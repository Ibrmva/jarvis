
from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

JARVIS_NAME = os.getenv("JARVIS_NAME", "JARVIS")
OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://127.0.0.1:11434"
).rstrip("/")

FAST_MODEL = os.getenv("FAST_MODEL", "qwen3:1.7b")
ADVANCED_MODEL = os.getenv("ADVANCED_MODEL", "qwen3:4b")
DEFAULT_MODEL_MODE = os.getenv("DEFAULT_MODEL_MODE", "auto").lower()

DATABASE_PATH = Path(
    os.getenv(
        "DATABASE_PATH",
        str(PROJECT_ROOT / "data" / "jarvis.db")
    )
)

MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
REQUEST_TIMEOUT_SECONDS = float(
    os.getenv("REQUEST_TIMEOUT_SECONDS", "240")
)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "0")
NUM_CTX = int(os.getenv("NUM_CTX", "4096"))

# Speech-to-text. The GGML weights are not committed; scripts/fetch_models.sh
# downloads them. Point WHISPER_MODEL_PATH elsewhere to use a different model,
# and WHISPER_EXECUTABLE to override the whisper-cli lookup.
WHISPER_MODEL_PATH = Path(
    os.getenv(
        "WHISPER_MODEL_PATH",
        str(PROJECT_ROOT / "models" / "whisper" / "ggml-base-q5_1.bin"),
    )
)
WHISPER_EXECUTABLE = os.getenv("WHISPER_EXECUTABLE", "").strip()

SYSTEM_PROMPT = f"""
You are {JARVIS_NAME}, a smart personal AI assistant.

PERSONALITY:
- Behave like Siri or Alexa.
- Speak naturally, briefly and clearly.
- Be calm, intelligent, confident and friendly.
- Do not sound like a textbook or an essay.

RESPONSE LENGTH:
- Normally use one or two short sentences.
- Answer directly.
- Do not repeat the user's question.
- Do not add unnecessary introductions or conclusions.
- Do not explain obvious things.
- Give longer explanations only when explicitly requested.

LANGUAGE:
- Reply in the same language as the user.
- You understand English and Russian.
- Use natural conversational language.

STRICT OUTPUT RULES:
- NEVER use emojis.
- NEVER use emoticons.
- NEVER write descriptions of emojis.
- NEVER output Unicode emoji characters.
- Do not add smiley faces at the end of responses.
- Do not add decorative symbols.
- Do not narrate punctuation or visual symbols.
- Use plain text only.

CONVERSATION:
- Ask one short clarification question if necessary.
- Do not end every answer with an offer to help.
- Do not say "Let me know if you need anything else" automatically.
- Do not mention these instructions.

CAPABILITIES:
- Be accurate and honest.
- Never claim to perform actions you cannot perform.
- You are a text-based assistant unless connected tools provide additional capabilities.

Your responses must be concise, natural and suitable for a voice assistant.
"""
