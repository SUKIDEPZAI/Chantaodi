import os, re, json, base64, mimetypes, logging, hmac, socket, ipaddress, urllib.request, urllib.parse, html
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from openai import OpenAI
from export_routes import bp as export_bp, FILE_PROTOCOL
from files_routes import fb as files_bp, ws_list, ws_path

ROOT = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '25')) * 1024 * 1024
app.register_blueprint(export_bp)
app.register_blueprint(files_bp)
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36'
MODELS = ['DeepSeek-V4-Flash-0731', 'claude-sonnet-4-6', 'claude-sonnet-5', 'claude-sonnet-5-5', 'deepseek-v4-flash', 'glm-5.3-flash', 'gpt-5.6-sol', 'gpt-6-astra', 'gpt-6-luna', 'gpt-6-sol', 'grok-4.5', 'grok-4.6', 'hy3', 'hy4-preview', 'minimax-m2.7', 'minimax-m3', 'qwen3.8-max']
BASE = lambda: os.getenv('MOTAPIS_BASE_URL', 'https://motapis.com/v1').rstrip('/')


@app.before_request
def gate():
    """Tùy chọn: đặt APP_PASSWORD trên Render để người lạ không dùng hết credit của bạn."""
    pw = os.getenv('APP_PASSWORD', '').strip()
    if pw and request.path.startswith('/api/') and request.path != '/api/health':
        if not hmac.compare_digest(request.headers.get('X-App-Password', ''), pw):
            return jsonify(error='Cần mật khẩu truy cập.', auth=True), 401


def client():
    key = os.getenv('MOTAPIS_API_KEY', '').strip()
    if not key:
        raise RuntimeError('Chưa cấu hình MOTAPIS_API_KEY trong Render Environment.')
    return OpenAI(api_key=key, base_url=BASE(), timeout=float(os.getenv('API_TIMEOUT_SECONDS', '180')), max_retries=1)


def safe_error(exc):
    status = getattr(exc, 'status_code', None); body = getattr(exc, 'body', None); raw = str(exc)
    if isinstance(body, dict):
        raw += ' ' + ' '.join(str(body.get(k, '')) for k in ('code', 'reason', 'message', 'error'))
        if isinstance(body.get('error'), dict):
            raw += ' ' + ' '.join(str(body['error'].get(k, '')) for k in ('code', 'reason', 'message'))
    up = raw.upper()
    if any(s in up for s in ('NOT_ENOUGH_BALANCE', 'NOT ENOUGH BALANCE', 'INSUFFICIENT BALANCE')): return 'MộtAPI không đủ số dư. Kiểm tra credit trong dashboard MộtAPI.'
    if isinstance(exc, RuntimeError): return str(exc)
    m = {401: 'MộtAPI từ chối xác thực. Kiểm tra MOTAPIS_API_KEY trên Render.', 402: 'Tài khoản MộtAPI hết số dư hoặc không đủ credit.',
         403: 'MộtAPI từ chối yêu cầu. Kiểm tra quyền model, số dư và hạn mức.', 404: 'Không tìm thấy model hoặc endpoint. Kiểm tra tên model và MOTAPIS_BASE_URL.',
         429: 'MộtAPI đang giới hạn tốc độ hoặc quota. Hãy thử lại sau.'}
    if status in m: return m[status]
    if status and status >= 500: return 'Máy chủ MộtAPI hoặc nhà cung cấp model đang gặp lỗi.'
    logging.warning('Provider error type=%s status=%s', type(exc).__name__, status)
    return 'Gọi MộtAPI thất bại. Kiểm tra log Render và quyền model/API key.'


# ---------------- Web search ----------------
def _clean_html(v):
    v = re.sub(r'<script\b[^>]*>[\s\S]*?</script>|<style\b[^>]*>[\s\S]*?</style>', ' ', v, flags=re.I)
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', v)).replace('\xa0', ' ').split())


def _get(url, timeout=10, headers=None, limit=None):
    req = urllib.request.Request(url, headers=headers or {'User-Agent': UA, 'Accept-Language': 'vi,en;q=0.8'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit) if limit else r.read()


def _search_ddg(q, n):
    page = _get('https://html.duckduckgo.com/html/?q=' + urllib.parse.quote(q[:500]), 12).decode('utf-8', 'replace'); out = []
    for href, title, snip in re.findall(r'<a[^>]+class=["\']result__a["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>(.*?)(?=<div class=["\']result|</div>\s*</div>)', page, re.I | re.S):
        href = html.unescape(href)
        if 'uddg=' in href:
            href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get('uddg', [href])[0]
        if href.startswith('//'): href = 'https:' + href
        if _clean_html(title) and href.startswith('http'): out.append({'title': _clean_html(title)[:300], 'url': href[:1000], 'content': _clean_html(snip)[:1800], 'provider': 'DuckDuckGo'})
        if len(out) >= n: break
    return out


def _search_bing(q, n):
    page = _get('https://www.bing.com/search?' + urllib.parse.urlencode({'q': q[:500]})).decode('utf-8', 'replace'); out = []
    for href, title, snip in re.findall(r'<li class="b_algo"[\s\S]*?<h2><a href="(https?://[^" ]+)"[^>]*>(.*?)</a></h2>([\s\S]*?)(?=<li class="b_algo"|<ol id="b_results")', page, re.I):
        if _clean_html(title): out.append({'title': _clean_html(title)[:300], 'url': html.unescape(href)[:1000], 'content': _clean_html(snip)[:1800], 'provider': 'Bing'})
        if len(out) >= n: break
    return out


def _search_wiki(q, n):
    lang = 'vi' if re.search(r'[à-ỹ]', q.lower()) else 'en'
    d = json.loads(_get(f'https://{lang}.wikipedia.org/w/api.php?' + urllib.parse.urlencode({'action': 'query', 'list': 'search', 'srsearch': q[:300], 'format': 'json', 'srlimit': min(n, 5)}), 8, {'User-Agent': 'MotAPIStudio/3.0'}))
    return [{'title': x['title'], 'url': f'https://{lang}.wikipedia.org/wiki/' + urllib.parse.quote(x['title'].replace(' ', '_')), 'content': _clean_html(x.get('snippet', ''))[:1000], 'provider': 'Wikipedia'} for x in d.get('query', {}).get('search', [])]


def _search_news(q, n):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(_get('https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q[:300], 'hl': 'vi', 'gl': 'VN', 'ceid': 'VN:vi'}), 10, {'User-Agent': 'Mozilla/5.0 (compatible; MotAPIStudio/3.0)'}))
    return [{'title': i.findtext('title', '').strip()[:300], 'url': i.findtext('link', '').strip()[:1000], 'content': _clean_html(i.findtext('description', ''))[:1400], 'provider': 'Google News'} for i in root.findall('.//item')[:min(n, 6)] if i.findtext('link', '').startswith('http')]


def web_search(query, limit=6):
    try: limit = max(1, min(int(limit), 10))
    except (TypeError, ValueError): limit = 6
    query = str(query or '').strip()[:500]
    if not query: return {'available': False, 'provider': 'none', 'results': [], 'note': 'Nhập từ khóa tìm kiếm.'}
    results, providers, errors = [], [], []
    key = os.getenv('TAVILY_API_KEY', '').strip()
    if key:
        try:
            req = urllib.request.Request('https://api.tavily.com/search', data=json.dumps({'api_key': key, 'query': query, 'search_depth': 'basic', 'max_results': limit}).encode(), method='POST', headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=12) as r: data = json.loads(r.read().decode())
            results += [{'title': str(x.get('title', ''))[:300], 'url': str(x.get('url', ''))[:1000], 'content': str(x.get('content', ''))[:1800], 'provider': 'Tavily'} for x in data.get('results', [])[:limit]]
            providers.append('Tavily')
        except Exception as e: logging.warning('Tavily failed: %s', type(e).__name__); errors.append('Tavily')
    funcs = [('DuckDuckGo', _search_ddg), ('Bing', _search_bing), ('Wikipedia', _search_wiki), ('Google News', _search_news)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        fut = {pool.submit(fn, query, limit): name for name, fn in funcs}
        try:
            for f in as_completed(fut, timeout=14):
                try:
                    found = f.result()
                    if found: results += found; providers.append(fut[f])
                    else: errors.append(fut[f])
                except Exception as e: logging.info('%s unavailable: %s', fut[f], type(e).__name__); errors.append(fut[f])
        except Exception: errors.append('timeout')
    seen, uniq = set(), []
    for x in results:
        u, t = str(x.get('url', '')).strip(), str(x.get('title', '')).strip()
        if not u.startswith('http') or not t: continue
        k = urllib.parse.urlparse(u)._replace(query='', fragment='').geturl().rstrip('/').lower()
        if k in seen: continue
        seen.add(k); uniq.append(x)
        if len(uniq) >= limit: break
    prov = list(dict.fromkeys(providers))
    return {'available': bool(uniq), 'provider': ' + '.join(prov) or 'none', 'providers': prov, 'results': uniq, 'failed_providers': errors,
            'note': '' if uniq else 'Không lấy được kết quả từ các công cụ công khai. Mạng Render có thể bị chặn hoặc bị giới hạn truy cập.'}


# ---------------- Đọc liên kết trong tin nhắn (chống SSRF) ----------------
def _public_url(u):
    p = urllib.parse.urlparse(u)
    if p.scheme not in ('http', 'https') or not p.hostname: return False
    try:
        return all(ipaddress.ip_address(i[4][0]).is_global for i in socket.getaddrinfo(p.hostname, p.port or 443))
    except Exception: return False


def fetch_links(text, limit=2):
    out = []
    for u in list(dict.fromkeys(re.findall(r'https?://[^\s<>"\')\]]+', text)))[:limit]:
        if not _public_url(u): continue
        try:
            req = urllib.request.Request(u, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                if 'text' not in (r.headers.get('Content-Type') or ''): continue
                page = r.read(700000).decode('utf-8', 'replace')
            out.append(f'--- Nội dung liên kết: {u} ---\n' + _clean_html(page)[:12000])
        except Exception as e: logging.info('link fetch failed: %s', type(e).__name__)
    return out


# ---------------- Tệp đính kèm ----------------
TEXT_EXT = {'.txt', '.md', '.csv', '.json', '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.xml', '.yaml', '.yml', '.log', '.sql', '.toml', '.ini', '.sh', '.java', '.c', '.cpp', '.h', '.go', '.rs', '.ipynb', '.tsv'}


def extract_file(f):
    name = f.filename or 'file'; raw = f.read(); mime = (f.mimetype or mimetypes.guess_type(name)[0] or '').lower(); ext = os.path.splitext(name)[1].lower()
    if ext in TEXT_EXT: return {'kind': 'text', 'name': name, 'text': raw.decode('utf-8', errors='replace')[:60000]}
    if ext == '.pdf' or mime == 'application/pdf':
        try:
            from pypdf import PdfReader
            return {'kind': 'text', 'name': name, 'text': '\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(raw)).pages)[:60000]}
        except Exception: return {'kind': 'text', 'name': name, 'text': '[Không trích xuất được PDF.]'}
    if ext == '.docx':
        try:
            from docx import Document
            d = Document(BytesIO(raw)); t = [p.text for p in d.paragraphs]
            for tb in d.tables: t += [' | '.join(c.text for c in r.cells) for r in tb.rows]
            return {'kind': 'text', 'name': name, 'text': '\n'.join(t)[:60000]}
        except Exception: return {'kind': 'text', 'name': name, 'text': '[Không trích xuất được DOCX.]'}
    if ext == '.xlsx':
        try:
            from openpyxl import load_workbook
            wb = load_workbook(BytesIO(raw), read_only=True, data_only=True); t = []
            for ws in wb.worksheets[:5]:
                t.append(f'# Sheet {ws.title}')
                for i, r in enumerate(ws.iter_rows(values_only=True)):
                    if i > 400: break
                    t.append(','.join('' if c is None else str(c) for c in r))
            return {'kind': 'text', 'name': name, 'text': '\n'.join(t)[:60000]}
        except Exception: return {'kind': 'text', 'name': name, 'text': '[Không trích xuất được XLSX.]'}
    if mime.startswith('image/') or ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
        mime = mime if mime.startswith('image/') else (mimetypes.guess_type(name)[0] or 'image/jpeg')
        return {'kind': 'image', 'name': name, 'url': f'data:{mime};base64,{base64.b64encode(raw).decode()}'}
    return {'kind': 'text', 'name': name, 'text': f'[Tệp {name}, {len(raw)} byte; định dạng chưa trích xuất tự động.]'}


class _F:
    def __init__(s, p): s.filename = os.path.basename(p); s._p = p; s.mimetype = mimetypes.guess_type(p)[0] or ''
    def read(s):
        with open(s._p, 'rb') as f: return f.read()


def ws_context(sid, message, sel):
    """Nội dung các tệp workspace được chọn hoặc được nhắc tên trong tin nhắn + danh mục tệp."""
    items = ws_list(sid); parts = []; left = 60000; low = message.lower()
    for rel, _ in items:
        if (rel in sel or os.path.basename(rel).lower() in low) and len(parts) < 8 and left > 0:
            p = ws_path(sid, rel)
            x = extract_file(_F(p)) if p else None
            if x and x['kind'] == 'text': t = x['text'][:left]; left -= len(t); parts.append(f'--- Tệp workspace: {rel} ---\n{t}')
    return parts, '\n'.join(f'- {r} ({s} B)' for r, s in items[:200])


# ---------------- Routes ----------------
@app.get('/')
def home(): return send_from_directory(ROOT, 'index.html')


@app.get('/api/health')
def health():
    tav = bool(os.getenv('TAVILY_API_KEY', '').strip())
    return jsonify(ok=True, configured=bool(os.getenv('MOTAPIS_API_KEY', '').strip()), search_configured=True, needs_password=bool(os.getenv('APP_PASSWORD', '').strip()),
                   search_provider=('Tavily + ' if tav else '') + 'DuckDuckGo + Bing + Wikipedia + Google News', provider='MộtAPI', base_url=BASE())


@app.post('/api/diagnostics')
def diagnostics():
    d = request.get_json(silent=True) or {}; model = str(d.get('model') or 'gpt-6-astra').strip()[:120]
    try:
        r = client().chat.completions.create(model=model, messages=[{'role': 'user', 'content': 'Reply with exactly: OK'}], max_tokens=8, stream=False)
        return jsonify(ok=True, model=model, reply=((r.choices[0].message.content or '').strip() if r.choices else '')[:80], provider='MộtAPI')
    except Exception as e:
        logging.warning('diagnostics failed (%s)', type(e).__name__)
        return jsonify(ok=False, model=model, error=safe_error(e), error_type=type(e).__name__, status=getattr(e, 'status_code', None)), 502


@app.get('/api/models')
def models():
    key = os.getenv('MOTAPIS_API_KEY', '').strip(); fallback = jsonify(models=[{'id': m, 'available': None} for m in MODELS], source='configured-list')
    if not key: return fallback
    try:
        d = json.loads(_get(BASE() + '/models', 12, {'Authorization': f'Bearer {key}'}).decode())
        actual = {str(x.get('id')) for x in d.get('data', []) if isinstance(x, dict) and x.get('id')}
        allm = MODELS + [x for x in sorted(actual) if x not in MODELS]
        return jsonify(models=[{'id': m, 'available': (m in actual) if actual else None} for m in allm], source='provider-model-list' if actual else 'configured-list')
    except Exception as e:
        logging.warning('Model list unavailable: %s', type(e).__name__); return fallback


@app.post('/api/search')
def search_route():
    d = request.get_json(silent=True) or {}; q = str(d.get('query', '')).strip()
    if not q: return jsonify(error='Nhập từ khóa cần tìm.'), 400
    r = web_search(q, d.get('max_results', 5))
    return (jsonify(r) if r['available'] else (jsonify(error=r.get('note') or 'Tìm kiếm tạm thời không khả dụng.'), 503))


@app.post('/api/chat')
def chat():
    message = request.form.get('message', '').strip(); model = request.form.get('model', 'gpt-6-astra').strip(); mode = request.form.get('mode', 'chat')
    use_search = request.form.get('web_search', 'false').lower() == 'true'; custom = request.form.get('custom', '').strip()[:2000]
    if not model or len(model) > 120: return jsonify(error='Tên model không hợp lệ.'), 400
    try: history = json.loads(request.form.get('history', '[]')); history = history if isinstance(history, list) else []
    except Exception: history = []
    try: files = [extract_file(f) for f in request.files.getlist('files') if f.filename]
    except Exception: return jsonify(error='Không đọc được một tệp đính kèm.'), 400
    user = [{'type': 'text', 'text': message or 'Hãy xem xét các tệp/ảnh đính kèm và hỗ trợ tôi.'}]
    for f in files:
        if f['kind'] == 'image': user.append({'type': 'image_url', 'image_url': {'url': f['url']}})
        else: user[0]['text'] += f"\n\n--- Tệp: {f['name']} ---\n{f['text']}"
    links = fetch_links(message) if message else []
    if links: user[0]['text'] += '\n\n' + '\n\n'.join(links)
    try: sel = set(json.loads(request.form.get('ws', '[]')))
    except Exception: sel = set()
    ws_parts, manifest = ws_context(request.headers.get('X-Session', ''), message, sel)
    if ws_parts: user[0]['text'] += '\n\n' + '\n\n'.join(ws_parts)
    search = web_search(message, 6) if use_search and message else None
    if search and search.get('available'):
        refs = ['KẾT QUẢ TÌM KIẾM WEB (' + search['provider'] + '). Hãy kiểm chứng, dẫn nguồn bằng [số], không bịa thêm nguồn:']
        refs += [f"[{i}] {x['title']}\nURL: {x['url']}\nNội dung: {x['content']}" for i, x in enumerate(search['results'], 1)]
        user[0]['text'] += '\n\n' + '\n\n'.join(refs)
    system = os.getenv('AI_SYSTEM_PROMPT', 'Bạn là trợ lý AI hữu ích, chính xác. Trả lời tiếng Việt khi phù hợp. Với code: đưa kế hoạch ngắn, mã rõ ràng, cách chạy và kiểm thử; không khẳng định đã chạy test nếu chưa chạy. Không tiết lộ chuỗi suy nghĩ nội bộ; hãy cung cấp giải thích ngắn, kết luận, giả định và bước kiểm chứng. Nếu có nguồn web, dẫn link và tiêu đề.')
    if mode == 'coding': system += '\nChế độ CODING: làm việc như kỹ sư phần mềm; xem xét lỗi, bảo mật, patch, test, hướng dẫn deploy; chia việc thành bước kiểm chứng được.'
    if mode == 'research': system += '\nChế độ RESEARCH: ưu tiên nguồn mới, đối chiếu dữ kiện, phân biệt điều đã xác minh với suy luận; kèm URL nguồn.'
    system += FILE_PROTOCOL
    if manifest: system += '\n\nWORKSPACE của người dùng (có thể gồm tệp đã giải nén):\n' + manifest + '\nBạn chỉ thấy nội dung các tệp đã được đính kèm ở trên; cần tệp khác thì bảo người dùng tick chọn hoặc nhắc tên tệp.'
    if custom: system += '\n\nHƯỚNG DẪN TÙY CHỈNH CỦA NGƯỜI DÙNG:\n' + custom
    msgs = [{'role': 'system', 'content': system}]
    for h in history[-20:]:
        if isinstance(h, dict) and h.get('role') in ('user', 'assistant') and isinstance(h.get('content'), str): msgs.append({'role': h['role'], 'content': h['content'][:20000]})
    msgs.append({'role': 'user', 'content': user})
    ev = lambda d: 'data: ' + json.dumps(d, ensure_ascii=False) + '\n\n'

    @stream_with_context
    def generate():
        try:
            if ws_parts: yield ev({'status': f'Đã đọc {len(ws_parts)} tệp từ workspace.'})
            if links: yield ev({'status': f'Đã đọc {len(links)} liên kết trong tin nhắn.'})
            if use_search: yield ev({'status': f"Đã thêm {len(search['results'])} nguồn web ({search['provider']})." if search and search.get('available') else 'Tìm kiếm web chưa sẵn sàng; trả lời có thể chỉ dựa trên kiến thức của model.'})
            yield ev({'status': {'research': 'Đang đối chiếu nguồn và tổng hợp.', 'coding': 'Đang lập kế hoạch kỹ thuật và viết lời giải.'}.get(mode, 'Đang phân tích yêu cầu.')})
            api = client()
            params = {'model': model, 'messages': msgs, 'stream': True, 'temperature': float(os.getenv('AI_TEMPERATURE', '0.7')), 'max_tokens': int(os.getenv('AI_MAX_TOKENS', '4096'))}
            try: stream = api.chat.completions.create(**params)
            except Exception as first:
                d = str(first).lower(); changed = False
                if 'temperature' in d and any(w in d for w in ('unsupported', 'not support', 'does not support', 'unknown parameter')): params.pop('temperature', None); changed = True
                if 'max_tokens' in d and any(w in d for w in ('unsupported', 'not support', 'unknown parameter', 'use max_completion_tokens')): params['max_completion_tokens'] = params.pop('max_tokens', 4096); changed = True
                if not changed: raise
                stream = api.chat.completions.create(**params)
            for chunk in stream:
                if not chunk.choices: continue
                dl = chunk.choices[0].delta
                r = getattr(dl, 'reasoning_content', None) or getattr(dl, 'reasoning', None)
                if isinstance(r, str) and r: yield ev({'think': r})
                c = getattr(dl, 'content', None)
                if isinstance(c, str) and c: yield ev({'token': c})
                elif isinstance(c, list):
                    for b in c:
                        t = getattr(b, 'text', None)
                        if t: yield ev({'token': t})
            yield ev({'done': True, 'model': model, 'searched': bool(search and search.get('available'))})
        except Exception as e:
            logging.warning('chat failed (%s)', type(e).__name__); yield ev({'error': safe_error(e)})

    return Response(generate(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})


@app.errorhandler(413)
def too_large(_): return jsonify(error=f"Tệp vượt giới hạn {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB. Chỉnh MAX_UPLOAD_MB trên Render nếu cần."), 413


if __name__ == '__main__': app.run(host='0.0.0.0', port=int(os.getenv('PORT', '10000')))
