#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/Ibrmva/jarvis.git"
OLLAMA_PID=""
OLLAMA_LOG=""

cleanup() {
  if [[ -n "$OLLAMA_PID" ]] && kill -0 "$OLLAMA_PID" 2>/dev/null; then
    kill "$OLLAMA_PID" 2>/dev/null || true
    wait "$OLLAMA_PID" 2>/dev/null || true
  fi
  if [[ -n "$OLLAMA_LOG" ]]; then
    rm -f "$OLLAMA_LOG"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

if [[ -f "$PWD/requirements.txt" && -f "$PWD/backend/main.py" ]]; then
  REPO_ROOT="$PWD"
elif [[ -f "$(dirname "${BASH_SOURCE[0]}")/../requirements.txt" ]]; then
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
  command -v git >/dev/null 2>&1 || die "Git is required to clone JARVIS."
  REPO_ROOT="${JARVIS_DIR:-$PWD/jarvis}"
  if [[ -e "$REPO_ROOT" ]]; then
    [[ -f "$REPO_ROOT/requirements.txt" && -f "$REPO_ROOT/backend/main.py" ]] \
      || die "$REPO_ROOT exists but is not a JARVIS checkout. Set JARVIS_DIR to another path."
  else
    printf 'Cloning JARVIS into %s...\n' "$REPO_ROOT"
    git clone "$REPO_URL" "$REPO_ROOT"
  fi
fi

cd "$REPO_ROOT"
REPO_ROOT="$(pwd)"

command -v curl >/dev/null 2>&1 || die "curl is required."

BREW_BIN="$(command -v brew || true)"
if [[ -z "$BREW_BIN" ]]; then
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    if [[ -x "$candidate" ]]; then
      BREW_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$BREW_BIN" ]]; then
  printf 'Homebrew was not found; installing it now...\n'
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    if [[ -x "$candidate" ]]; then
      BREW_BIN="$candidate"
      break
    fi
  done
  [[ -n "$BREW_BIN" ]] || die "Homebrew installation completed, but brew was not found."
fi
if [[ -n "$BREW_BIN" ]]; then
  BREW_PREFIX="$("$BREW_BIN" --prefix)"
  PATH="$BREW_PREFIX/bin:$PATH"
  export PATH
fi

PYTHON_BIN=""
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null 2>&1 \
    && "$candidate" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)'; then
    PYTHON_BIN="$(command -v "$candidate")"
    break
  fi
done
[[ -n "$PYTHON_BIN" ]] \
  || die "Python 3.10 through 3.14 is required (Python 3.15 is not yet supported by ONNX Runtime)."

if [[ ! -f .env ]]; then
  cp .env.example .env
  printf 'Created .env from .env.example.\n'
fi

if [[ ! -d .venv ]]; then
  printf 'Creating Python virtual environment...\n'
  "$PYTHON_BIN" -m venv .venv
elif ! .venv/bin/python -c \
  'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)'; then
  die "The existing .venv uses an unsupported Python version. Remove .venv and rerun setup to recreate it with Python 3.10 through 3.14."
fi

printf 'Installing Python dependencies...\n'
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

read_config() {
  .venv/bin/python - "$1" <<'PY'
import os
import sys
from pathlib import Path
from dotenv import dotenv_values

key = sys.argv[1]
values = dotenv_values(".env")
defaults = {
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    "FAST_MODEL": "qwen3:1.7b",
    "ADVANCED_MODEL": "qwen3:4b",
}
value = os.environ.get(key) or values.get(key) or defaults.get(key, "")
if key == "WHISPER_MODEL_PATH":
    value = value or str(Path.cwd() / "models/whisper/ggml-base-q5_1.bin")
    path = Path(value).expanduser()
    value = str(path if path.is_absolute() else Path.cwd() / path)
print(value)
PY
}

OLLAMA_BASE_URL="$(read_config OLLAMA_BASE_URL)"
FAST_MODEL="$(read_config FAST_MODEL)"
ADVANCED_MODEL="$(read_config ADVANCED_MODEL)"
WHISPER_MODEL_PATH="$(read_config WHISPER_MODEL_PATH)"
JARVIS_SSL_CERTFILE="$(read_config JARVIS_SSL_CERTFILE)"
JARVIS_SSL_KEYFILE="$(read_config JARVIS_SSL_KEYFILE)"
OLLAMA_CLI_HOST="${OLLAMA_BASE_URL#http://}"
OLLAMA_CLI_HOST="${OLLAMA_CLI_HOST#https://}"
OLLAMA_CLI_HOST="${OLLAMA_CLI_HOST%/}"

if ! command -v ollama >/dev/null 2>&1; then
  if [[ -n "$BREW_BIN" ]]; then
    printf 'Installing Ollama with Homebrew...\n'
    "$BREW_BIN" install ollama
  else
    die "Ollama was not found. Install it from https://ollama.com/download, then rerun this script."
  fi
fi

ollama_ready() {
  curl -fsS --connect-timeout 2 --max-time 4 \
    "${OLLAMA_BASE_URL%/}/api/tags" >/dev/null 2>&1
}

if ! ollama_ready; then
  if [[ "$OLLAMA_BASE_URL" == "http://127.0.0.1:11434" \
     || "$OLLAMA_BASE_URL" == "http://localhost:11434" ]]; then
    printf 'Ollama is not responding; starting its local service...\n'
    OLLAMA_LOG="$(mktemp "${TMPDIR:-/tmp}/jarvis-ollama.XXXXXX")"
    OLLAMA_HOST="$OLLAMA_CLI_HOST" ollama serve >"$OLLAMA_LOG" 2>&1 &
    OLLAMA_PID=$!
    for _ in {1..30}; do
      if ollama_ready; then
        break
      fi
      if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
        cat "$OLLAMA_LOG" >&2
        die "Could not start Ollama. Start it manually and rerun setup."
      fi
      sleep 1
    done
  fi
fi

ollama_ready || die \
  "Ollama is not reachable at $OLLAMA_BASE_URL. Start Ollama or update OLLAMA_BASE_URL in .env."

OLLAMA_HOST="$OLLAMA_CLI_HOST" ollama list >/dev/null \
  || die "Could not query Ollama models. Check that the Ollama CLI uses $OLLAMA_BASE_URL."

if [[ "${JARVIS_SKIP_MODEL_PULL:-0}" == "1" ]]; then
  printf 'Skipping model downloads (JARVIS_SKIP_MODEL_PULL=1).\n'
else
  installed_models="$(OLLAMA_HOST="$OLLAMA_CLI_HOST" ollama list | awk 'NR > 1 { print $1 }')"
  models=("$FAST_MODEL")
  if [[ "$ADVANCED_MODEL" != "$FAST_MODEL" ]]; then
    models+=("$ADVANCED_MODEL")
  fi
  for model in "${models[@]}"; do
    [[ -n "$model" ]] || continue
    if grep -Fqx -- "$model" <<<"$installed_models"; then
      printf 'Ollama model already installed: %s\n' "$model"
    else
      printf 'Downloading Ollama model %s...\n' "$model"
      OLLAMA_HOST="$OLLAMA_CLI_HOST" ollama pull "$model"
    fi
  done
fi

whisper_cli=""
if command -v whisper-cli >/dev/null 2>&1; then
  whisper_cli="$(command -v whisper-cli)"
elif [[ -x /opt/homebrew/bin/whisper-cli ]]; then
  whisper_cli="/opt/homebrew/bin/whisper-cli"
fi

if [[ -z "$whisper_cli" && -n "$BREW_BIN" ]]; then
  printf 'Installing whisper.cpp with Homebrew...\n'
  "$BREW_BIN" install whisper.cpp
  if command -v whisper-cli >/dev/null 2>&1; then
    whisper_cli="$(command -v whisper-cli)"
  elif [[ -x "$("$BREW_BIN" --prefix)/bin/whisper-cli" ]]; then
    whisper_cli="$("$BREW_BIN" --prefix)/bin/whisper-cli"
  fi
fi

if [[ -n "$whisper_cli" ]]; then
  if [[ ! -f "$WHISPER_MODEL_PATH" ]]; then
    default_whisper_model="$REPO_ROOT/models/whisper/ggml-base-q5_1.bin"
    if [[ "$WHISPER_MODEL_PATH" == "$default_whisper_model" ]]; then
      printf 'Downloading the Whisper speech model...\n'
      ./scripts/fetch_models.sh
    else
      printf 'Voice model not found at %s; voice input will need a valid WHISPER_MODEL_PATH.\n' \
        "$WHISPER_MODEL_PATH" >&2
    fi
  fi
else
  printf 'whisper-cli is not installed; text chat will work, but voice transcription will not.\n'
  case "$(uname -s)" in
    Darwin) printf 'Install Homebrew, then rerun setup, or run: brew install whisper.cpp\n' ;;
    Linux) printf 'Install Homebrew or build whisper.cpp and put whisper-cli on PATH.\n' ;;
  esac
fi

host="${JARVIS_HOST:-127.0.0.1}"
port="${JARVIS_PORT:-8000}"
tls_args=()
scheme="http"
if [[ -n "$JARVIS_SSL_CERTFILE" || -n "$JARVIS_SSL_KEYFILE" ]]; then
  [[ -n "$JARVIS_SSL_CERTFILE" && -n "$JARVIS_SSL_KEYFILE" ]] \
    || die "Set both JARVIS_SSL_CERTFILE and JARVIS_SSL_KEYFILE in .env to enable HTTPS."
  [[ -f "$JARVIS_SSL_CERTFILE" ]] \
    || die "TLS certificate not found: $JARVIS_SSL_CERTFILE"
  [[ -f "$JARVIS_SSL_KEYFILE" ]] \
    || die "TLS private key not found: $JARVIS_SSL_KEYFILE"
  tls_args=(--ssl-certfile "$JARVIS_SSL_CERTFILE" --ssl-keyfile "$JARVIS_SSL_KEYFILE")
  scheme="https"
fi
printf '\nJARVIS is ready at %s://%s:%s\n' "$scheme" "$host" "$port"
printf 'Press Ctrl+C to stop the app.\n\n'
.venv/bin/python -m uvicorn backend.main:app --host "$host" --port "$port" "${tls_args[@]}"
