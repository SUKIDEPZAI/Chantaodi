#!/usr/bin/env python3
"""Apply the Codex-inspired UI and multi-branch search upgrade to MotAPI Studio v3.

Usage:
    python apply_upgrade.py /path/to/Chantaodi

The script refuses to write unless the expected source markers are found.
It preserves the original Flask/SQLite architecture and existing API routes.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys


SEARCH_IMPL = r'''def _search_tavily(query, n, key):
    req = urllib.request.Request(
        'https://api.tavily.com/search',
        data=json.dumps({
            'api_key': key, 'query': query[:500], 'search_depth': 'basic',
            'max_results': min(max(1, int(n)), 10),
        }).encode(),
        method='POST', headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        data = json.loads(response.read().decode('utf-8', 'replace'))
    return [
        {
            'title': str(item.get('title', ''))[:300],
            'url': str(item.get('url', ''))[:1000],
            'content': str(item.get('content', ''))[:1800],
            'provider': 'Tavily',
        }
        for item in data.get('results', [])[:min(max(1, int(n)), 10)]
    ]


def _search_score(item, query):
    stop = {
        'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'was', 'how',
        'what', 'when', 'where', 'why', 'who', 'can', 'could', 'would', 'should',
        'you', 'your', 'about', 'into', 'official', 'documentation', 'latest',
        'các', 'những', 'đang', 'được', 'như', 'nào', 'làm', 'sao', 'thế',
        'với', 'của', 'cho', 'trong', 'ngoài', 'và', 'là', 'một', 'có', 'không',
        'tôi', 'bạn', 'này', 'đó', 'khi', 'theo', 'tại', 'để', 'về', 'mới',
    }
    terms = [w for w in dict.fromkeys(re.findall(r'\w+', query.lower(), re.UNICODE))
             if len(w) > 2 and w not in stop]
    title = str(item.get('title', '')).lower()
    body = (title + ' ' + str(item.get('content', '')).lower() + ' ' +
            str(item.get('url', '')).lower())
    score = sum(4 if word in title else 1 for word in terms if word in body)
    phrase = query.strip().lower()
    if phrase and phrase in title:
        score += 5
    if item.get('provider') == 'Tavily':
        score += 1
    try:
        host = (urllib.parse.urlparse(str(item.get('url', ''))).hostname or '').lower()
        if host.endswith(('.gov', '.gov.vn', '.edu', '.edu.vn')):
            score += 2
    except Exception:
        pass
    return score


def web_search(query, limit=6, deep=False):
    """Search several providers concurrently; deep mode fans out into related queries."""
    try:
        limit = max(1, min(int(limit), 10))
    except (TypeError, ValueError):
        limit = 6
    query = str(query or '').strip()[:500]
    if not query:
        return {'available': False, 'provider': 'none', 'providers': [], 'results': [],
                'failed_providers': [], 'note': 'Nhập từ khóa tìm kiếm.'}

    key = os.getenv('TAVILY_API_KEY', '').strip()
    vietnamese = bool(re.search(r'[à-ỹđ]', query.lower()))
    fresh = bool(re.search(
        r'hiện nay|hôm nay|mới nhất|gần đây|tin tức|cập nhật|202[5-9]|today|latest|recent|news|release',
        query, re.I,
    ))
    tasks = [
        ('DuckDuckGo', 'chính', query, _search_ddg),
        ('Bing', 'chính', query, _search_bing),
        ('Wikipedia', 'bối cảnh', query, _search_wiki),
    ]
    if key:
        tasks.append(('Tavily', 'chính', query, lambda q, n, k=key: _search_tavily(q, n, k)))

    if deep:
        docs_query = (query + (' tài liệu chính thức' if vietnamese else ' official documentation'))[:500]
        latest_query = (query + (' tin mới cập nhật' if vietnamese else ' latest developments'))[:500]
        # One specialized branch finds official documentation; the other focuses on recent updates.
        if key:
            tasks.append(('Tavily', 'tài liệu', docs_query,
                          lambda q, n, k=key: _search_tavily(q, n, k)))
        else:
            tasks.append(('Bing', 'tài liệu', docs_query, _search_bing))
        tasks.append(('Bing', 'cập nhật', latest_query, _search_bing))
        tasks.append(('Google News', 'cập nhật', latest_query, _search_news))
    elif fresh:
        tasks.append(('Google News', 'cập nhật', query, _search_news))

    try:
        timeout = max(2.0, min(float(os.getenv('SEARCH_TIMEOUT_SECONDS', '9')), 20.0))
    except (TypeError, ValueError):
        timeout = 9.0
    pool = ThreadPoolExecutor(max_workers=min(8, len(tasks)))
    futures = {pool.submit(fn, q, limit): (provider, branch)
               for provider, branch, q, fn in tasks}
    results, providers, errors = [], [], []
    try:
        done, pending = wait(futures, timeout=timeout)
        for future in done:
            provider, branch = futures[future]
            try:
                found = future.result()
                if not found:
                    errors.append(provider)
                    continue
                for item in found:
                    if not isinstance(item, dict):
                        continue
                    item = dict(item)
                    item['branch'] = branch
                    item.setdefault('provider', provider)
                    results.append(item)
                providers.append(provider)
            except Exception as exc:
                logging.info('%s search failed (%s)', provider, type(exc).__name__)
                errors.append(provider)
        for future in pending:
            provider, _ = futures[future]
            future.cancel()
            errors.append(provider + ' (timeout)')
    finally:
        # Don't let a slow provider block the first streamed progress event indefinitely.
        pool.shutdown(wait=False, cancel_futures=True)

    seen, uniq = set(), []
    for item in results:
        url = str(item.get('url', '')).strip()
        title = str(item.get('title', '')).strip()
        if not title or not url.startswith(('https://', 'http://')):
            continue
        parsed = urllib.parse.urlparse(url)
        if not parsed.hostname:
            continue
        canonical = parsed._replace(query='', fragment='').geturl().rstrip('/').lower()
        if canonical in seen:
            continue
        seen.add(canonical)
        item['_score'] = _search_score(item, query)
        uniq.append(item)
    uniq.sort(key=lambda item: (item.get('_score', 0),
                                item.get('provider') == 'Tavily'), reverse=True)
    for item in uniq:
        item.pop('_score', None)
    unique_providers = list(dict.fromkeys(providers))
    unique_errors = list(dict.fromkeys(errors))
    return {
        'available': bool(uniq),
        'provider': ' + '.join(unique_providers) or 'none',
        'providers': unique_providers,
        'results': uniq[:limit],
        'failed_providers': unique_errors,
        'branches': 3 if deep else 1,
        'note': '' if uniq else
                'Chưa lấy được kết quả. Có thể mạng của máy chủ chặn nguồn tìm kiếm; hãy thử lại hoặc cấu hình TAVILY_API_KEY.',
    }
'''


CSS = r'''/* Codex-inspired redesign for MotAPI Studio; functional IDs remain unchanged. */
:root{color-scheme:dark;--bg:#0b0b0b;--p1:#111111;--p2:#191919;--ln:#ffffff17;--tx:#f1f1f1;--mu:#a0a0a0;--ac:#d7d7d7;--mn:#a5d6a7;--bad:#ff9b9b;--f:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;--m:"SFMono-Regular",Consolas,"Liberation Mono",monospace}
*{box-sizing:border-box}html,body{height:100%;background:#0b0b0b}body{margin:0;background:radial-gradient(ellipse at 50% -35%,#1b1b1b 0,#0b0b0b 58%);color:var(--tx);font:14px/1.6 var(--f);letter-spacing:.005em}button,input,textarea,select{font:inherit;color:inherit}button{cursor:pointer;transition:background .15s,border-color .15s,color .15s}button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:2px solid #bcbcbc;outline-offset:2px}.hidden{display:none!important}
.app{height:100dvh;grid-template-columns:260px minmax(0,1fr) 0;transition:grid-template-columns .18s}.app.panel-open{grid-template-columns:260px minmax(0,1fr) minmax(360px,43%)}
.side{padding:16px 12px 12px;background:#101010;border-right:1px solid #ffffff12;gap:12px}.brand{gap:10px;padding:3px 8px 12px;font-size:13px;font-weight:650;letter-spacing:.015em;color:#e8e8e8}.logo{width:29px;height:29px;border-radius:9px;background:#e5e5e5;color:#111;box-shadow:none;font-size:16px}.btn{border:1px solid #ffffff19;background:#ffffff06;border-radius:9px;padding:7px 10px;font-size:12px;color:#d5d5d5}.btn:hover{background:#ffffff10;border-color:#ffffff30;color:#fff}.new{padding:10px 12px;background:#ededed;color:#141414;border:1px solid #ededed;font-weight:650;border-radius:11px}.new:hover{background:#fff;color:#050505}.search{width:100%;background:#171717;border:1px solid #ffffff16;border-radius:9px;padding:9px 10px;color:#ededed;outline:none;font-size:12px}.search:focus{border-color:#ffffff39}.hist{padding-top:2px;scrollbar-width:thin;scrollbar-color:#393939 transparent}.hi{gap:7px;padding:8px 8px;border:1px solid transparent;border-radius:8px;color:#b0b0b0;font-size:12px}.hi:hover,.hi.on{background:#ffffff0b;border-color:#ffffff08;color:#f3f3f3}.hi span{flex:1;min-width:0}.hi button{opacity:.55}.hi:hover button{opacity:1}.projrow{gap:5px}.projrow select{flex:1;min-width:0}.ws{border-top:1px solid var(--ln);padding:11px 6px 0;max-height:36%;gap:6px}.ws summary{font-size:12px;color:#c8c8c8}.wsbar .btn{padding:5px 7px}.wsl{scrollbar-width:thin}.wf{gap:5px;padding:4px 0;font-size:11px}.wf .n{color:#b1b1b1}.wf button{border-radius:5px}.side .st{padding:7px 6px;color:#8c8c8c;font-size:11px}
.main{background:transparent}.top{min-height:56px;padding:10px 20px;border-bottom:1px solid #ffffff12;background:#0b0b0bc9;backdrop-filter:blur(18px);gap:10px}.top .t{font-size:13px;color:#dedede;font-weight:550}.top .model{max-width:205px;background:#151515;border:1px solid #ffffff19;border-radius:9px;padding:7px 9px;font-size:12px}.top .st{font-size:11px}.top #testApi{font-size:11px}.chat{scrollbar-width:thin;scrollbar-color:#303030 transparent}.welcome{gap:0;padding:38px 18px 28px}.welcome>.logo{width:42px!important;height:42px!important;border-radius:14px!important;margin-bottom:22px!important;background:#f0f0f0!important;color:#151515!important;font-size:22px!important}.welcome h1{font-size:clamp(26px,3.3vw,36px);font-weight:560;letter-spacing:-1.15px;line-height:1.18;margin-bottom:12px}.welcome p{max-width:540px;color:#9b9b9b;font-size:13px;margin-bottom:26px}.cards{width:min(660px,100%);grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.card{background:#111;border:1px solid #ffffff16;border-radius:13px;padding:15px 15px;min-height:82px;box-shadow:0 1px 1px #0003}.card:hover{background:#181818;border-color:#ffffff35;transform:translateY(-1px)}.card b{font-size:12px;font-weight:600;color:#e9e9e9;margin-bottom:3px}.card span{font-size:11px;line-height:1.55;color:#929292}
.msgs{max-width:900px;padding:28px 24px 40px;gap:24px}.m.user{max-width:82%;background:#202020;border:1px solid #ffffff10;border-radius:17px 17px 5px 17px;padding:11px 15px;color:#ededed}.m.ai .meta{font-size:11px;color:#919191;margin-bottom:8px}.txt{font-size:14px;line-height:1.75;color:#e7e7e7}.txt p{margin:0 0 12px}.txt h1,.txt h2,.txt h3{color:#f2f2f2;font-weight:600;letter-spacing:-.02em}.txt a{color:#bdd3ff;text-decoration:underline;text-underline-offset:3px}.txt blockquote{border-left:2px solid #777;color:#b5b5b5}.txt code{background:#242424;border:1px solid #ffffff0c;color:#e8e8e8;border-radius:5px;padding:2px 5px;font-size:12px}.tw{border:1px solid #ffffff14;border-radius:10px}.txt table{font-size:12px}.txt th,.txt td{border-color:#ffffff16;padding:8px 10px}.txt th{background:#1c1c1c}.cb,.file{border:1px solid #ffffff16;border-radius:11px;background:#111;overflow:hidden;margin:10px 0}.ch{display:flex;align-items:center;gap:8px;padding:8px 10px;background:#171717;border-bottom:1px solid #ffffff12;color:#aaa;font-size:11px}.ch .sp{flex:1}.ch button{border:0;background:transparent;color:#aaa;font-size:11px}.ch button:hover{color:#fff}.cb pre{margin:0;padding:13px 14px;overflow:auto;background:#0d0d0d}.cb code{border:0;background:transparent;font:12px/1.7 var(--m);padding:0}.file{display:flex;align-items:center;gap:10px;padding:10px 12px}.file .nm{flex:1;min-width:0;color:#eee}.file small{display:block;color:#888;font-size:10px}.file .ic{opacity:.8}.think{border-color:#ffffff15;border-radius:10px;background:#111}.think summary{padding:8px 11px;color:#b7b7b7;font-size:12px}.think .tb{font-size:12px;color:#999;white-space:pre-wrap}.dot{background:#b8b8b8}.run .dot{animation:pulse 1.2s infinite}.acts{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}.acts .btn{font-size:11px;padding:6px 9px}.acts select.btn{background:#151515}
.comp{padding:0 22px 12px;background:linear-gradient(180deg,transparent,#0b0b0b 22%)}.box{width:min(900px,100%);margin:0 auto;background:#151515;border:1px solid #ffffff21;border-radius:17px;padding:11px 13px 10px;box-shadow:0 12px 35px #0004}.modes{display:flex;align-items:center;gap:5px;padding:0 0 8px;border-bottom:1px solid #ffffff0c}.mode{border:1px solid transparent;background:transparent;color:#999;border-radius:7px;padding:5px 9px;font-size:11px}.mode:hover{background:#ffffff08;color:#ddd}.mode.on{background:#292929;border-color:#ffffff12;color:#f1f1f1}.sw{display:flex;align-items:center;gap:5px;margin-left:auto;color:#999;font-size:11px}.sw input{accent-color:#ccc}.chips{display:flex;gap:6px;flex-wrap:wrap;padding-top:8px}.chip{display:flex;align-items:center;gap:6px;border:1px solid #ffffff18;background:#202020;border-radius:8px;padding:4px 7px;font-size:11px;color:#bbb}.chip img{width:20px;height:20px;object-fit:cover;border-radius:4px}#prompt{display:block;width:100%;min-height:54px;max-height:200px;resize:none;border:0;outline:0;background:transparent;color:#f1f1f1;padding:12px 1px 8px;font-size:14px;line-height:1.6}#prompt::placeholder{color:#7d7d7d}.bar{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.bar .btn{background:transparent;border-color:#ffffff14;color:#b3b3b3;padding:6px 9px}.bar .btn:hover{background:#ffffff0c;color:#fff}.send{margin-left:auto;border:0;border-radius:9px;background:#efefef;color:#111;padding:7px 13px;font-size:12px;font-weight:650}.send:hover{background:white}.send:disabled{opacity:.5;cursor:wait}.hint{width:min(900px,100%);margin:7px auto 0;color:#656565;font-size:10px;text-align:center}.toast{bottom:20px;background:#222;border:1px solid #ffffff21;border-radius:10px;padding:10px 14px;color:#f1f1f1;box-shadow:0 10px 32px #0007;z-index:80}
.panel{background:#0d0d0d;border-left:1px solid #ffffff16;min-width:0}.ph{display:flex;align-items:center;gap:6px;padding:10px 12px;border-bottom:1px solid #ffffff12;background:#111}.ph b{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;font-weight:600}.ph .btn{font-size:11px}.pv{background:#fff}.pv iframe{background:#fff}.pc{background:#0c0c0c;color:#e3e3e3;font:12px/1.7 var(--m)}
@media(max-width:900px){.app,.app.panel-open{grid-template-columns:minmax(0,1fr)}.side{position:fixed;inset:0 auto 0 0;width:min(290px,86vw);z-index:30;transform:translateX(-102%);transition:transform .2s;box-shadow:24px 0 70px #0008}.side.open{transform:none}.menu{display:inline-block}.panel{position:fixed;inset:0;z-index:40}.cards{grid-template-columns:1fr}.model{max-width:36vw}.m.user{max-width:94%}.top{padding:9px 11px;gap:6px}.top #testApi{display:none}.top .t{font-size:12px}.msgs{padding:18px 12px 28px}.comp{padding:0 8px 8px}.box{border-radius:15px;padding:9px 10px}.welcome{padding:24px 14px}.welcome h1{font-size:27px}.welcome p{font-size:12px}.cards{max-width:460px}.hint{padding:0 8px}.acts{gap:5px}}
@media(max-width:420px){.top .model{max-width:118px}.st{display:none}.modes{gap:2px}.mode{padding:5px 7px}.sw{font-size:10px}.bar .btn{padding:6px 7px;font-size:10px}.send{padding:7px 10px}.welcome h1{font-size:25px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;scroll-behavior:auto!important;transition:none!important}}
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Không áp dụng được mục '{label}': cần 1 vị trí, tìm thấy {count}. File có thể đã thay đổi.")
    return text.replace(old, new, 1)


def upgrade_server(src: str) -> str:
    src = replace_once(src,
        'from concurrent.futures import ThreadPoolExecutor, as_completed',
        'from concurrent.futures import ThreadPoolExecutor, wait', 'import concurrent futures')
    src = replace_once(src,
        "@app.get('/')\ndef home(): return send_from_directory(ROOT, 'index.html')",
        "@app.get('/')\ndef home():\n    # Inject the optional theme file while keeping index.html as the single-page app.\n    page_path = os.path.join(ROOT, 'index.html')\n    with open(page_path, 'r', encoding='utf-8') as f:\n        page = f.read()\n    theme_path = os.path.join(ROOT, 'codex.css')\n    if os.path.isfile(theme_path):\n        with open(theme_path, 'r', encoding='utf-8') as f:\n            theme = f.read()\n        page = page.replace('</head>', '<style id=\"codex-theme\">\\n' + theme + '\\n</style></head>', 1)\n    return Response(page, mimetype='text/html; charset=utf-8')",
        'home route')
    start = src.find('def web_search(query, limit=6):')
    end = src.find('# ---------------- Đọc liên kết trong tin nhắn (chống SSRF) ----------------')
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError('Không tìm thấy khối web_search trong server.py.')
    src = src[:start] + SEARCH_IMPL + '\n\n' + src[end:]

    redirect_class = """class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Revalidate every redirect target so a public URL cannot redirect directly to localhost/private IPs.
        if not _public_url(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


"""
    src = replace_once(src, "def fetch_links(text, limit=2):", redirect_class + "def fetch_links(text, limit=2):", 'safe redirect handler')
    src = replace_once(src,
        "with urllib.request.urlopen(req, timeout=10) as r:",
        "with urllib.request.build_opener(_SafeRedirectHandler()).open(req, timeout=10) as r:",
        'validate link redirects')

    src = replace_once(src,
        "    r = web_search(q, d.get('max_results', 5))",
        "    r = web_search(q, d.get('max_results', 5), deep=bool(d.get('deep', False)))",
        'search endpoint')
    src = replace_once(src,
        "    use_search = request.form.get('web_search', 'false').lower() == 'true'; custom = request.form.get('custom', '').strip()[:2000]",
        "    use_search = request.form.get('web_search', 'false').lower() == 'true'; deep_search = mode == 'research' or request.form.get('deep_search', 'false').lower() == 'true'; custom = request.form.get('custom', '').strip()[:2000]",
        'chat search settings')
    old_search = """    search = web_search(message, 6) if use_search and message else None
    if search and search.get('available'):
        refs = ['KẾT QUẢ TÌM KIẾM WEB (' + search['provider'] + '). Hãy kiểm chứng, dẫn nguồn bằng [số], không bịa thêm nguồn:']
        refs += [f\"[{i}] {x['title']}\\nURL: {x['url']}\\nNội dung: {x['content']}\" for i, x in enumerate(search['results'], 1)]
        user[0]['text'] += '\\n\\n' + '\\n\\n'.join(refs)
"""
    src = replace_once(src, old_search, '    search = None\n', 'defer search until streaming starts')
    src = replace_once(src,
        "    def generate():\n        got, thk = [], []\n        try:\n            if ws_parts:",
        "    def generate():\n        nonlocal search\n        got = []\n        try:\n            if use_search and message:\n                yield ev({'status': 'Đang tìm kiếm song song trên nhiều nguồn' + (' và mở rộng thành nhiều nhánh truy vấn.' if deep_search else '.')})\n                try:\n                    search = web_search(message, 8 if deep_search else 6, deep=deep_search)\n                except Exception as exc:\n                    logging.warning('web search failed (%s)', type(exc).__name__)\n                    search = {'available': False, 'provider': 'none', 'results': [], 'note': 'Tìm kiếm đang tạm thời không khả dụng.'}\n                if search.get('available'):\n                    refs = ['KẾT QUẢ TÌM KIẾM WEB (' + search['provider'] + '). Đối chiếu nguồn, ưu tiên nguồn đáng tin cậy và dẫn URL cụ thể; không bịa nguồn:']\n                    refs += [f\"[{i}] {x['title']}\\nURL: {x['url']}\\nNguồn: {x.get('provider', 'web')} · Nhánh: {x.get('branch', 'chính')}\\nNội dung: {x['content']}\" for i, x in enumerate(search['results'], 1)]\n                    user[0]['text'] += '\\n\\n' + '\\n\\n'.join(refs)\n                    yield ev({'status': f\"Đã đối chiếu {len(search['results'])} kết quả từ {search['provider']}.\"})\n                else:\n                    yield ev({'status': search.get('note') or 'Không lấy được kết quả web; tiếp tục dựa trên ngữ cảnh sẵn có.'})\n            if ws_parts:",
        'stream search progress')
    old_reasoning = """                r = getattr(dl, 'reasoning_content', None) or getattr(dl, 'reasoning', None)
                if isinstance(r, str) and r: thk.append(r); yield ev({'think': r})
                c = getattr(dl, 'content', None)
"""
    src = replace_once(src, old_reasoning,
        "                # Never forward hidden reasoning to the browser; only stream user-facing answer content.\n                c = getattr(dl, 'content', None)\n",
        'hide raw model reasoning')
    src = replace_once(src,
        "        finally:  # lưu cả phần trả lời dở dang khi người dùng bấm Dừng\n            if cid and got: add_msg(cid, 'assistant', ('<think>' + ''.join(thk) + '</think>' if thk else '') + ''.join(got))",
        "        finally:  # Lưu phần trả lời hiển thị đã tạo, kể cả khi người dùng bấm Dừng.\n            if cid and got: add_msg(cid, 'assistant', ''.join(got))",
        'persist visible response only')

    # Validate the inserted changes before returning.
    for marker in ('def _search_tavily(', 'def _search_score(', 'def web_search(query, limit=6, deep=False):',
                   "deep_search = mode == 'research'", "nonlocal search", 'Never forward hidden reasoning'):
        if marker not in src:
            raise RuntimeError(f'Thiếu thay đổi bắt buộc trong server.py: {marker}')
    return src


def upgrade_index(src: str) -> str:
    # Historical rows may already contain <think> from earlier builds; never render them in the UI.
    old = r"function parse(raw){let think='',text=raw;const m=text.match(/<think>([\s\S]*?)(<\/think>|$)/);if(m){think=m[1].trim();text=text.replace(m[0],'')}"
    new = r"function parse(raw){let think='',text=raw;const m=text.match(/<think>([\s\S]*?)(<\/think>|$)/);if(m){text=text.replace(m[0],'')}"
    src = replace_once(src, old, new, 'hide old stored reasoning in UI')
    # Add two high-value prompts without changing the existing card click wiring.
    close = src.find('</div>', src.find('<div class="cards">'))
    if close < 0:
        raise RuntimeError('Không tìm thấy khối thẻ gợi ý trong index.html.')
    if 'data-p="Nghiên cứu đa nhánh' not in src:
        extra = ('<button class="card" data-p="Nghiên cứu đa nhánh về chủ đề này; đối chiếu tài liệu chính thức với cập nhật gần đây, tóm tắt kết luận và dẫn URL cho từng nguồn." data-m="research"><b>Nghiên cứu đa nhánh</b><span>Đối chiếu tài liệu và cập nhật</span></button>'
                 '<button class="card" data-p="Rà soát toàn bộ code/tệp đính kèm; tìm lỗi logic, bảo mật, API và hiệu năng. Đưa đề xuất sửa theo mức ưu tiên, kèm patch và test kiểm chứng." data-m="coding"><b>Rà soát code chuyên sâu</b><span>Lỗi, bảo mật, API và kiểm thử</span></button>')
        src = src[:close] + extra + src[close:]
    return src


def upgrade_export_routes(src: str) -> str:
    old = "1) Câu hỏi phức tạp: mở đầu bằng một khối <think>…</think> gồm 3-6 gạch đầu dòng ngắn tóm tắt cách tiếp cận, giả định, điểm cần kiểm chứng; rồi mới trả lời. Câu hỏi đơn giản thì bỏ qua.\n"
    new = "1) Câu hỏi phức tạp: mở đầu bằng kế hoạch ngắn 3-6 gạch đầu dòng, nêu giả định và điểm cần kiểm chứng; không tiết lộ suy luận nội bộ hoặc chuỗi suy nghĩ ẩn. Câu hỏi đơn giản thì trả lời trực tiếp.\n"
    return replace_once(src, old, new, 'remove contradictory hidden-reasoning instruction')


def upgrade_files_routes(src: str) -> str:
    old = """            os.remove(dest); ok = sum(len(fs) for _, _, fs in os.walk(folder)); added += ok
            notes.append(f'{name}: đã giải nén {ok} tệp.')"""
    new = """            if _usage(root) > MAX_TOTAL:
                shutil.rmtree(folder, ignore_errors=True)
                notes.append(f'{name}: giải nén vượt giới hạn workspace {MAX_TOTAL >> 20} MB; đã hủy giải nén, giữ tệp gốc.')
                continue
            os.remove(dest); ok = sum(len(fs) for _, _, fs in os.walk(folder)); added += ok
            notes.append(f'{name}: đã giải nén {ok} tệp.')"""
    return replace_once(src, old, new, 'enforce workspace limit after archive expansion')


def upgrade_tests(src: str) -> str:
    marker = "if __name__ == '__main__': unittest.main()"
    addition = r'''
    def test_hidden_reasoning_is_not_streamed_or_saved(self):
        class _ReasoningFake:
            class chat:
                class completions:
                    @staticmethod
                    def create(**params):
                        return iter([
                            NS(choices=[NS(delta=NS(content=None, reasoning_content='PRIVATE_INTERNAL_REASONING'))]),
                            NS(choices=[NS(delta=NS(content='Câu trả lời hiển thị.', reasoning_content=None))]),
                        ])
        original = server.client
        server.client = lambda: _ReasoningFake
        try:
            response = c.post('/api/chat', headers=A, buffered=True, data={
                'message': 'kiểm tra trạng thái', 'model': 'm',
                'conv_id': 'conv-hidden-0001', 'client_id': 'cm-hidden-1',
            })
            body = response.get_data(as_text=True)
            self.assertNotIn('PRIVATE_INTERNAL_REASONING', body)
            saved = msgs(A, 'conv-hidden-0001')[-1]['content']
            self.assertNotIn('<think>', saved)
            self.assertNotIn('PRIVATE_INTERNAL_REASONING', saved)
            self.assertIn('Câu trả lời hiển thị.', saved)
        finally:
            server.client = original

'''
    if marker not in src:
        raise RuntimeError('Không tìm thấy điểm chèn bài kiểm thử trong test_app.py.')
    if 'test_hidden_reasoning_is_not_streamed_or_saved' in src:
        return src
    return src.replace(marker, addition + marker, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', nargs='?', default='.', help='Đường dẫn thư mục Chantaodi đã tải về')
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    server_path, test_path = root / 'server.py', root / 'test_app.py'
    index_path, export_path = root / 'index.html', root / 'export_routes.py'
    files_path = root / 'files_routes.py'
    for path in (server_path, test_path, index_path, export_path, files_path):
        if not path.is_file():
            print(f'Không tìm thấy {path}. Hãy trỏ tới thư mục gốc repository.', file=sys.stderr)
            return 2

    server_original = server_path.read_text(encoding='utf-8')
    tests_original = test_path.read_text(encoding='utf-8')
    index_original = index_path.read_text(encoding='utf-8')
    export_original = export_path.read_text(encoding='utf-8')
    files_original = files_path.read_text(encoding='utf-8')
    server_new = upgrade_server(server_original)
    tests_new = upgrade_tests(tests_original)
    index_new = upgrade_index(index_original)
    export_new = upgrade_export_routes(export_original)
    files_new = upgrade_files_routes(files_original)
    css_path = root / 'codex.css'
    css_path.write_text(CSS, encoding='utf-8')
    server_path.write_text(server_new, encoding='utf-8')
    test_path.write_text(tests_new, encoding='utf-8')
    index_path.write_text(index_new, encoding='utf-8')
    export_path.write_text(export_new, encoding='utf-8')
    files_path.write_text(files_new, encoding='utf-8')
    print('Đã áp dụng nâng cấp MotAPI Studio:')
    print('  - Giao diện tối phong cách Codex trong codex.css (không thay framework).')
    print('  - Tìm kiếm nhiều nhánh, chạy song song, chấm điểm và gộp URL trùng.')
    print('  - Gửi trạng thái tìm kiếm trước khi đợi nhà cung cấp trả kết quả.')
    print('  - Không truyền/lưu reasoning nội bộ từ model; ẩn reasoning cũ khỏi giao diện.')
    print('  - Kiểm tra lại đích chuyển hướng khi đọc URL trong tin nhắn.')
    print('  - Bỏ chỉ thị yêu cầu model viết khối <think> mâu thuẫn với chính sách hiển thị.')
    print('  - Hủy giải nén nếu tổng workspace vượt ngưỡng dung lượng.')
    print('  - Thêm bài test kiểm tra không lộ reasoning.')
    print('\nBước tiếp theo: python -m py_compile server.py store.py files_routes.py export_routes.py')
    print('              python -m unittest -v test_app')
    print('              git diff --check && git diff')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
