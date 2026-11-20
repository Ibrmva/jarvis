# Changelog

## Unreleased — voice input diagnostics

### Fixed

- **`Whisper model not found: …` was a dead end.** The weights are no longer in git, so a fresh clone had no way to know how to get them. The error now names `scripts/fetch_models.sh` and `WHISPER_MODEL_PATH`; the `whisper-cli` error names the per-OS install and `WHISPER_EXECUTABLE`. Both are covered by `tests/test_speech.py`, which drives a stand-in `whisper-cli` through the real two-pass (detect language → transcribe) flow.

### Added

- `WHISPER_MODEL_PATH` and `WHISPER_EXECUTABLE` settings (config + `.env.example` + README table) so a different GGML model or a non-PATH binary is a config change, not a code edit.
- README troubleshooting section for the three voice-input failure modes.

## Unreleased — hardening pass

### Fixed

- **File-descriptor leak in the persistence layer.** `with sqlite3.connect(...) as conn` wraps a transaction, not the handle, so every query leaked one descriptor. Measured on the original code: 30 `save_message()` calls → +30 open fds, i.e. `EMFILE` after a long session. Connections are now opened, committed and closed inside `backend.database.get_connection()`.
- **Truncated history on reload.** `get_display_history()` applied `LIMIT` in ascending order, so a session longer than the limit reloaded showing its oldest messages and hid the newest replies (250-row session returned rows 0–99). The page now selects newest-first and re-sorts.
- **Router false positives.** Auto mode escalated on substrings, so `import duty on tea exports was reduced` and `Explain the class system in Victorian Britain` both hit the 4B model with the reason "code detected". Detection is now anchored (`^…$` code statements, whole-word intent keywords, explicit fences) and signal-scored, so plain prose stays on the fast tier while `def f(x): return x`, fenced blocks and `SELECT … FROM` still escalate.
- **Concurrent writes.** WAL journaling and a 5 s `busy_timeout` are set, since `main.py` writes to SQLite from the threadpool (chat and transcribe can overlap).
- **Config drift.** `MAX_HISTORY_MESSAGES` defaulted to 10 in code while the README documented 20; `.env.example` is now the single source of documented defaults.

### Removed

- **`frontend/magic.js` (1 413 lines) and its ~450 lines of CSS.** It was never loaded by `index.html`, its required DOM nodes (`#magic-stage`, `#magic-renderer`, `#magic-form` …) did not exist, and it POSTed to `/api/magic/interpret`, an endpoint the backend never implemented. Pure dead code, plus a second copy of the MediaPipe bootstrap.
- **`frontend/dist/index.html`.** Byte-identical to `frontend/index.html` and never served — `main.py` serves `frontend/index.html` directly.
- **`models/whisper/ggml-base-q5_1.bin` (57 MB) from git.** 99.7 % of the repository pack. Fetched on demand instead.

### Added

- `scripts/fetch_models.sh` — downloads the whisper GGML model and verifies its SHA-256; `models/**/*.bin` is git-ignored.
- `tests/` — 33 stdlib `unittest` cases with a fake Ollama server (`tests/fake_ollama.py`), covering the routing table, the persistence regressions above, and the HTTP surface (routing end-to-end, command intercept, 409/503 degradation, validation). No GPU, Ollama or whisper binary required:
  `python3 -m unittest discover -s tests -t .`
- `.github/workflows/tests.yml` — runs the suite on Python 3.10/3.12/3.13.
- `.env.example`, `LICENSE` (MIT), and a README rewritten for a git clone (the old one still told you to extract a ZIP and copy a `jarvis_local_phase1/` folder).

### Not addressed yet

- No authentication or CORS policy; the API is safe only while bound to loopback. Any exposure of the port grants full transcript read access plus the `open …` allowlist.
- `stream:false` with a fixed `num_predict=512`, so long answers truncate and the UI shows no tokens while waiting.
- MediaPipe (hand-tracking panel) and Three.js are still loaded from `cdn.jsdelivr.net` / `storage.googleapis.com` at runtime; vendoring them is pending.
- `keep_alive=0` is still the default: correct for memory, expensive in latency. An idle-unload watchdog would allow `5m`.
- Command execution and the `whisper-cli` fallback path remain macOS-specific.
