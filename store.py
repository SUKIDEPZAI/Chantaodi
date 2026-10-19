"""Lưu trữ bền vững (SQLite) + API v2: hội thoại, dự án, artifact có phiên bản.
Mọi truy vấn đều tham số hóa và ràng buộc `owner` (= X-Session của trình duyệt)."""
import os, re, time, uuid, sqlite3, tempfile, threading, collections
from flask import Blueprint, request, jsonify, abort
from files_routes import _sid, ws_path

bp = Blueprint('v2', __name__)
_ID = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
_hits = collections.defaultdict(collections.deque); _lk = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, description TEXT DEFAULT '', instructions TEXT DEFAULT '', model TEXT DEFAULT '', created REAL, updated REAL);
CREATE INDEX IF NOT EXISTS ix_proj_owner ON projects(owner, updated DESC);
CREATE TABLE IF NOT EXISTS project_files(project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, path TEXT NOT NULL, PRIMARY KEY(project_id, path));
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT REFERENCES projects(id) ON DELETE SET NULL, title TEXT DEFAULT '', model TEXT DEFAULT '', mode TEXT DEFAULT 'chat', pinned INTEGER DEFAULT 0, archived INTEGER DEFAULT 0, created REAL, updated REAL);
CREATE INDEX IF NOT EXISTS ix_conv_owner ON conversations(owner, archived, pinned DESC, updated DESC);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, client_id TEXT, feedback INTEGER DEFAULT 0, created REAL);
CREATE INDEX IF NOT EXISTS ix_msg_conv ON messages(conv_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_msg_client ON messages(conv_id, client_id) WHERE client_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, owner TEXT NOT NULL, conv_id TEXT, title TEXT DEFAULT '', lang TEXT DEFAULT '', created REAL);
CREATE TABLE IF NOT EXISTS artifact_versions(id INTEGER PRIMARY KEY AUTOINCREMENT, artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE, content TEXT NOT NULL, note TEXT DEFAULT '', created REAL);
CREATE INDEX IF NOT EXISTS ix_ver_art ON artifact_versions(artifact_id, id);
"""


def _db():
    c = sqlite3.connect(os.getenv('DATABASE_PATH', os.path.join(tempfile.gettempdir(), 'motapi.db')), timeout=10)
    c.row_factory = sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c


def q(sql, a=(), one=False, write=False):
    c = _db()
    try:
        cur = c.execute(sql, a)
        if write: c.commit(); return cur.rowcount
        rows = [dict(r) for r in cur.fetchall()]
        return (rows[0] if rows else None) if one else rows
    finally: c.close()


def init():
    c = _db()
    try: c.execute('PRAGMA journal_mode=WAL'); c.executescript(SCHEMA); c.commit()
    finally: c.close()


init()
_now = time.time


# ---------- helper dùng bởi /api/chat ----------
def owner_of(raw): return _sid(raw)
def valid_id(x): return bool(x and _ID.match(x))


def allow(owner, limit=30, per=60):
    """Giới hạn tốc độ trong bộ nhớ: tối đa `limit` yêu cầu / `per` giây cho mỗi phiên."""
    with _lk:
        d = _hits[owner or 'anon']; t = _now()
        while d and t - d[0] > per: d.popleft()
        if len(d) >= limit: return False
        d.append(t); return True


def project_of(owner, pid):
    return q('SELECT * FROM projects WHERE id=? AND owner=?', (pid, owner), one=True) if owner and valid_id(pid) else None


def project_paths(owner, pid):
    if not project_of(owner, pid): return []
    return [r['path'] for r in q('SELECT path FROM project_files WHERE project_id=?', (pid,)) if ws_path(owner, r['path'])]


def ensure_conv(owner, cid, title, model, mode, pid):
    """Tạo (nếu chưa có) rồi cập nhật hội thoại. Trả False nếu id thuộc người khác."""
    t = _now(); pid = pid if project_of(owner, pid) else None
    q('INSERT OR IGNORE INTO conversations(id,owner,project_id,title,model,mode,created,updated) VALUES(?,?,?,?,?,?,?,?)', (cid, owner, pid, title[:120], model[:120], mode[:20], t, t), write=True)
    return q("UPDATE conversations SET updated=?, model=?, mode=?, project_id=?, title=CASE WHEN title='' THEN ? ELSE title END WHERE id=? AND owner=?", (t, model[:120], mode[:20], pid, title[:120], cid, owner), write=True) > 0


def add_msg(cid, role, content, client_id=None):
    """Lưu tin nhắn; trả False nếu client_id đã tồn tại (retry không tạo bản trùng)."""
    try:
        q('INSERT INTO messages(conv_id,role,content,client_id,created) VALUES(?,?,?,?,?)', (cid, role, content[:200000], client_id or None, _now()), write=True)
        q('UPDATE conversations SET updated=? WHERE id=?', (_now(), cid), write=True); return True
    except sqlite3.IntegrityError: return False


def history_of(owner, cid, limit=20):
    rows = q('SELECT role,content FROM messages WHERE conv_id=? AND conv_id IN (SELECT id FROM conversations WHERE owner=?) ORDER BY id DESC LIMIT ?', (cid, owner, limit))
    return [{'role': r['role'], 'content': re.sub(r'<think>[\s\S]*?(</think>|$)', '', r['content']).strip()} for r in reversed(rows)]


def drop_last_turn(owner, cid):
    rows = q('SELECT id,role FROM messages WHERE conv_id=? AND conv_id IN (SELECT id FROM conversations WHERE owner=?) ORDER BY id DESC LIMIT 2', (cid, owner)); ids = []
    if rows and rows[0]['role'] == 'assistant': ids.append(rows.pop(0)['id'])
    if rows and rows[0]['role'] == 'user': ids.append(rows[0]['id'])
    for i in ids: q('DELETE FROM messages WHERE id=?', (i,), write=True)


# ---------- routes ----------
def _o():
    o = _sid(request.headers.get('X-Session', ''))
    if not o: abort(400)
    return o


def _b(): return request.get_json(silent=True) or {}
def _own(table, i):
    r = q(f'SELECT * FROM {table} WHERE id=? AND owner=?', (i, _o()), one=True) if valid_id(i) else None
    if not r: abort(404)
    return r
def _s(v, n): return str(v or '').strip()[:n]


@bp.get('/api/v2/conversations')
def conv_list():
    o = _o(); s = _s(request.args.get('q'), 100); p = request.args.get('project', '')
    sql = 'SELECT id,title,pinned,archived,project_id,model,updated FROM conversations WHERE owner=? AND archived=?'; a = [o, 1 if request.args.get('archived') == '1' else 0]
    if valid_id(p): sql += ' AND project_id=?'; a.append(p)
    if s:
        like = '%' + s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        sql += " AND (title LIKE ? ESCAPE '\\' OR id IN (SELECT conv_id FROM messages WHERE content LIKE ? ESCAPE '\\'))"; a += [like, like]
    try: lim = max(1, min(int(request.args.get('limit', 50)), 100)); off = max(0, int(request.args.get('offset', 0)))
    except ValueError: lim, off = 50, 0
    return jsonify(items=q(sql + ' ORDER BY pinned DESC, updated DESC LIMIT ? OFFSET ?', a + [lim, off]))


@bp.get('/api/v2/conversations/<cid>')
def conv_get(cid):
    c = _own('conversations', cid)
    c['messages'] = q('SELECT id,role,content,feedback,created FROM messages WHERE conv_id=? ORDER BY id', (cid,))
    return jsonify(c)


@bp.patch('/api/v2/conversations/<cid>')
def conv_patch(cid):
    c = _own('conversations', cid); d = _b(); sets, a = [], []
    if 'title' in d: sets.append('title=?'); a.append(_s(d['title'], 120))
    if 'pinned' in d: sets.append('pinned=?'); a.append(1 if d['pinned'] else 0)
    if 'archived' in d: sets.append('archived=?'); a.append(1 if d['archived'] else 0)
    if 'model' in d: sets.append('model=?'); a.append(_s(d['model'], 120))
    if 'project_id' in d:
        pid = d['project_id'] or None
        if pid and not project_of(c['owner'], pid): return jsonify(error='Dự án không tồn tại.'), 404
        sets.append('project_id=?'); a.append(pid)
    if sets: q(f"UPDATE conversations SET {','.join(sets)} WHERE id=? AND owner=?", a + [cid, c['owner']], write=True)
    return jsonify(ok=True)


@bp.delete('/api/v2/conversations/<cid>')
def conv_del(cid):
    c = _own('conversations', cid); q('DELETE FROM conversations WHERE id=? AND owner=?', (cid, c['owner']), write=True); return jsonify(ok=True)


@bp.post('/api/v2/messages/<int:mid>/feedback')
def feedback(mid):
    v = _b().get('value')
    if v not in (-1, 0, 1): return jsonify(error='Giá trị không hợp lệ.'), 400
    n = q('UPDATE messages SET feedback=? WHERE id=? AND conv_id IN (SELECT id FROM conversations WHERE owner=?)', (v, mid, _o()), write=True)
    return (jsonify(ok=True) if n else abort(404))


@bp.get('/api/v2/projects')
def proj_list():
    return jsonify(items=q('SELECT id,name,description,instructions,model,updated FROM projects WHERE owner=? ORDER BY updated DESC LIMIT 100', (_o(),)))


@bp.post('/api/v2/projects')
def proj_new():
    o = _o(); d = _b(); name = _s(d.get('name'), 80)
    if not name: return jsonify(error='Nhập tên dự án.'), 400
    if q('SELECT COUNT(*) n FROM projects WHERE owner=?', (o,), one=True)['n'] >= 100: return jsonify(error='Đã đạt giới hạn 100 dự án.'), 400
    pid = 'p-' + uuid.uuid4().hex[:20]; t = _now()
    q('INSERT INTO projects(id,owner,name,description,instructions,model,created,updated) VALUES(?,?,?,?,?,?,?,?)', (pid, o, name, _s(d.get('description'), 300), _s(d.get('instructions'), 8000), _s(d.get('model'), 120), t, t), write=True)
    return jsonify(id=pid, name=name), 201


@bp.get('/api/v2/projects/<pid>')
def proj_get(pid):
    p = _own('projects', pid); p['paths'] = [r['path'] for r in q('SELECT path FROM project_files WHERE project_id=?', (pid,))]; return jsonify(p)


@bp.patch('/api/v2/projects/<pid>')
def proj_patch(pid):
    p = _own('projects', pid); d = _b(); lim = {'name': 80, 'description': 300, 'instructions': 8000, 'model': 120}; sets, a = [], []
    for k, n in lim.items():
        if k in d:
            v = _s(d[k], n)
            if k == 'name' and not v: return jsonify(error='Tên dự án không được trống.'), 400
            sets.append(f'{k}=?'); a.append(v)
    if sets: q(f"UPDATE projects SET {','.join(sets)}, updated=? WHERE id=? AND owner=?", a + [_now(), pid, p['owner']], write=True)
    return jsonify(ok=True)


@bp.delete('/api/v2/projects/<pid>')
def proj_del(pid):
    p = _own('projects', pid); q('DELETE FROM projects WHERE id=? AND owner=?', (pid, p['owner']), write=True); return jsonify(ok=True)


@bp.put('/api/v2/projects/<pid>/files')
def proj_files(pid):
    p = _own('projects', pid); raw = _b().get('paths'); raw = raw if isinstance(raw, list) else []
    paths = [x for x in dict.fromkeys(str(x)[:300] for x in raw[:50]) if ws_path(p['owner'], x)]  # chỉ nhận tệp có thật trong workspace của chính chủ
    q('DELETE FROM project_files WHERE project_id=?', (pid,), write=True)
    for x in paths: q('INSERT INTO project_files(project_id,path) VALUES(?,?)', (pid, x), write=True)
    return jsonify(paths=paths)


@bp.post('/api/v2/artifacts')
def art_new():
    o = _o(); d = _b(); content = str(d.get('content', ''))
    if not content or len(content) > 400000: return jsonify(error='Nội dung trống hoặc quá lớn.'), 400
    cid = d.get('conv_id') if valid_id(d.get('conv_id')) and q('SELECT 1 x FROM conversations WHERE id=? AND owner=?', (d.get('conv_id'), o), one=True) else None
    aid = 'a-' + uuid.uuid4().hex[:20]; t = _now()
    q('INSERT INTO artifacts(id,owner,conv_id,title,lang,created) VALUES(?,?,?,?,?,?)', (aid, o, cid, _s(d.get('title'), 120), _s(d.get('lang'), 20).lower(), t), write=True)
    q('INSERT INTO artifact_versions(artifact_id,content,note,created) VALUES(?,?,?,?)', (aid, content, 'v1', t), write=True)
    return jsonify(id=aid), 201


@bp.get('/api/v2/artifacts')
def art_list():
    return jsonify(items=q('SELECT id,title,lang,conv_id,created FROM artifacts WHERE owner=? ORDER BY created DESC LIMIT 100', (_o(),)))


@bp.get('/api/v2/artifacts/<aid>')
def art_get(aid):
    a = _own('artifacts', aid)
    a['versions'] = q('SELECT id,note,created,LENGTH(content) size FROM artifact_versions WHERE artifact_id=? ORDER BY id', (aid,))
    a['content'] = q('SELECT content FROM artifact_versions WHERE artifact_id=? ORDER BY id DESC LIMIT 1', (aid,), one=True)['content']
    return jsonify(a)


@bp.post('/api/v2/artifacts/<aid>/versions')
def art_ver(aid):
    _own('artifacts', aid); d = _b(); content = str(d.get('content', ''))
    if not content or len(content) > 400000: return jsonify(error='Nội dung trống hoặc quá lớn.'), 400
    last = q('SELECT content FROM artifact_versions WHERE artifact_id=? ORDER BY id DESC LIMIT 1', (aid,), one=True)
    if last and last['content'] == content: return jsonify(ok=True, unchanged=True)
    q('INSERT INTO artifact_versions(artifact_id,content,note,created) VALUES(?,?,?,?)', (aid, content, _s(d.get('note'), 120), _now()), write=True)
    return jsonify(ok=True), 201


@bp.get('/api/v2/artifacts/<aid>/versions/<int:vid>')
def art_ver_get(aid, vid):
    _own('artifacts', aid); v = q('SELECT id,content,note,created FROM artifact_versions WHERE id=? AND artifact_id=?', (vid, aid), one=True)
    return jsonify(v) if v else abort(404)


@bp.post('/api/v2/import')
def import_local():
    """Nhập một lần các hội thoại cũ từ localStorage (bỏ qua id đã tồn tại)."""
    o = _o(); chats = _b().get('chats'); n = 0
    for c in (chats if isinstance(chats, list) else [])[:100]:
        if not isinstance(c, dict) or not valid_id(c.get('id')): continue
        t = float(c.get('updated') or _now() * 1000) / 1000 if isinstance(c.get('updated'), (int, float)) else _now()
        if q('INSERT OR IGNORE INTO conversations(id,owner,title,model,mode,created,updated) VALUES(?,?,?,?,?,?,?)', (c['id'], o, _s(c.get('title'), 120), _s(c.get('model'), 120), _s(c.get('mode') or 'chat', 20), t, t), write=True):
            for m in (c.get('history') or [])[:400]:
                if isinstance(m, dict) and m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str): add_msg(c['id'], m['role'], m['content'])
            n += 1
    return jsonify(ok=True, imported=n)
