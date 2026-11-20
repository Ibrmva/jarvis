# JARVIS — Phase 2: Intelligent Local Model Routing

JARVIS is a local-first personal AI assistant. Phase 2 routes requests between two Ollama models while keeping a single SQLite conversation history.

## Features

- **Auto mode:** routes everyday requests to `qwen3:1.7b` and coding / reasoning / long requests to `qwen3:4b`. Routing is signal-scored, not a single keyword hit, and every response carries the reason it took that route.
- **Manual Fast and Advanced modes** in the interface. A manual choice always wins over the router.
- **One conversation across models:** both tiers receive the same recent history, so switching tiers does not start a new chat. Each stored message keeps the `model` that produced it.
- **Voice in, voice out:** `/api/transcribe` runs `whisper-cli` (whisper.cpp) locally for speech-to-text; replies are spoken with the browser's `speechSynthesis`.
- **Local command execution:** a fixed allowlist of `open …` phrases launches sites and apps (`open youtube`, `открой телеграм`, `найди на youtube …`). No shell, no arbitrary argv.
- **SQLite migration** adds a `model` column without deleting existing messages.
- **No cloud API is called by the backend.** `OLLAMA_KEEP_ALIVE=0` unloads a model after each reply (saves RAM, costs a reload next turn); use `5m` to keep it warm.
- Note: the optional hand-tracking camera feature loads MediaPipe from a CDN, so that one panel needs network access. Camera frames stay in the browser.

## Requirements

- Python **3.10+** (the code uses `str | None` and `list[dict]`)
- [Ollama](https://ollama.com) on `127.0.0.1:11434`
- `whisper-cli` from whisper.cpp **for voice input only** (`brew install whisper.cpp` on macOS; build from source on Linux)
- The GGML model for whisper — fetched by `scripts/fetch_models.sh`, deliberately not committed (57 MB)

## Setup

```bash
git clone https://github.com/Ibrmva/jarvis
cd jarvis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # every value in it is the code default
./scripts/fetch_models.sh     # ~57 MB whisper model, checksum verified
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

> The API has no authentication. It is meant to be bound to loopback only — do not expose it on `0.0.0.0` without putting an authenticating reverse proxy in front of it.

## Configuration

All settings come from `.env` (see `.env.example`); the defaults live in `backend/config.py`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `FAST_MODEL` | `qwen3:1.7b` | fast tier |
| `ADVANCED_MODEL` | `qwen3:4b` | advanced tier |
| `DATABASE_PATH` | `./data/jarvis.db` | SQLite file |
| `MAX_HISTORY_MESSAGES` | `20` | turns replayed to the model |
| `REQUEST_TIMEOUT_SECONDS` | `240` | `/api/chat` timeout |
| `OLLAMA_KEEP_ALIVE` | `0` | model residency after a reply |
| `NUM_CTX` | `4096` | context window |
| `WHISPER_MODEL_PATH` | `./models/whisper/ggml-base-q5_1.bin` | GGML weights used by `/api/transcribe` |
| `WHISPER_EXECUTABLE` | *(PATH lookup)* | explicit `whisper-cli` binary, overrides `PATH` |

## Troubleshooting

- **`Whisper model not found: …/models/whisper/ggml-base-q5_1.bin`** on voice input — the weights are not in git. Run `./scripts/fetch_models.sh` (57 MB, checksum-verified), or point `WHISPER_MODEL_PATH` at an existing GGML `.bin`.
- **`whisper-cli was not found on PATH`** — install whisper.cpp (`brew install whisper.cpp` on macOS, build from source on Linux) or set `WHISPER_EXECUTABLE` to the binary's full path.
- **`JARVIS currently supports only English and Russian`** — the transcriber runs a language-detection pass first and refuses anything outside `ALLOWED_LANGUAGES` in `backend/speech_recognition.py`.

## Tests

No GPU, no Ollama, no whisper binary required — the suite starts a fake Ollama on a random loopback port:

```bash
python3 -m unittest discover -s tests -t .
```

Coverage: router routing table (including prose-vs-code false positives), database persistence (file-descriptor leak, newest-N history, legacy migration), and the HTTP surface (routing end-to-end, command intercept, 409/503 degradation, validation).

For a manual live check without a model installed:

```bash
python3 -m tests.fake_ollama --port 11500 &
OLLAMA_BASE_URL=http://127.0.0.1:11500 uvicorn backend.main:app --port 8000
```

## Test routing

1. Keep `Auto — JARVIS decides` selected.
2. Send: `What is the difference between a list and a tuple in Python?` Expected route: `qwen3:1.7b`.
3. Send: `Review this Python code and explain how to refactor it for better performance: ```python
def f(x): return sorted(set(x))
``` ` Expected route: `qwen3:4b`.
4. Send: `Explain the class system in Victorian Britain in two sentences.` Expected route: `qwen3:1.7b` — prose mentioning "class" must not escalate.
5. Select `Fast` manually and send a complex request. It should still use `qwen3:1.7b`.
6. Select `Advanced` manually. It should use `qwen3:4b` or clearly tell you (HTTP 409) if it is not installed.
7. Ask a follow-up referring to the previous answer. The conversation should remain continuous after a model change.

## Memory note

`keep_alive=0` prioritises memory safety: the model is unloaded after each reply, which saves RAM between requests but adds model-load latency to the next one. If the machine stays comfortable in Activity Monitor, try `OLLAMA_KEEP_ALIVE=5m` for lower latency.

## Current limitations

- Router uses transparent, anchored heuristics (regex code detection + whole-word intent keywords), not a trained classifier.
- No automatic RAM telemetry or idle-model watchdog yet.
- No cloud provider integration; cloud support is a later opt-in milestone with an explicit consent step.
- `stream:false` and a fixed `num_predict=512`: long answers are truncated and there is no token streaming in the UI yet.
- Command execution and the `whisper-cli` lookup are macOS-shaped (`open -a`, `/opt/homebrew/bin`).

## Layout

```
backend/    FastAPI app, router, Ollama client, SQLite layer, whisper + command sidecars
frontend/   zero-build vanilla UI served from the same origin
models/     whisper weights land here (git-ignored; use scripts/fetch_models.sh)
scripts/    fetch_models.sh
tests/      unittest suite + fake Ollama server
```
