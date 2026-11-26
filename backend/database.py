"""SQLite persistence for JARVIS.

Every call takes a short-lived connection that is *explicitly closed*.

Note on `with sqlite3.connect(...) as conn`: that context manager only wraps a
transaction - it never closes the handle. Leaking one file descriptor per query
is invisible in a demo and fatal in a long-running assistant session, so the
connection lifecycle lives in `get_connection()` below.

WAL + busy_timeout are set because `main.py` performs these writes from the
threadpool, so the chat writer and the transcriber can overlap.
"""

import json
import sqlite3
from contextlib import contextmanager

from backend.config import DATABASE_PATH

BUSY_TIMEOUT_MS = 5000
MAX_HISTORY_ATTACHMENT_BYTES = 12 * 1024 * 1024


@contextmanager
def get_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    try:
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
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            model TEXT,
            attachments TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "model" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN model TEXT")
        if "attachments" not in columns:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'"
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id_id ON messages(session_id, id)")


def get_history(
    session_id: str,
    limit: int = 20,
    exclude_message_id: int | None = None,
) -> list[dict]:
    """Newest `limit` messages, returned oldest-first (model context order)."""
    with get_connection() as conn:
        if exclude_message_id is None:
            rows = conn.execute(
                "SELECT role, content, attachments FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT role, content, attachments FROM messages
                WHERE session_id = ? AND id != ?
                ORDER BY id DESC LIMIT ?
                """,
                (session_id, exclude_message_id, limit),
            ).fetchall()
    history = []
    selected_attachments = []
    remaining_attachment_bytes = MAX_HISTORY_ATTACHMENT_BYTES
    for row in rows:
        attachments = json.loads(row["attachments"] or "[]")
        attachment_size = sum(
            len(item.get("content", "").encode("utf-8"))
            for item in attachments
        )
        if attachment_size > remaining_attachment_bytes:
            attachments = []
        else:
            remaining_attachment_bytes -= attachment_size
        selected_attachments.append((row, attachments))

    for row, attachments in reversed(selected_attachments):
        message = {"role": row["role"], "content": row["content"]}
        documents = [
            item for item in attachments
            if item.get("kind") == "text"
        ]
        if documents:
            message["content"] += "\n\n" + "\n\n".join(
                f"[Attached document: {item['name']}]\n{item['content']}"
                for item in documents
            )
        images = [
            item["content"] for item in attachments
            if item.get("kind") == "image"
        ]
        if images:
            message["images"] = images
        history.append(message)
    return history


def get_latest_exchange(session_id: str) -> dict | None:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, model FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 2
            """,
            (session_id,),
        ).fetchall()

    if len(rows) != 2 or rows[0]["role"] != "assistant" or rows[1]["role"] != "user":
        return None

    return {
        "assistant_id": rows[0]["id"],
        "assistant_model": rows[0]["model"],
        "user_content": rows[1]["content"],
    }


def replace_latest_assistant(
    session_id: str,
    message_id: int,
    content: str,
    model: str,
) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE messages
            SET content = ?, model = ?
            WHERE id = ? AND session_id = ? AND role = 'assistant'
              AND id = (SELECT MAX(id) FROM messages WHERE session_id = ?)
            """,
            (content, model, message_id, session_id, session_id),
        )
    return cursor.rowcount == 1


def get_display_history(session_id: str, limit: int = 100) -> list[dict]:
    """Newest `limit` messages, oldest-first, for UI rendering.

    The LIMIT must be applied newest-first and the page re-sorted afterwards,
    otherwise a session longer than `limit` reloads showing its beginning and
    silently hides the most recent replies.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content, model, created_at, attachments
            FROM (
                SELECT id, role, content, model, created_at, attachments
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (session_id, limit),
        ).fetchall()
    messages = []
    remaining_preview_chars = 2 * 1024 * 1024
    for row in reversed(rows):
        message = dict(row)
        stored_attachments = json.loads(message.pop("attachments") or "[]")
        message_attachments = []
        for item in stored_attachments:
            attachment = {
                "name": item["name"],
                "kind": item["kind"],
                "mime": item.get("mime", ""),
            }
            thumbnail = item.get("thumbnail", "")
            if thumbnail and len(thumbnail) <= remaining_preview_chars:
                attachment["thumbnail"] = thumbnail
                remaining_preview_chars -= len(thumbnail)
            message_attachments.append(attachment)
        message["attachments"] = message_attachments
        messages.append(message)
    return list(reversed(messages))


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


def save_message(
    session_id: str,
    role: str,
    content: str,
    model: str | None = None,
    attachments: list[dict] | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, model, attachments) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, model, json.dumps(attachments or [], ensure_ascii=False)),
        )


def clear_history(session_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
