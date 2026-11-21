"""Persistence regressions.

Locks down two confirmed defects:

1. `with sqlite3.connect(...) as conn` never closes the handle, so every query
   leaked a file descriptor (measured: +30 fds for 30 saves).
2. `get_display_history()` applied LIMIT in ascending order, so any session
   longer than the limit reloaded showing its oldest messages and hid the most
   recent replies.
"""

import sqlite3
import unittest
from pathlib import Path

from tests import support  # noqa: F401  (import side effects: paths + fake Ollama)

import backend.database as database  # noqa: E402

SESSION = "11111111-1111-1111-1111-111111111111"


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        support.reset_db()

    def test_no_file_descriptor_leak(self):
        before = support.open_fd_count()
        if before < 0:
            self.skipTest("/proc not available")

        for index in range(60):
            database.save_message(SESSION, "user", f"message {index}")
        database.get_history(SESSION)
        database.get_display_history(SESSION)
        database.get_recent_sessions()

        after = support.open_fd_count()
        self.assertEqual(after, before, f"leaked {after - before} file descriptors")

    def test_display_history_returns_newest_messages(self):
        for index in range(250):
            role = "user" if index % 2 == 0 else "assistant"
            database.save_message(SESSION, role, f"message {index}", "qwen3:1.7b")

        page = database.get_display_history(SESSION, limit=100)

        self.assertEqual(len(page), 100)
        self.assertEqual(page[0]["content"], "message 150")
        self.assertEqual(page[-1]["content"], "message 249")
        self.assertEqual(
            [row["content"] for row in page],
            sorted((row["content"] for row in page), key=lambda c: int(c.split()[-1])),
        )

    def test_model_history_is_oldest_first_and_limited(self):
        for index in range(30):
            role = "user" if index % 2 == 0 else "assistant"
            database.save_message(SESSION, role, f"turn {index}", "qwen3:1.7b")

        history = database.get_history(SESSION, limit=10)

        self.assertEqual(len(history), 10)
        self.assertEqual(history[-1]["content"], "turn 29")
        self.assertEqual(history[0]["content"], "turn 20")
        self.assertEqual(set(history[0]), {"role", "content"})

    def test_sessions_are_listed_newest_first_with_first_user_message_as_title(self):
        for session, text in (
            ("aaaaaaaa-1111-1111-1111-111111111111", "first session"),
            ("bbbbbbbb-1111-1111-1111-111111111111", "second session"),
        ):
            database.save_message(session, "user", text)
            database.save_message(session, "assistant", "ok", "qwen3:1.7b")

        sessions = database.get_recent_sessions()

        self.assertEqual([s["session_id"][:1] for s in sessions], ["b", "a"])
        self.assertEqual(sessions[0]["title"], "second session")
        self.assertTrue(sessions[0]["updated_at"])

    def test_migration_adds_model_column_to_legacy_table(self):
        for suffix in ("", "-wal", "-shm"):
            Path(str(support.DB_PATH) + suffix).unlink(missing_ok=True)

        legacy = sqlite3.connect(support.DB_PATH)
        legacy.execute(
            """CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )"""
        )
        legacy.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, 'user', 'legacy row')",
            (SESSION,),
        )
        legacy.commit()
        legacy.close()

        database.initialize_database()
        database.initialize_database()  # idempotent

        with database.get_connection() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}

        self.assertIn("model", columns)
        self.assertEqual(len(database.get_history(SESSION)), 1)

    def test_clear_history_is_scoped_to_session(self):
        other = "22222222-2222-2222-2222-222222222222"
        database.save_message(SESSION, "user", "keep me")
        database.save_message(other, "user", "delete me")

        database.clear_history(other)

        self.assertEqual(len(database.get_history(SESSION)), 1)
        self.assertEqual(len(database.get_history(other)), 0)


if __name__ == "__main__":
    unittest.main()
