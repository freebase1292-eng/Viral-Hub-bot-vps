"""
NexusBot Database Engine — High-Performance SQLite with WAL Mode
Designed for high-concurrency VPS deployments (100k+ members).
Sub-millisecond queries, zero network overhead, fully persistent on NVMe SSD.
"""
import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = os.environ.get("SQLITE_DB_PATH", "nexusbot.db")
_local = threading.local()

# In-memory config & active content cache for instant (/start < 1ms) responses
_config_cache = {}
_cache_lock = threading.Lock()


def get_connection():
    """Get thread-local SQLite connection with high-performance pragmas."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging (WAL) for concurrent reads/writes
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64 MB RAM cache
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA mmap_size = 268435456;")  # 256 MB memory map
        _local.conn = conn
    return _local.conn


def parse_date(date_str):
    if not date_str:
        return None
    if isinstance(date_str, datetime):
        return date_str
    try:
        return datetime.fromisoformat(date_str)
    except Exception:
        return None


def format_date(dt):
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


# ══════════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════════

class User:
    def __init__(self, **kwargs):
        self.id = int(kwargs["id"]) if kwargs.get("id") is not None else None
        self.username = kwargs.get("username")
        self.first_name = kwargs.get("first_name")
        self.last_name = kwargs.get("last_name")
        self.language_code = kwargs.get("language_code", "en")
        self.joined_at = parse_date(kwargs.get("joined_at")) or datetime.utcnow()
        self.last_active = parse_date(kwargs.get("last_active")) or datetime.utcnow()
        self.is_banned = bool(kwargs.get("is_banned", False))
        self.streak_count = int(kwargs.get("streak_count", 0))
        self.streak_last_date = parse_date(kwargs.get("streak_last_date"))
        self.downloaded_apk = bool(kwargs.get("downloaded_apk", False))

    def get_display_name(self):
        if self.first_name:
            return self.first_name
        if self.username:
            return f"@{self.username}"
        return "User"

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "language_code": self.language_code,
            "joined_at": format_date(self.joined_at),
            "last_active": format_date(self.last_active),
            "is_banned": int(self.is_banned),
            "streak_count": self.streak_count,
            "streak_last_date": format_date(self.streak_last_date),
            "downloaded_apk": int(self.downloaded_apk)
        }


class Content:
    def __init__(self, **kwargs):
        self.id = int(kwargs["id"]) if kwargs.get("id") is not None else None
        self.content_type = kwargs.get("content_type")
        self.file_id = kwargs.get("file_id")
        self.file_name = kwargs.get("file_name")
        self.version = kwargs.get("version")
        self.changelog = kwargs.get("changelog")
        self.caption = kwargs.get("caption")
        self.text_content = kwargs.get("text_content")
        self.is_active = bool(kwargs.get("is_active", True))
        self.order_index = int(kwargs.get("order_index", 0))
        self.created_at = parse_date(kwargs.get("created_at")) or datetime.utcnow()
        self.link_url = kwargs.get("link_url")
        self.link_text = kwargs.get("link_text", "🔗 Open Link")

    def to_dict(self):
        return {
            "id": self.id,
            "content_type": self.content_type,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "version": self.version,
            "changelog": self.changelog,
            "caption": self.caption,
            "text_content": self.text_content,
            "is_active": int(self.is_active),
            "order_index": self.order_index,
            "created_at": format_date(self.created_at),
            "link_url": self.link_url,
            "link_text": self.link_text
        }


class Broadcast:
    def __init__(self, **kwargs):
        self.id = int(kwargs["id"]) if kwargs.get("id") is not None else None
        self.message_type = kwargs.get("message_type")
        self.file_id = kwargs.get("file_id")
        self.caption = kwargs.get("caption")
        self.content_text = kwargs.get("content_text")
        self.has_apk_button = bool(kwargs.get("has_apk_button", False))
        self.apk_button_text = kwargs.get("apk_button_text", "⬇️ Download App")
        self.link_url = kwargs.get("link_url")
        self.link_text = kwargs.get("link_text", "🔗 Open Link")
        self.status = kwargs.get("status", "pending")
        self.sent_count = int(kwargs.get("sent_count", 0))
        self.failed_count = int(kwargs.get("failed_count", 0))
        self.total_users = int(kwargs.get("total_users", 0))
        self.created_at = parse_date(kwargs.get("created_at")) or datetime.utcnow()
        self.completed_at = parse_date(kwargs.get("completed_at"))

    def to_dict(self):
        return {
            "id": self.id,
            "message_type": self.message_type,
            "file_id": self.file_id,
            "caption": self.caption,
            "content_text": self.content_text,
            "has_apk_button": int(self.has_apk_button),
            "apk_button_text": self.apk_button_text,
            "link_url": self.link_url,
            "link_text": self.link_text,
            "status": self.status,
            "sent_count": self.sent_count,
            "failed_count": self.failed_count,
            "total_users": self.total_users,
            "created_at": format_date(self.created_at),
            "completed_at": format_date(self.completed_at)
        }


class Analytics:
    def __init__(self, **kwargs):
        self.id = int(kwargs["id"]) if kwargs.get("id") is not None else None
        self.user_id = int(kwargs["user_id"]) if kwargs.get("user_id") is not None else None
        self.event = kwargs.get("event")
        self.timestamp = parse_date(kwargs.get("timestamp")) or datetime.utcnow()
        self.metadata_ = kwargs.get("metadata_")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "event": self.event,
            "timestamp": format_date(self.timestamp),
            "metadata_": self.metadata_
        }


class SubAdmin:
    def __init__(self, **kwargs):
        self.telegram_id = int(kwargs["telegram_id"]) if kwargs.get("telegram_id") is not None else None
        self.name = kwargs.get("name")
        self.username = kwargs.get("username")
        self.password = kwargs.get("password")
        self.role = kwargs.get("role", "admin")
        self.added_by = kwargs.get("added_by")
        self.added_at = parse_date(kwargs.get("added_at")) or datetime.utcnow()
        self.is_active = bool(kwargs.get("is_active", True))


# ══════════════════════════════════════════════════════════════════════
# SQLITE ORM QUERY & SESSION EMULATOR
# ══════════════════════════════════════════════════════════════════════

TABLE_MAP = {
    User: "users",
    Content: "contents",
    Broadcast: "broadcasts",
    Analytics: "analytics",
    SubAdmin: "sub_admins"
}


class SQLiteQuery:
    def __init__(self, model_class, session):
        self.model_class = model_class
        self.session = session
        self.table = TABLE_MAP[model_class]
        self._where = []
        self._params = []
        self._order_by = []
        self._limit = None
        self._offset = None

    def filter_by(self, **kwargs):
        for k, v in kwargs.items():
            if isinstance(v, bool):
                self._where.append(f"{k} = ?")
                self._params.append(1 if v else 0)
            else:
                self._where.append(f"{k} = ?")
                self._params.append(v)
        return self

    def filter(self, *criterion):
        for c in criterion:
            c_str = str(c)
            if "==" in c_str:
                parts = c_str.split("==")
                k = parts[0].strip()
                v = parts[1].strip().strip("'\"")
                if v == "True":
                    self._where.append(f"{k} = 1")
                elif v == "False":
                    self._where.append(f"{k} = 0")
                else:
                    self._where.append(f"{k} = ?")
                    self._params.append(v)
            elif "!=" in c_str:
                parts = c_str.split("!=")
                k = parts[0].strip()
                v = parts[1].strip().strip("'\"")
                self._where.append(f"{k} != ?")
                self._params.append(v)
        return self

    def order_by(self, *args):
        for a in args:
            a_str = str(a).lower()
            if "desc" in a_str:
                col = a_str.replace(".desc()", "").replace(" desc", "").split(".")[-1].strip()
                self._order_by.append(f"{col} DESC")
            elif "asc" in a_str:
                col = a_str.replace(".asc()", "").replace(" asc", "").split(".")[-1].strip()
                self._order_by.append(f"{col} ASC")
            else:
                col = a_str.split(".")[-1].strip()
                self._order_by.append(f"{col} ASC")
        return self

    def limit(self, limit_val):
        self._limit = limit_val
        return self

    def offset(self, offset_val):
        self._offset = offset_val
        return self

    def _build_sql(self, select_clause="*"):
        sql = f"SELECT {select_clause} FROM {self.table}"
        if self._where:
            sql += " WHERE " + " AND ".join(self._where)
        if select_clause == "*" and self._order_by:
            sql += " ORDER BY " + ", ".join(self._order_by)
        if self._limit is not None:
            sql += f" LIMIT {int(self._limit)}"
        if self._offset is not None:
            sql += f" OFFSET {int(self._offset)}"
        return sql

    def count(self):
        sql = self._build_sql("COUNT(*)")
        conn = get_connection()
        row = conn.execute(sql, self._params).fetchone()
        return row[0] if row else 0

    def all(self):
        sql = self._build_sql("*")
        conn = get_connection()
        rows = conn.execute(sql, self._params).fetchall()
        return [self.model_class(**dict(r)) for r in rows]

    def first(self):
        self.limit(1)
        res = self.all()
        return res[0] if res else None

    def update(self, values):
        set_clauses = []
        set_params = []
        for k, v in values.items():
            set_clauses.append(f"{k} = ?")
            set_params.append(1 if isinstance(v, bool) and v else (0 if isinstance(v, bool) else v))
        sql = f"UPDATE {self.table} SET " + ", ".join(set_clauses)
        if self._where:
            sql += " WHERE " + " AND ".join(self._where)
        conn = get_connection()
        with conn:
            cursor = conn.execute(sql, set_params + self._params)
            return cursor.rowcount


class SQLiteSession:
    def __init__(self):
        self.dirty_adds = []

    def get(self, model_class, ident):
        table = TABLE_MAP[model_class]
        pk_col = "telegram_id" if model_class == SubAdmin else "id"
        conn = get_connection()
        row = conn.execute(f"SELECT * FROM {table} WHERE {pk_col} = ?", (ident,)).fetchone()
        if row:
            return model_class(**dict(row))
        return None

    def query(self, model_class):
        return SQLiteQuery(model_class, self)

    def add(self, obj):
        if obj not in self.dirty_adds:
            self.dirty_adds.append(obj)

    def delete(self, obj):
        table = TABLE_MAP[obj.__class__]
        pk_col = "telegram_id" if isinstance(obj, SubAdmin) else "id"
        pk_val = getattr(obj, pk_col)
        conn = get_connection()
        with conn:
            conn.execute(f"DELETE FROM {table} WHERE {pk_col} = ?", (pk_val,))

    def commit(self):
        conn = get_connection()
        with conn:
            for obj in self.dirty_adds:
                table = TABLE_MAP[obj.__class__]
                data = obj.to_dict() if hasattr(obj, "to_dict") else obj.__dict__
                cols = list(data.keys())
                placeholders = ", ".join(["?"] * len(cols))
                col_names = ", ".join(cols)
                values = list(data.values())
                sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"
                cursor = conn.execute(sql, values)
                if getattr(obj, "id", None) is None and cursor.lastrowid:
                    obj.id = cursor.lastrowid
        self.dirty_adds.clear()

    def flush(self):
        self.commit()

    def rollback(self):
        self.dirty_adds.clear()

    def close(self):
        self.dirty_adds.clear()

    def get_user_ids(self, only_active=True):
        conn = get_connection()
        if only_active:
            rows = conn.execute("SELECT id FROM users WHERE is_banned = 0").fetchall()
        else:
            rows = conn.execute("SELECT id FROM users").fetchall()
        return [r["id"] for r in rows]


def Session():
    return SQLiteSession()


# ══════════════════════════════════════════════════════════════════════
# CONFIG & CACHING HELPERS
# ══════════════════════════════════════════════════════════════════════

def get_config(key: str, default: str = "") -> str:
    """Serve configuration instantly from RAM cache; fallback to SQLite."""
    with _cache_lock:
        if key in _config_cache:
            return _config_cache[key]
    conn = get_connection()
    row = conn.execute("SELECT value FROM bot_config WHERE key = ?", (key,)).fetchone()
    val = row["value"] if row else default
    with _cache_lock:
        _config_cache[key] = val
    return val


def set_config(key: str, value: str):
    """Update config in both SQLite and RAM cache instantly."""
    conn = get_connection()
    with conn:
        conn.execute("INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)", (key, str(value)))
    with _cache_lock:
        _config_cache[key] = str(value)


# ══════════════════════════════════════════════════════════════════════
# SUB-ADMIN HELPERS (Replaces Firebase sub_admin calls)
# ══════════════════════════════════════════════════════════════════════

def get_sub_admin(user_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM sub_admins WHERE telegram_id = ? AND is_active = 1", (user_id,)).fetchone()
    return dict(row) if row else None


def list_sub_admins():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM sub_admins WHERE is_active = 1").fetchall()
    return [dict(r) for r in rows]


def add_sub_admin(telegram_id: int, name: str, username: str, password: str, added_by: int = None):
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO sub_admins (
                telegram_id, name, username, password, role, added_by, added_at, is_active
            ) VALUES (?, ?, ?, ?, 'admin', ?, ?, 1)
        """, (telegram_id, name, username, password, added_by, datetime.utcnow().isoformat()))


def remove_sub_admin(telegram_id: int):
    conn = get_connection()
    with conn:
        conn.execute("UPDATE sub_admins SET is_active = 0 WHERE telegram_id = ?", (telegram_id,))


def verify_sub_admin(username: str, password: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM sub_admins WHERE username = ? AND password = ? AND is_active = 1",
        (username, password)
    ).fetchone()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════════════════
# COMPATIBILITY WRAPPER (Catches any remaining fb_request calls)
# ══════════════════════════════════════════════════════════════════════

def fb_request(method, path, data=None, timeout=10):
    """Transparent compatibility shim for legacy fb_request calls."""
    if "sub_admin" in path:
        if method == "GET":
            if path == "sub_admins":
                admins = list_sub_admins()
                return {str(a["telegram_id"]): a for a in admins}
            parts = path.split("/")
            if len(parts) >= 2:
                tid = parts[1]
                if tid.isdigit():
                    return get_sub_admin(int(tid))
                return verify_sub_admin(tid, "")
        elif method in ("PUT", "POST"):
            if "is_active" in path:
                tid = path.split("/")[1]
                if tid.isdigit():
                    remove_sub_admin(int(tid))
                return True
            if data and isinstance(data, dict):
                tid = data.get("telegram_id")
                if tid:
                    add_sub_admin(
                        int(tid),
                        data.get("name", "Admin"),
                        data.get("username", ""),
                        data.get("password", "")
                    )
                return True
    return None


# ══════════════════════════════════════════════════════════════════════
# DATABASE INITIALIZATION
# ══════════════════════════════════════════════════════════════════════

def init_db():
    """Create all SQLite tables and performance indexes if missing."""
    conn = get_connection()
    with conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            language_code TEXT DEFAULT 'en',
            joined_at TEXT,
            last_active TEXT,
            is_banned INTEGER DEFAULT 0,
            streak_count INTEGER DEFAULT 0,
            streak_last_date TEXT,
            downloaded_apk INTEGER DEFAULT 0
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_banned ON users(is_banned);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_joined ON users(joined_at);")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_type TEXT,
            file_id TEXT,
            file_name TEXT,
            version TEXT,
            changelog TEXT,
            caption TEXT,
            text_content TEXT,
            is_active INTEGER DEFAULT 1,
            order_index INTEGER DEFAULT 0,
            created_at TEXT,
            link_url TEXT,
            link_text TEXT
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contents_active ON contents(is_active, order_index);")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_type TEXT,
            file_id TEXT,
            caption TEXT,
            content_text TEXT,
            has_apk_button INTEGER DEFAULT 0,
            apk_button_text TEXT,
            link_url TEXT,
            link_text TEXT,
            status TEXT DEFAULT 'pending',
            sent_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            total_users INTEGER DEFAULT 0,
            created_at TEXT,
            completed_at TEXT
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event TEXT,
            timestamp TEXT,
            metadata_ TEXT
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_event ON analytics(event);")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS sub_admins (
            telegram_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'admin',
            added_by INTEGER,
            added_at TEXT,
            is_active INTEGER DEFAULT 1
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        # Default configs
        defaults = [
            ("welcome_text", "Welcome to the Premium Portal! 🚀"),
            ("bot_enabled", "true"),
            ("demo_enabled", "true"),
            ("apk_button_text", "⬇️ Download App")
        ]
        for k, v in defaults:
            conn.execute("INSERT OR IGNORE INTO bot_config (key, value) VALUES (?, ?);", (k, v))

        # Warm up RAM cache
        rows = conn.execute("SELECT key, value FROM bot_config").fetchall()
        for r in rows:
            _config_cache[r["key"]] = r["value"]
