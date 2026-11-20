# JARVIS — Phase 2: Intelligent Local Model Routing

JARVIS is a local-first personal AI assistant. Phase 2 adds automatic routing between two Ollama models while keeping a single SQLite conversation history.

## Features
- Auto mode: routes everyday requests to `qwen3:1.7b` and coding/longer reasoning requests to `qwen3:4b`.
- Manual Fast and Advanced modes in the interface.
- Both models receive the same recent conversation history; switching models does not create a new chat.
- SQLite migration adds a `model` column without deleting existing messages.
- `OLLAMA_KEEP_ALIVE=0` asks Ollama to unload a model after each response to reduce memory pressure. This can make the next response slower because the model must load again.
- No cloud API is called in this phase. Cloud routing will be added only as an opt-in feature with an explicit privacy/consent step.

## MacBook setup

Keep your existing project as a backup before replacing files. Extract this ZIP and copy the contents of `jarvis_local_phase1/` into your project folder, or use the extracted folder as the new project.

```bash
cd ~/Downloads/jarvis_local_phase1
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # only if you do not already have .env
```

If `.env` already exists, edit it and make sure it contains:

```env
JARVIS_NAME=JARVIS
OLLAMA_BASE_URL=http://127.0.0.1:11434
FAST_MODEL=qwen3:1.7b
ADVANCED_MODEL=qwen3:4b
DATABASE_PATH=./data/jarvis.db
MAX_HISTORY_MESSAGES=20
REQUEST_TIMEOUT_SECONDS=240
OLLAMA_KEEP_ALIVE=0
NUM_CTX=4096
```

Install both models if needed:

```bash
ollama pull qwen3:1.7b
ollama pull qwen3:4b
ollama list
```

Start JARVIS:

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

## Test routing

1. Keep `Auto — JARVIS decides` selected.
2. Send: `What is the difference between a list and a tuple in Python?` Expected route: `qwen3:1.7b`.
3. Send: `Review this Python code and explain how to refactor it for better performance: ```python
def f(x): return sorted(set(x))
``` ` Expected route: `qwen3:4b`.
4. Select `Fast` manually and send a complex request. It should still use `qwen3:1.7b`.
5. Select `Advanced` manually. It should use `qwen3:4b` or clearly tell you if it is not installed.
6. Ask a follow-up referring to the previous answer. The conversation should remain continuous after a model change.

## Important memory note
This version prioritizes memory safety by setting `keep_alive=0`. It unloads the model after each response, which saves RAM between requests but adds model-load latency. If the machine remains comfortable in Activity Monitor, you can later test `OLLAMA_KEEP_ALIVE=30s`.

## Current limitations
- Router uses transparent keyword/length/code heuristics, not a separate AI classifier.
- No automatic RAM telemetry yet.
- No cloud provider integration yet; cloud support is a later opt-in milestone.
- No voice or macOS automation yet.
