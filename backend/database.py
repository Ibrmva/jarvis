"""SQLite persistence for JARVIS.

Every call takes a short-lived connection that is *explicitly closed*.

Note on `with sqlite3.connect(...) as conn`: that context manager only wraps a
transaction - it never closes the handle. Leaking one file descriptor per query
is invisible in a demo and fatal in a long-running assistant session, so the
connection lifecycle lives in `get_connection()` below.

WAL + busy_timeout are set because `main.py` performs these writes from the
threadpool, so the chat writer and the transcriber can overlap.
"""

import sqlite3
from contextlib import contextmanager

from backend.config import DATABASE_PATH

BUSY_TIMEOUT_MS = 5000


@contextmanager
def get_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            model TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "model" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN model TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id_id ON messages(session_id, id)")


def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """Newest `limit` messages, returned oldest-first (model context order)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def get_display_history(session_id: str, limit: int = 100) -> list[dict]:
    """Newest `limit` messages, oldest-first, for UI rendering.

    The LIMIT must be applied newest-first and the page re-sorted afterwards,
    otherwise a session longer than `limit` reloads showing its beginning and
    silently hides the most recent replies.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content, model, created_at
            FROM (
                SELECT id, role, content, model, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_recent_sessions(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT session_id,
                      (SELECT content FROM messages AS first_message
                       WHERE first_message.session_id = messages.session_id
                         AND first_message.role = 'user'
                       ORDER BY first_message.id ASC LIMIT 1) AS title,
                      MAX(created_at) AS updated_at
               FROM messages
               GROUP BY session_id
               ORDER BY MAX(id) DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_message(session_id: str, role: str, content: str, model: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, model) VALUES (?, ?, ?, ?)",
            (session_id, role, content, model),
        )


def clear_history(session_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
