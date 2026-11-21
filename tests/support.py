"""Shared test bootstrap.

Import this before any `backend.*` module: `backend.config` freezes the
environment into module constants at import time, so the database path and the
Ollama URL have to be in place first. One fake Ollama server is started here for
the whole run and stopped at interpreter exit.
"""

import atexit
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import fake_ollama  # noqa: E402

TMPDIR = Path(tempfile.mkdtemp(prefix="jarvis-tests-"))
DB_PATH = TMPDIR / "jarvis.db"

os.environ["DATABASE_PATH"] = str(DB_PATH)
os.environ.pop("OLLAMA_BASE_URL", None)

FAKE_URL, FAKE_SERVER, _stop_fake = fake_ollama.serve()
os.environ["OLLAMA_BASE_URL"] = FAKE_URL
atexit.register(_stop_fake)


def reset_db() -> None:
    """Delete the test database (plus WAL sidecars) and recreate the schema."""
    import backend.database as database

    for suffix in ("", "-wal", "-shm"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
    database.initialize_database()


def reset_fake_requests() -> None:
    FAKE_SERVER.requests.clear()


def fake_requests() -> list[dict]:
    return FAKE_SERVER.requests


def open_fd_count() -> int:
    """Open file descriptors for this process, or -1 where /proc is missing."""
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return -1
