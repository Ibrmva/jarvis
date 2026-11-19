
import httpx
import re

from backend.config import (
    OLLAMA_BASE_URL,
    REQUEST_TIMEOUT_SECONDS,
    SYSTEM_PROMPT,
    OLLAMA_KEEP_ALIVE,
    NUM_CTX,
)


class OllamaUnavailable(RuntimeError):
    pass


def clean_assistant_text(text: str) -> str:
    """Remove emoji and decorative symbols from assistant output."""

    if not text:
        return ""

    # Remove emoji and pictographic Unicode characters.
    text = re.sub(
        r"[\U0001F000-\U0001FAFF"
        r"\U00002600-\U000027BF"
        r"\U0000FE00-\U0000FE0F"
        r"\U0001F1E6-\U0001F1FF"
        r"\U0000200D"
        r"\U000020E3]+",
        "",
        text,
    )

    # Remove common text emoticons.
    text = re.sub(
        r"(?<!\w)(?:[:;=]-?[)(DPp]|<3)(?!\w)",
        "",
        text,
    )

    # Clean spaces left behind.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


async def get_available_models() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(
                f"{OLLAMA_BASE_URL}/api/tags"
            )
            response.raise_for_status()
            payload = response.json()

            return [
                item.get("name", "")
                for item in payload.get("models", [])
            ]

    except (httpx.HTTPError, ValueError) as exc:
        raise OllamaUnavailable(
            f"Cannot reach Ollama at {OLLAMA_BASE_URL}. "
            "Open the Ollama app and try again."
        ) from exc


async def check_ollama(
    fast_model: str,
    advanced_model: str
) -> dict:
    models = await get_available_models()

    return {
        "ollama": "online",
        "available_models": models,
        "fast_model": fast_model,
        "fast_model_available": fast_model in models,
        "advanced_model": advanced_model,
        "advanced_model_available": advanced_model in models,
    }


async def generate_reply(
    history: list[dict],
    model: str
) -> str:

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        *history
    ]

    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0.4,
            "num_ctx": NUM_CTX,
            "num_predict": 512,
        },
    }

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS
        ) as client:

            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=body
            )

            response.raise_for_status()
            payload = response.json()

            answer = (
                payload.get("message", {})
                .get("content", "")
                .strip()
            )

            answer = clean_assistant_text(answer)

            if not answer:
                raise OllamaUnavailable(
                    "The local model returned an empty response."
                )

            return answer

    except httpx.ConnectError as exc:
        raise OllamaUnavailable(
            "Ollama is not running. Open the Ollama app and retry."
        ) from exc

    except httpx.TimeoutException as exc:
        raise OllamaUnavailable(
            "The model took too long to respond. "
            "Try a shorter request."
        ) from exc

    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]

        raise OllamaUnavailable(
            f"Ollama returned an error: {detail}"
        ) from exc
