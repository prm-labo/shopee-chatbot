import sqlite3
import time
import secrets
from contextlib import contextmanager

DB_PATH = "chatbot.db"

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER UNIQUE NOT NULL,
                shop_name TEXT,
                access_token TEXT,
                refresh_token TEXT,
                token_expires_at INTEGER,
                line_user_id TEXT,
                registration_token TEXT,
                product_cache TEXT,
                product_cache_updated_at INTEGER,
                active INTEGER DEFAULT 1,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS processed_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                processed_at INTEGER DEFAULT (strftime('%s','now')),
                UNIQUE(shop_id, message_id)
            );
        """)

def add_user(shop_id: int, shop_name: str, access_token: str, refresh_token: str, expires_at: int) -> str:
    token = secrets.token_hex(8)
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (shop_id, shop_name, access_token, refresh_token, token_expires_at, registration_token)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(shop_id) DO UPDATE SET
                shop_name=excluded.shop_name,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                token_expires_at=excluded.token_expires_at,
                registration_token=excluded.registration_token,
                active=1
        """, (shop_id, shop_name, access_token, refresh_token, expires_at, token))
    return token

def get_all_active_users():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE active=1").fetchall()

def get_user_by_shop_id(shop_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE shop_id=?", (shop_id,)).fetchone()

def update_tokens(shop_id: int, access_token: str, refresh_token: str, expires_at: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE users SET access_token=?, refresh_token=?, token_expires_at=? WHERE shop_id=?
        """, (access_token, refresh_token, expires_at, shop_id))

def link_line_user(registration_token: str, line_user_id: str) -> bool:
    with get_conn() as conn:
        result = conn.execute("""
            UPDATE users SET line_user_id=? WHERE registration_token=? AND line_user_id IS NULL
        """, (line_user_id, registration_token))
        return result.rowcount > 0

def is_message_processed(shop_id: int, message_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_messages WHERE shop_id=? AND message_id=?",
            (shop_id, message_id)
        ).fetchone()
        return row is not None

def mark_message_processed(shop_id: int, message_id: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_messages (shop_id, message_id) VALUES (?, ?)",
            (shop_id, message_id)
        )

def update_product_cache(shop_id: int, product_text: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE users SET product_cache=?, product_cache_updated_at=? WHERE shop_id=?
        """, (product_text, int(time.time()), shop_id))

def get_user_by_registration_token(token: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE registration_token=?", (token,)).fetchone()
