import unittest
from unittest.mock import patch

from tests import support  # noqa: F401

from backend.ollama_client import (  # noqa: E402
    OllamaUnavailable,
    generate_reply,
    get_available_models,
    stream_reply,
)


class _Response:
    def __init__(self, payload=None, lines=()):
        self.payload = payload
        self.lines = lines

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    async def aiter_lines(self):
        for line in self.lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _AsyncClient:
    def __init__(self, response, **_kwargs):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, *_args, **_kwargs):
        return self.response

    async def post(self, *_args, **_kwargs):
        return self.response

    def stream(self, *_args, **_kwargs):
        return self.response


class OllamaClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_malformed_model_list(self):
        response = _Response(payload={"models": ["invalid"]})
        with patch(
            "backend.ollama_client.httpx.AsyncClient",
            return_value=_AsyncClient(response),
        ):
            with self.assertRaisesRegex(OllamaUnavailable, "invalid model list"):
                await get_available_models()

    async def test_rejects_malformed_chat_response(self):
        response = _Response(payload={"message": {"content": []}})
        with patch(
            "backend.ollama_client.httpx.AsyncClient",
            return_value=_AsyncClient(response),
        ):
            with self.assertRaisesRegex(OllamaUnavailable, "invalid response"):
                await generate_reply([], "test-model")

    async def test_rejects_truncated_stream(self):
        response = _Response(lines=['{"message":{"content":"partial"},"done":false}'])
        with patch(
            "backend.ollama_client.httpx.AsyncClient",
            return_value=_AsyncClient(response),
        ):
            with self.assertRaisesRegex(OllamaUnavailable, "ended the response"):
                async for _event in stream_reply([], "test-model"):
                    pass
