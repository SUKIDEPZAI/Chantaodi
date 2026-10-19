"""Small SQLite persistence layer. All records are scoped to a browser-session owner."""
from __future__ import annotations
import os, re, sqlite3, time, uuid
from pathlib import Path


def db_path() -> str:
    return os.getenv("DATABASE_PATH", str(Path(__file__).resolve().parent / "data" / "chantaodi.sqlite3"))


def connect():
    path = Path(db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    return c


def init_db():
    c = connect()
    legacy_messages = False
    try:
        c.execute("PRAGMA journal_mode=WAL")
        # Move the prior MotAPI Studio message table aside if it uses the old `conv_id` column.
        old_tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "messages" in old_tables:
            message_cols={r[1] for r in c.execute("PRAGMA table_info(messages)").fetchall()}
            if "conversation_id" not in message_cols and "conv_id" in message_cols:
                if "messages_legacy_v1" in old_tables:
                    c.execute("DROP TABLE messages_legacy_v1")
                c.execute("ALTER TABLE messages RENAME TO messages_legacy_v1")
                legacy_messages=True
        c.executescript("""
        CREATE TABLE IF NOT EXISTS conversations(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL DEFAULT 'Cuộc trò chuyện mới',
          model TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'chat', project_id TEXT,
          pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
          client_id TEXT, created REAL NOT NULL,
          UNIQUE(conversation_id, client_id)
        );
        CREATE TABLE IF NOT EXISTS projects(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
          instructions TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_files(
          project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, path TEXT NOT NULL,
          PRIMARY KEY(project_id, path)
        );
        """)
        # Additive migration for versions that predate project-scoped conversations.
        conv_cols={row[1] for row in c.execute("PRAGMA table_info(conversations)").fetchall()}
        if "project_id" not in conv_cols:c.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")
        if "pinned" not in conv_cols:c.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        if "archived" not in conv_cols:c.execute("ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        if "mode" not in conv_cols:c.execute("ALTER TABLE conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat'")
        c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_conversations_owner_updated ON conversations(owner, archived, pinned DESC, updated DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
        CREATE INDEX IF NOT EXISTS idx_projects_owner_updated ON projects(owner, updated DESC);
        """)
        if legacy_messages:
            old_cols={r[1] for r in c.execute("PRAGMA table_info(messages_legacy_v1)").fetchall()}
            id_col="id" if "id" in old_cols else "NULL"
            client_col="client_id" if "client_id" in old_cols else "NULL"
            created_col="created" if "created" in old_cols else "strftime('%s','now')"
            c.execute(f"INSERT OR IGNORE INTO messages(id,conversation_id,role,content,client_id,created) SELECT {id_col},conv_id,role,content,{client_col},{created_col} FROM messages_legacy_v1 WHERE role IN ('user','assistant')")
            c.execute("DROP TABLE messages_legacy_v1")
        c.commit()
    finally:
        c.close()


def now() -> float: return time.time()
def new_id(prefix="c") -> str: return f"{prefix}-{uuid.uuid4().hex[:24]}"


def rowdict(row): return dict(row) if row is not None else None


def list_conversations(owner, query="", project=None, archived=False, limit=100):
    c=connect()
    try:
        sql="SELECT id,title,model,mode,project_id,pinned,archived,created,updated FROM conversations WHERE owner=? AND archived=?"
        args=[owner, 1 if archived else 0]
        if project:
            sql += " AND project_id=?";args.append(project)
        if query:
            sql += " AND (title LIKE ? ESCAPE '\\' OR id IN (SELECT conversation_id FROM messages WHERE content LIKE ? ESCAPE '\\'))"
            escaped=query.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
            like=f"%{escaped}%"
            args += [like, like]
        sql += " ORDER BY pinned DESC, updated DESC LIMIT ?"
        args.append(max(1,min(int(limit),200)))
        return [rowdict(r) for r in c.execute(sql,args).fetchall()]
    finally: c.close()


def get_conversation(owner, cid, with_messages=True):
    c=connect()
    try:
        conv=c.execute("SELECT * FROM conversations WHERE id=? AND owner=?",(cid,owner)).fetchone()
        if not conv: return None
        out=rowdict(conv)
        if with_messages:
            out["messages"]=[rowdict(r) for r in c.execute(
                "SELECT id,role,content,created FROM messages WHERE conversation_id=? ORDER BY id",(cid,)).fetchall()]
            for message in out["messages"]:
                message["content"]=re.sub(r"<think>[\s\S]*?(</think>|$)","",message["content"]).strip()
        return out
    finally: c.close()


def ensure_conversation(owner, cid, title, model, mode, project_id=None):
    c=connect(); t=now()
    try:
        old=c.execute("SELECT owner FROM conversations WHERE id=?",(cid,)).fetchone()
        if old and old["owner"] != owner: return False
        if not old:
            c.execute("INSERT INTO conversations(id,owner,title,model,mode,project_id,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                      (cid,owner,title[:120] or "Cuộc trò chuyện mới",model[:120],mode[:24],project_id,t,t))
        else:
            c.execute("UPDATE conversations SET model=?,mode=?,project_id=?,updated=?,title=CASE WHEN title='Cuộc trò chuyện mới' AND ?<>'' THEN ? ELSE title END WHERE id=? AND owner=?",
                      (model[:120],mode[:24],project_id,t,title[:120],title[:120],cid,owner))
        c.commit(); return True
    finally: c.close()


def add_message(owner, cid, role, content, client_id=None):
    c=connect(); t=now()
    try:
        conv=c.execute("SELECT id FROM conversations WHERE id=? AND owner=?",(cid,owner)).fetchone()
        if not conv: return False
        cur=c.execute("INSERT OR IGNORE INTO messages(conversation_id,role,content,client_id,created) VALUES(?,?,?,?,?)",
                      (cid,role,content[:250000],client_id or None,t))
        c.execute("UPDATE conversations SET updated=? WHERE id=? AND owner=?",(t,cid,owner)); c.commit()
        return cur.rowcount == 1
    finally: c.close()


def history(owner,cid,limit=30):
    c=connect()
    try:
        rows=c.execute("SELECT role,content FROM messages WHERE conversation_id=? AND conversation_id IN (SELECT id FROM conversations WHERE owner=?) ORDER BY id DESC LIMIT ?",
                        (cid,owner,limit)).fetchall()
        result=[rowdict(r) for r in reversed(rows)]
        for message in result:message["content"]=re.sub(r"<think>[\s\S]*?(</think>|$)","",message["content"]).strip()
        return result
    finally: c.close()


def delete_last_turn(owner,cid):
    c=connect()
    try:
        rows=c.execute("SELECT id,role FROM messages WHERE conversation_id=? AND conversation_id IN (SELECT id FROM conversations WHERE owner=?) ORDER BY id DESC LIMIT 2",(cid,owner)).fetchall()
        ids=[]
        if rows and rows[0]["role"]=="assistant": ids.append(rows[0]["id"])
        if len(rows)>0:
            last_user=next((r for r in rows if r["role"]=="user"),None)
            if last_user: ids.append(last_user["id"])
        if ids: c.executemany("DELETE FROM messages WHERE id=?",[(x,) for x in ids]); c.commit()
    finally: c.close()
