"""Multi-provider web search with fan-out branches, bounded timeouts and diagnostics.

Provider keys are optional. Public HTML/RSS/API fallbacks are best-effort because
public providers may rate-limit automated traffic or change their markup.
"""
from __future__ import annotations

import concurrent.futures
import html
import json
import logging
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Any

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "Chrome/128.0.0.0 Safari/537.36 ChantaodiSearch/4.0")
STOP = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "how", "what", "when", "where", "why", "who", "can", "could", "would", "should", "you", "your", "about", "into", "latest", "official", "documentation",
    "các", "những", "đang", "được", "như", "nào", "làm", "sao", "thế", "với", "của", "cho", "trong", "ngoài", "và", "là", "một", "có", "không", "tôi", "bạn", "này", "đó", "khi", "theo", "tại", "để", "về", "mới", "hãy", "giúp", "tìm", "kiếm",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "vi,en-US;q=0.8,en;q=0.6"})
    return s


def _clean(value: Any, limit: int = 1800) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    value = BeautifulSoup(html.unescape(str(value)), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _valid_result(title: Any, url: Any, content: Any, provider: str, branch: str = "primary") -> dict | None:
    title, url = _clean(title, 300), str(url or "").strip()
    parsed = urllib.parse.urlparse(url)
    if not title or parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return {"title": title, "url": url[:1200], "content": _clean(content, 1800),
            "provider": provider, "branch": branch}


def _tavily(query: str, limit: int) -> list[dict]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("API key chưa cấu hình")
    r = requests.post("https://api.tavily.com/search", json={
        "api_key": key, "query": query, "search_depth": "basic", "max_results": limit,
        "include_answer": False, "include_raw_content": False,
    }, timeout=(3, 7))
    r.raise_for_status()
    data = r.json()
    out = []
    for x in data.get("results", []):
        item = _valid_result(x.get("title"), x.get("url"), x.get("content"), "Tavily")
        if item: out.append(item)
    return out


def _brave(query: str, limit: int) -> list[dict]:
    key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        raise RuntimeError("API key chưa cấu hình")
    r = requests.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": limit},
                     headers={"X-Subscription-Token": key, "Accept": "application/json"}, timeout=(3, 7))
    r.raise_for_status()
    data, out = r.json(), []
    for x in data.get("web", {}).get("results", []):
        item = _valid_result(x.get("title"), x.get("url"), x.get("description"), "Brave")
        if item: out.append(item)
    return out


def _duckduckgo(query: str, limit: int) -> list[dict]:
    url = "https://html.duckduckgo.com/html/"
    r = _session().post(url, data={"q": query}, timeout=(3, 6))
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for result in soup.select(".result"):
        a = result.select_one("a.result__a")
        if not a:
            continue
        href = a.get("href", "")
        parsed = urllib.parse.urlparse(href)
        if "duckduckgo.com" in (parsed.hostname or ""):
            target = urllib.parse.parse_qs(parsed.query).get("uddg", [None])[0]
            if target: href = target
        snippet = result.select_one(".result__snippet")
        item = _valid_result(a.get_text(" ", strip=True), href,
                             snippet.get_text(" ", strip=True) if snippet else "", "DuckDuckGo")
        if item: out.append(item)
        if len(out) >= limit: break
    if not out:
        raise RuntimeError("Không trích xuất được kết quả HTML")
    return out


def _bing(query: str, limit: int) -> list[dict]:
    r = _session().get("https://www.bing.com/search", params={"q": query}, timeout=(3, 6))
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for node in soup.select("li.b_algo"):
        a = node.select_one("h2 a")
        if not a: continue
        snippet = node.select_one(".b_caption p") or node.select_one("p")
        item = _valid_result(a.get_text(" ", strip=True), a.get("href", ""),
                             snippet.get_text(" ", strip=True) if snippet else "", "Bing")
        if item: out.append(item)
        if len(out) >= limit: break
    if not out:
        raise RuntimeError("Không trích xuất được kết quả HTML")
    return out


def _wikipedia(query: str, limit: int) -> list[dict]:
    lang = "vi" if re.search(r"[à-ỹđ]", query.lower()) else "en"
    r = _session().get(f"https://{lang}.wikipedia.org/w/api.php", params={
        "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": min(limit, 8),
    }, timeout=(2, 5))
    r.raise_for_status()
    out = []
    for x in r.json().get("query", {}).get("search", []):
        url = f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(x["title"].replace(" ", "_"))
        item = _valid_result(x.get("title"), url, x.get("snippet"), "Wikipedia")
        if item: out.append(item)
    return out


def _google_news(query: str, limit: int) -> list[dict]:
    r = _session().get("https://news.google.com/rss/search", params={
        "q": query, "hl": "vi", "gl": "VN", "ceid": "VN:vi",
    }, timeout=(2, 6))
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for node in root.findall(".//item")[:limit]:
        item = _valid_result(node.findtext("title"), node.findtext("link"), node.findtext("description"), "Google News", "freshness")
        if item: out.append(item)
    if not out:
        raise RuntimeError("RSS không trả kết quả")
    return out


def _score(item: dict, query: str) -> float:
    terms = [w for w in dict.fromkeys(re.findall(r"[\w-]+", query.casefold(), re.UNICODE)) if len(w) > 2 and w not in STOP]
    title, body = item["title"].casefold(), (item["title"] + " " + item.get("content", "") + " " + item["url"]).casefold()
    score = sum(4 if t in title else 1 for t in terms if t in body)
    if query.casefold() in title: score += 5
    host = (urllib.parse.urlparse(item["url"]).hostname or "").lower()
    if host.endswith((".gov", ".gov.vn", ".edu", ".edu.vn")): score += 2
    if item["provider"] in ("Tavily", "Brave"): score += 1
    if item.get("branch") == "official": score += 1
    return score


def _branches(query: str, deep: bool) -> list[tuple[str, str]]:
    vi = bool(re.search(r"[à-ỹđ]", query.lower()))
    out = [("primary", query)]
    if deep:
        out.append(("official", query + (" tài liệu chính thức documentation official" if vi else " official documentation")))
        out.append(("freshness", query + (" tin mới cập nhật" if vi else " latest news updates")))
    return [(name, q[:500]) for name, q in out]


def web_search(query: str, limit: int = 8, deep: bool = False) -> dict:
    """Run independent search branches/providers concurrently and return provider health."""
    query = str(query or "").strip()[:500]
    try: limit = max(1, min(int(limit), 15))
    except (ValueError, TypeError): limit = 8
    if not query:
        return {"available": False, "query": "", "results": [], "providers": [], "failed_providers": [], "note": "Nhập từ khóa cần tìm."}

    branches = _branches(query, deep)
    configured = []
    # Use keyed APIs preferentially. Public fallbacks stay enabled to make first-run search possible.
    if os.getenv("TAVILY_API_KEY", "").strip(): configured.append(("Tavily", _tavily))
    if os.getenv("BRAVE_SEARCH_API_KEY", "").strip(): configured.append(("Brave", _brave))
    configured.extend([("DuckDuckGo", _duckduckgo), ("Bing", _bing), ("Wikipedia", _wikipedia)])
    fresh_pattern = r"today|latest|recent|news|release|current|hôm nay|mới nhất|tin tức|cập nhật|hiện nay|gần đây"
    if deep or re.search(fresh_pattern, query, re.I):
        configured.append(("Google News", _google_news))

    try: timeout = max(2, min(float(os.getenv("SEARCH_TIMEOUT_SECONDS", "8")), 15))
    except ValueError: timeout = 8
    tasks = []
    # Primary query is fanned out to independent providers. Secondary branches target docs and freshness.
    for branch, branch_query in branches:
        allowed = configured if branch == "primary" else [p for p in configured if p[0] in (
            ("Tavily", "Brave", "Bing", "DuckDuckGo") if branch == "official" else ("Google News", "Bing", "Tavily", "Brave")
        )]
        for provider, fn in allowed:
            tasks.append((branch, branch_query, provider, fn))
    results: list[dict] = []
    provider_status: dict[str, dict] = {}
    started = time.monotonic()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(tasks))))
    future_map = {pool.submit(fn, q, min(limit, 10)): (branch, q, name)
                  for branch, q, name, fn in tasks}
    try:
        done, pending = concurrent.futures.wait(future_map, timeout=timeout)
        for future in done:
            branch, branch_query, name = future_map[future]
            status = provider_status.setdefault(name, {"provider": name, "ok": False, "branches": [], "error": ""})
            try:
                found = future.result()
                if found:
                    status["ok"] = True
                    if branch not in status["branches"]: status["branches"].append(branch)
                    for item in found:
                        item["branch"] = branch
                        item["_score"] = _score(item, query)
                        # Score content against the original query; branch label slightly favors official docs.
                        results.append(item)
                elif not status["error"]:
                    status["error"] = "Không có kết quả phù hợp"
            except Exception as exc:
                log.info("Search provider %s failed (%s)", name, type(exc).__name__)
                status["error"] = type(exc).__name__
        for future in pending:
            _, _, name = future_map[future]
            status = provider_status.setdefault(name, {"provider": name, "ok": False, "branches": [], "error": ""})
            status["error"] = "timeout"
            future.cancel()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    unique: dict[str, dict] = {}
    for item in results:
        p = urllib.parse.urlparse(item["url"])
        key = p._replace(query="", fragment="").geturl().rstrip("/").casefold()
        existing = unique.get(key)
        if not existing or item["_score"] > existing["_score"]:
            unique[key] = item
    ranked = sorted(unique.values(), key=lambda x: (x["_score"], x.get("provider") in ("Tavily", "Brave")), reverse=True)
    for item in ranked: item.pop("_score", None)
    statuses = list(provider_status.values())
    ok_providers = [x["provider"] for x in statuses if x["ok"]]
    failures = [x["provider"] for x in statuses if not x["ok"]]
    return {
        "available": bool(ranked), "query": query, "deep": deep,
        "results": ranked[:limit], "providers": list(dict.fromkeys(ok_providers)),
        "failed_providers": list(dict.fromkeys(failures)), "provider_status": statuses,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "branches": [{"name": name, "query": q} for name, q in branches],
        "note": "" if ranked else "Không lấy được kết quả từ nguồn tìm kiếm. Kiểm tra mạng outbound của Render hoặc cấu hình TAVILY_API_KEY/BRAVE_SEARCH_API_KEY.",
    }
