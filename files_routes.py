"""Workspace theo phiên: tải lên, tự giải nén (zip/tar/tgz/gz/bz2/xz/7z/rar), xem, tải, xóa, lưu tệp do AI tạo."""
import os, re, io, stat, shutil, tarfile, zipfile, gzip, bz2, lzma, tempfile
from flask import Blueprint, request, jsonify, send_file, abort

fb = Blueprint('files', __name__)
WS = os.path.abspath(os.getenv('WORKSPACE_DIR', os.path.join(tempfile.gettempdir(), 'motapi_ws')))
MAX_TOTAL = int(os.getenv('WORKSPACE_MAX_MB', '300')) * 2**20
MAX_EXTRACT = int(os.getenv('MAX_EXTRACT_MB', '200')) * 2**20
MAX_FILES = int(os.getenv('MAX_EXTRACT_FILES', '2000'))
TEXT = {'.txt', '.md', '.csv', '.tsv', '.json', '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.xml', '.yaml', '.yml', '.log', '.sql', '.toml', '.ini', '.sh', '.java', '.c', '.cpp', '.h', '.go', '.rs', '.svg', '.rtf', '.env', '.cfg'}
ARCH = ('.zip', '.tar', '.tgz', '.tar.gz', '.tbz2', '.tar.bz2', '.txz', '.tar.xz', '.gz', '.bz2', '.xz', '.7z', '.rar')


def _sid(raw):
    return raw if re.fullmatch(r'[A-Za-z0-9_-]{8,64}', raw or '') else None


def ws_root(sid, create=True):
    sid = _sid(sid)
    if not sid: return None
    d = os.path.join(WS, sid)
    if create: os.makedirs(d, exist_ok=True)
    return d


def _inside(root, rel):
    rel = (rel or '').replace('\\', '/').lstrip('/')
    p = os.path.abspath(os.path.join(root, rel))
    return p if (p == root or p.startswith(root + os.sep)) else None


def ws_list(sid):
    root = ws_root(sid, False)
    if not root or not os.path.isdir(root): return []
    out = []
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            out.append((os.path.relpath(p, root).replace(os.sep, '/'), os.path.getsize(p)))
    return sorted(out)


def ws_path(sid, rel):
    root = ws_root(sid, False)
    p = _inside(root, rel) if root else None
    return p if p and os.path.isfile(p) else None


def _root_or_400():
    r = ws_root(request.headers.get('X-Session', ''))
    if not r: abort(400)
    return r


def _usage(root):
    return sum(s for _, s in ws_list(os.path.basename(root)))


def _clean_name(n):
    n = os.path.basename((n or 'file').replace('\\', '/')) or 'file'
    return re.sub(r'[^\w.\- ()]+', '_', n)[:120]


def _unique(p):
    if not os.path.exists(p): return p
    b, e = os.path.splitext(p); i = 2
    while os.path.exists(f'{b}-{i}{e}'): i += 1
    return f'{b}-{i}{e}'


class Budget:
    def __init__(s): s.n = 0; s.b = 0
    def take(s, size=0):
        s.n += 1; s.b += size
        if s.n > MAX_FILES or s.b > MAX_EXTRACT: raise ValueError('Tệp nén vượt giới hạn số tệp hoặc dung lượng giải nén.')


def _copy(src, dest, bud):
    os.makedirs(os.path.dirname(dest), exist_ok=True); bud.take()
    with open(dest, 'wb') as o:
        while True:
            c = src.read(1 << 20)
            if not c: break
            bud.b += len(c)
            if bud.b > MAX_EXTRACT: raise ValueError('Tệp nén vượt giới hạn dung lượng giải nén.')
            o.write(c)


def _stem(name):
    n = name
    for e in sorted(ARCH, key=len, reverse=True):
        if n.lower().endswith(e): return n[:-len(e)] or 'archive'
    return n


def is_archive(name): return name.lower().endswith(ARCH)


def extract(path, dest, bud):
    """Giải nén an toàn vào dest (chống zip-slip, symlink, zip-bomb). Trả về danh sách tệp đã ghi."""
    low = path.lower(); out = []
    if zipfile.is_zipfile(path) and low.endswith('.zip'):
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if i.is_dir() or i.flag_bits & 1 or stat.S_ISLNK(i.external_attr >> 16): continue
                p = _inside(dest, i.filename)
                if not p or p == dest: continue
                with z.open(i) as s: _copy(s, p, bud)
                out.append(p)
    elif low.endswith(('.tar', '.tgz', '.tar.gz', '.tbz2', '.tar.bz2', '.txz', '.tar.xz')):
        with tarfile.open(path) as t:
            for m in t:
                if not m.isfile(): continue
                p = _inside(dest, m.name)
                if not p or p == dest: continue
                _copy(t.extractfile(m), p, bud); out.append(p)
    elif low.endswith(('.gz', '.bz2', '.xz')):
        op = {'.gz': gzip.open, '.bz2': bz2.open, '.xz': lzma.open}[os.path.splitext(low)[1]]
        p = os.path.join(dest, _clean_name(_stem(os.path.basename(path))))
        with op(path, 'rb') as s: _copy(s, p, bud)
        out.append(p)
    elif low.endswith('.7z'):
        try: import py7zr
        except ImportError: raise ValueError('Chưa cài py7zr nên chưa giải nén được .7z.')
        tmp = tempfile.mkdtemp(dir=WS)
        try:
            with py7zr.SevenZipFile(path) as z: z.extractall(tmp)
            out += _adopt(tmp, dest, bud)
        finally: shutil.rmtree(tmp, ignore_errors=True)
    elif low.endswith('.rar'):
        try: import rarfile
        except ImportError: raise ValueError('Máy chủ chưa hỗ trợ .rar (cần rarfile + unrar).')
        tmp = tempfile.mkdtemp(dir=WS)
        try:
            with rarfile.RarFile(path) as z: z.extractall(tmp)
            out += _adopt(tmp, dest, bud)
        finally: shutil.rmtree(tmp, ignore_errors=True)
    else: raise ValueError('Định dạng nén không được hỗ trợ.')
    return out


def _adopt(tmp, dest, bud):
    out = []
    for dp, _, fs in os.walk(tmp):
        for f in fs:
            s = os.path.join(dp, f)
            if os.path.islink(s): continue
            with open(s, 'rb') as fh: _copy(fh, os.path.join(dest, os.path.relpath(s, tmp)), bud)
            out.append(os.path.join(dest, os.path.relpath(s, tmp)))
    return out


@fb.post('/api/files/upload')
def upload():
    root = _root_or_400(); notes = []; added = 0
    for f in request.files.getlist('files'):
        name = _clean_name(f.filename); dest = _unique(os.path.join(root, name)); f.save(dest)
        if _usage(root) > MAX_TOTAL:
            os.remove(dest); notes.append(f'{name}: vượt giới hạn workspace {MAX_TOTAL >> 20} MB.'); continue
        if not is_archive(name): added += 1; continue
        folder = _unique(os.path.join(root, _stem(name))); bud = Budget(); todo = [(dest, folder, 0)]; ok = 0
        try:
            while todo:
                src, dst, depth = todo.pop(); os.makedirs(dst, exist_ok=True)
                try: got = extract(src, dst, bud)
                except Exception as e:
                    if depth == 0 or 'giới hạn' in str(e): raise
                    shutil.rmtree(dst, ignore_errors=True); continue  # tệp nén lồng nhau hỏng: giữ nguyên
                for p in got:
                    if depth < 1 and is_archive(p):
                        todo.append((p, os.path.join(os.path.dirname(p), _stem(os.path.basename(p))), depth + 1))
                if src != dest: os.remove(src)
            os.remove(dest); ok = sum(len(fs) for _, _, fs in os.walk(folder)); added += ok
            notes.append(f'{name}: đã giải nén {ok} tệp.')
        except Exception as e:
            shutil.rmtree(folder, ignore_errors=True)
            notes.append(f'{name}: {e if isinstance(e, ValueError) else "không giải nén được (tệp hỏng hoặc có mật khẩu)."} Tệp gốc được giữ lại.')
        if _usage(root) > MAX_TOTAL: notes.append('Workspace gần đầy; hãy xóa bớt tệp.')
    return jsonify(ok=True, added=added, notes=notes)


@fb.get('/api/files/list')
def listing():
    root = _root_or_400(); items = ws_list(os.path.basename(root))
    return jsonify(files=[{'path': p, 'size': s} for p, s in items], used=sum(s for _, s in items), limit=MAX_TOTAL)


@fb.get('/api/files/read')
def read():
    root = _root_or_400(); p = _inside(root, request.args.get('path', ''))
    if not p or not os.path.isfile(p): abort(404)
    ext = os.path.splitext(p)[1].lower()
    if ext not in TEXT: return jsonify(error='Tệp nhị phân: hãy tải xuống để xem.', binary=True), 415
    with open(p, 'rb') as f: raw = f.read(300000)
    return jsonify(path=request.args.get('path'), text=raw.decode('utf-8', 'replace'), truncated=os.path.getsize(p) > 300000)


@fb.get('/api/files/download')
def download():
    root = _root_or_400(); p = _inside(root, request.args.get('path', ''))
    if not p or not os.path.isfile(p): abort(404)
    return send_file(p, as_attachment=True, download_name=os.path.basename(p))


@fb.post('/api/files/save')
def save():
    root = _root_or_400(); d = request.get_json(silent=True) or {}
    rel = '/'.join(_clean_name(x) for x in str(d.get('path', 'file.txt')).replace('\\', '/').split('/') if x not in ('', '.', '..')) or 'file.txt'
    p = _inside(root, rel); data = str(d.get('content', '')).encode('utf-8')
    if not p or _usage(root) + len(data) > MAX_TOTAL: return jsonify(error='Không lưu được: workspace đầy hoặc đường dẫn không hợp lệ.'), 400
    p = _unique(p); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f: f.write(data)
    return jsonify(ok=True, path=os.path.relpath(p, root).replace(os.sep, '/'))


@fb.delete('/api/files')
def delete():
    root = _root_or_400()
    if request.args.get('all') == '1':
        shutil.rmtree(root, ignore_errors=True); return jsonify(ok=True)
    p = _inside(root, request.args.get('path', ''))
    if not p or p == root or not os.path.exists(p): abort(404)
    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    return jsonify(ok=True)


@fb.get('/api/files/zip')
def zip_all():
    root = _root_or_400(); buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel, _ in ws_list(os.path.basename(root)): z.write(os.path.join(root, rel), rel)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='workspace.zip', mimetype='application/zip')
