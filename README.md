# JARVIS — Phase 2: Intelligent Local Model Routing

JARVIS is a local-first personal AI assistant. Phase 2 routes requests between two Ollama models while keeping a single SQLite conversation history.

## Features

- **Auto mode:** routes everyday requests to the `FAST_MODEL` configured in `.env` and coding / reasoning / long requests to `ADVANCED_MODEL`. Routing is signal-scored, not a single keyword hit, and every response carries the reason it took that route.
- **Manual Fast and Advanced modes** in the interface. A manual choice always wins over the router.
- **Local attachments:** attach JPEG, PNG, or WebP images and plain-text documents (`.txt`, `.md`, `.csv`, `.json`, `.yaml`, `.xml`, `.log`) to a chat. Attachments are validated, stored with the local conversation, and included in later model context; image understanding depends on the selected Ollama model supporting vision.
- **One conversation across models:** both tiers receive the same recent history, so switching tiers does not start a new chat. Each stored message keeps the `model` that produced it.
- **Voice in, voice out:** `/api/transcribe` runs `whisper-cli` (whisper.cpp) locally for speech-to-text; replies are spoken with the browser's `speechSynthesis`. Assistant responses can be spoken or copied, and the latest response can be regenerated from its message controls.
- **Optional wake word:** enable **Hey JARVIS** in the sidebar for local, always-on wake-word detection. When detected, JARVIS gives a brief spoken greeting, then listens for your request; it is sent after 1.2 seconds of silence. If no speech follows within 8 seconds, JARVIS discards the empty capture and listens again. Wake-word detection pauses while JARVIS transcribes and replies, then resumes. The browser streams microphone frames only to the local backend, and the detector model is downloaded on first use. Listening is off by default and pauses when the browser tab is backgrounded.
- **Local command execution:** the local model can resolve natural-language requests to public HTTPS websites, while app launches remain allowlisted (`открой телеграм`, `open calculator`). Search commands support both `search cats on YouTube` and `search YouTube for cats`, plus Russian forms. No shell or arbitrary argv.
- **SQLite migration** adds a `model` column without deleting existing messages.
- **No cloud API is called by the backend.** `OLLAMA_KEEP_ALIVE=0` unloads a model after each reply (saves RAM, costs a reload next turn); use `5m` to keep it warm.
- Note: the optional hand-tracking camera feature loads MediaPipe from a CDN, so that one panel needs network access. Camera frames stay in the browser.

## Requirements

- Python **3.10 through 3.14** (Python 3.15 is not yet supported by the ONNX Runtime dependency)
- [Ollama](https://ollama.com) on `127.0.0.1:11434`
- `whisper-cli` from whisper.cpp **for voice input only** (`brew install whisper.cpp` on macOS; build from source on Linux)
- `openwakeword` and ONNX Runtime (installed from `requirements.txt`) for wake-word detection
- The GGML model for whisper — fetched by `scripts/fetch_models.sh`, deliberately not committed (57 MB)

## Setup

The setup script supports macOS and Linux. It can clone the repository, install
Homebrew if needed, create the Python environment, install dependencies,
configure `.env`, install Ollama and whisper.cpp, check/start Ollama, pull the
configured models, fetch the Whisper model, and launch JARVIS:

```bash
curl -fsSL https://raw.githubusercontent.com/Ibrmva/jarvis/main/scripts/setup.sh | bash
```

By default, this clones into `./jarvis`. To choose another directory, set
`JARVIS_DIR`; to skip downloading Ollama models, set
`JARVIS_SKIP_MODEL_PULL=1`. If Homebrew installation fails, install Ollama from
[ollama.com/download](https://ollama.com/download); on Linux, install
whisper.cpp separately to enable voice input. The script reads `FAST_MODEL`,
`ADVANCED_MODEL`, and `OLLAMA_BASE_URL` from `.env` and preserves an existing
`.env`.

If the repository is already cloned, run the script from its root:

```bash
./scripts/setup.sh
```

Manual setup:

```bash
git clone https://github.com/Ibrmva/jarvis
cd jarvis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # every value in it is the code default
./scripts/fetch_models.sh     # ~57 MB whisper model, checksum verified
```

Install each model ID configured by `FAST_MODEL` and `ADVANCED_MODEL` in `.env` with `ollama pull <model-id>`, then verify them with `ollama list`.

Start JARVIS:

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

To access JARVIS from another device on your private network, bind it to the network interfaces. Plain HTTP is fine for chat, but mobile browsers block microphone access on HTTP LAN addresses. To use the microphone, configure HTTPS with a certificate trusted by the phone:

```bash
JARVIS_HOST=0.0.0.0 ./scripts/setup.sh
```

JARVIS does not provide user authentication. Keep LAN access on a trusted private network, use a firewall, and never expose the service directly to the public internet. HTTPS protects traffic in transit; it does not replace authentication.

One option for a private LAN is [mkcert](https://github.com/FiloSottile/mkcert): install it on the computer, then run `mkcert -install`, `mkdir -p certs`, and `mkcert -cert-file certs/jarvis.pem -key-file certs/jarvis-key.pem <your-computer's-LAN-IP>`. Set `JARVIS_SSL_CERTFILE=./certs/jarvis.pem` and `JARVIS_SSL_KEYFILE=./certs/jarvis-key.pem` in `.env`. Install mkcert's `rootCA.pem` (from `mkcert -CAROOT`) on the phone and trust it; never copy or share `rootCA-key.pem`. The certificate must include the address you open on your phone. Restart setup and open `https://<your-computer's-LAN-IP>:8000`. A self-signed certificate that the phone does not trust will not enable microphone access.

If starting Uvicorn manually, pass `--host 0.0.0.0 --ssl-certfile <certificate> --ssl-keyfile <private-key>`. The API has no authentication, so only make it reachable on a trusted private network; never port-forward it or expose it to the internet.

## Configuration

All settings come from `.env` (see `.env.example`); the defaults live in `backend/config.py`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `FAST_MODEL` | `.env` value | fast tier |
| `ADVANCED_MODEL` | `.env` value | advanced tier |
| `DATABASE_PATH` | `./data/jarvis.db` | SQLite file |
| `MAX_HISTORY_MESSAGES` | `20` | turns replayed to the model |
| `REQUEST_TIMEOUT_SECONDS` | `240` | `/api/chat` timeout |
| `OLLAMA_KEEP_ALIVE` | `0` | model residency after a reply |
| `NUM_CTX` | `4096` | context window |
| `WHISPER_MODEL_PATH` | `./models/whisper/ggml-base-q5_1.bin` | GGML weights used by `/api/transcribe` |
| `WHISPER_EXECUTABLE` | *(PATH lookup)* | explicit `whisper-cli` binary, overrides `PATH` |

## Troubleshooting

- **No matching distribution found for `onnxruntime`** — use Python 3.10 through 3.14. Python 3.15 does not yet have a compatible ONNX Runtime package; setup selects an older installed Python when available. If an existing `.venv` was created with Python 3.15, remove it and rerun setup.
- **`Whisper model not found: …/models/whisper/ggml-base-q5_1.bin`** on voice input — the weights are not in git. Run `./scripts/fetch_models.sh` (57 MB, checksum-verified), or point `WHISPER_MODEL_PATH` at an existing GGML `.bin`.
- **`whisper-cli was not found on PATH`** — install whisper.cpp (`brew install whisper.cpp` on macOS, build from source on Linux) or set `WHISPER_EXECUTABLE` to the binary's full path.
- **Wake-word listening fails to start** — allow microphone access, keep JARVIS open in a secure browser context (localhost or HTTPS), and ensure the first-run model download can reach GitHub. Microphone audio is processed by the local JARVIS backend.
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
2. Send: `What is the difference between a list and a tuple in Python?` Expected route: the configured fast model.
3. Send: `Review this Python code and explain how to refactor it for better performance: ```python
def f(x): return sorted(set(x))
``` ` Expected route: the configured advanced model.
4. Send: `Explain the class system in Victorian Britain in two sentences.` Expected route: the configured fast model — prose mentioning "class" must not escalate.
5. Select `Fast` manually and send a complex request. It should still use the configured fast model.
6. Select `Advanced` manually. It should use the configured advanced model or clearly tell you (HTTP 409) if it is not installed.
7. Ask a follow-up referring to the previous answer. The conversation should remain continuous after a model change.

## Memory note

`keep_alive=0` prioritises memory safety: the model is unloaded after each reply, which saves RAM between requests but adds model-load latency to the next one. If the machine stays comfortable in Activity Monitor, try `OLLAMA_KEEP_ALIVE=5m` for lower latency.

## Current limitations

- Router uses transparent, anchored heuristics (regex code detection + whole-word intent keywords), not a trained classifier.
- No automatic RAM telemetry or idle-model watchdog yet.
- No cloud provider integration; cloud support is a later opt-in milestone with an explicit consent step.
- The optional Hey JARVIS detector recognizes English wake phrases and requires the browser tab to remain open; mobile browsers may suspend it while backgrounded.
- Chat output streams from Ollama into the UI, including reasoning traces when enabled. The legacy `/api/chat` endpoint remains non-streaming for JSON clients; the UI uses `/api/chat/stream`.
- Command execution and the `whisper-cli` lookup are macOS-shaped (`open -a`, `/opt/homebrew/bin`).

## Layout

```
backend/    FastAPI app, router, Ollama client, SQLite layer, whisper + command sidecars
frontend/   zero-build vanilla UI served from the same origin
models/     whisper weights land here (git-ignored; use scripts/fetch_models.sh)
scripts/    setup.sh, fetch_models.sh
tests/      unittest suite + fake Ollama server
```
