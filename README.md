# JARVIS

JARVIS is a local-first personal AI assistant for macOS. It provides a web interface over a FastAPI backend and routes requests to local Ollama models.

**Current version:** `0.4.0`

## Current features

- **Adaptive local model routing**: choose Auto, Fast, or Advanced response mode.
  - Fast: `qwen3:1.7b`
  - Advanced: `qwen3:4b`
  - Auto: routing is based on request length, coding keywords, and code blocks.
- **Persistent conversations**: messages are stored in a local SQLite database, with a shared history across model changes and a recent-conversation sidebar.
- **Voice input**: browser microphone recording is transcribed locally with `whisper.cpp` for English and Russian.
- **Voice output**: assistant replies can be read aloud with the browser speech synthesis API.
- **macOS actions**: predefined requests can open supported applications and websites or run Google and YouTube searches.
- **Snow Vision**: browser-local hand tracking draws interactive snow particles from fingertips using MediaPipe and the device camera. Camera video is not uploaded or recorded.
- **Local status dashboard**: the interface reports Ollama and configured-model availability.

## macOS setup

### 1. Install prerequisites

Install Ollama and `whisper.cpp`:

```bash
brew install ollama whisper-cpp
ollama serve
```

Keep Ollama running in the background, or open the Ollama app.

### 2. Create a Python environment

```bash
cd /path/to/jarvis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure the environment

Create `.env` in the project root. The following values match the defaults:

```env
JARVIS_NAME=JARVIS
OLLAMA_BASE_URL=http://127.0.0.1:11434
FAST_MODEL=qwen3:1.7b
ADVANCED_MODEL=qwen3:4b
DEFAULT_MODEL_MODE=auto
DATABASE_PATH=./data/jarvis.db
MAX_HISTORY_MESSAGES=20
REQUEST_TIMEOUT_SECONDS=240
OLLAMA_KEEP_ALIVE=0
NUM_CTX=4096
```

Pull the language models:

```bash
ollama pull qwen3:1.7b
ollama pull qwen3:4b
ollama list
```

The repository includes the Whisper model at:

```text
models/whisper/ggml-base-q5_1.bin
```

### 4. Start JARVIS

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>.

Microphone and camera access use browser permissions. Use Safari or a recent Chrome-based browser and allow access when prompted.

## Using JARVIS

- Use the sidebar to switch between `Auto`, `Fast`, and `Advanced`.
- Press `Cmd+K` or use **New conversation** to start a new conversation.
- Use the microphone button to record up to 60 seconds of speech. Transcription is currently limited to English and Russian.
- Use **Clear chat** to remove the current conversation from SQLite.
- Open **Snow Vision** and activate the camera for fingertip particle tracking.

## macOS commands

The following predefined, safe actions are handled before the request is sent to an Ollama model:

- Open an application: `open Telegram`, `запусти Safari`, `open Visual Studio Code`
- Open a website: `open YouTube`, `открой Google`, `open GitHub`
- Search YouTube: `search YouTube lo-fi music`
- Search Google: `найди в гугл weather`

Supported applications and websites are listed in `backend/command_executor.py`. Unknown requests fall back to normal AI chat.

## API

- `GET /` - web interface
- `GET /api/health` - Ollama and model status
- `GET /api/models` - available response modes and model installation status
- `GET /api/history/{session_id}` - conversation history
- `GET /api/sessions` - recent conversations
- `POST /api/chat` - send a chat message
- `POST /api/transcribe` - transcribe uploaded WAV, MP3, FLAC, or OGG audio
- `DELETE /api/history/{session_id}` - clear one conversation

## Memory and performance

`OLLAMA_KEEP_ALIVE=0` asks Ollama to unload a model after each response. This reduces memory pressure between requests but may add model loading latency.

`NUM_CTX=4096` controls the context window. `MAX_HISTORY_MESSAGES` limits the number of recent messages included in each model request. Increasing either value may require more RAM.

## Project structure

```text
backend/
  main.py                 FastAPI application and API routes
  config.py               Environment configuration and system prompt
  database.py             SQLite conversation storage
  model_router.py         Heuristic Fast/Advanced routing
  ollama_client.py        Ollama health and chat integration
  speech_recognition.py   whisper.cpp transcription
  command_executor.py     Predefined macOS actions
frontend/
  index.html              JARVIS interface
  app.js                  Chat, voice, history, and Snow Vision behavior
  styles.css              Interface styles
models/
  whisper/                Local Whisper speech model
data/                     Local SQLite database, created at runtime
```

## Current limitations

- The model router uses keyword, code, and length heuristics; it is not a learned classifier.
- Advanced routing falls back to the Fast model when the Advanced model is unavailable. Explicit Advanced mode returns an error if it is not installed.
- macOS automation is limited to the predefined websites, applications, and searches in `backend/command_executor.py`.
- Voice transcription supports English and Russian and requires `whisper-cli` plus the bundled Whisper model.
- There is no wake-word listener or always-on assistant mode yet.
