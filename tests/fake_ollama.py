"""Minimal Ollama stand-in so the backend can be tested without a GPU.

Implements just enough of the API surface that JARVIS touches:

    GET  /api/tags   -> installed model list
    POST /api/chat   -> non-streaming completion

Run standalone for a live server check:

    python3 -m tests.fake_ollama --port 11500
    OLLAMA_BASE_URL=http://127.0.0.1:11500 uvicorn backend.main:app --port 8000

In-process use:

    url, server, stop = serve()
    ...
    server.requests   # every parsed POST body, for assertions
    stop()
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import dotenv_values


def configured_models() -> tuple[str, str]:
    env_values = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    fast_model = os.getenv("FAST_MODEL") or env_values.get("FAST_MODEL")
    advanced_model = os.getenv("ADVANCED_MODEL") or env_values.get("ADVANCED_MODEL")
    return (
        fast_model or "fast-test-model",
        advanced_model or "advanced-test-model",
    )


DEFAULT_MODELS = configured_models()


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeOllama/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        """Silence per-request logging."""
        pass

    @property
    def fake(self) -> "FakeOllama":
        server: FakeOllama = self.server  # type: ignore[assignment]
        return server

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_stream(self, chunks: list[dict]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for chunk in chunks:
            body = (json.dumps(chunk) + "\n").encode("utf-8")
            self.wfile.write(f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": name} for name in self.fake.models]})
        elif self.path == "/":
            self._send({"status": "fake-ollama"})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send({"error": "invalid json"}, 400)
            return

        self.fake.requests.append(payload)

        if self.path != "/api/chat":
            self._send({"error": "not found"}, 404)
            return

        model = payload.get("model")
        if model not in self.fake.models:
            self._send({"error": f"model '{model}' not found"}, 404)
            return

        users = [m for m in payload.get("messages", []) if m.get("role") == "user"]
        last = users[-1]["content"][:60] if users else ""
        reply = f"Fake reply from {model} about: {last}"
        if payload.get("stream"):
            chunks = []
            if payload.get("think"):
                chunks.append(
                    {"message": {"thinking": "Fake reasoning trace"}, "done": False}
                )
            chunks.extend(
                [
                    {"message": {"content": reply[:20]}, "done": False},
                    {"message": {"content": reply[20:]}, "done": False},
                    {"message": {}, "done": True},
                ]
            )
            self._send_stream(chunks)
        else:
            self._send(
                {
                    "model": model,
                    "message": {
                        "role": "assistant",
                        "content": reply,
                    },
                    "done": True,
                }
            )


class FakeOllama(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, models=DEFAULT_MODELS, port: int = 0):
        super().__init__(("127.0.0.1", port), _Handler)
        self.models = list(models)
        self.requests: list[dict] = []


def serve(models=DEFAULT_MODELS, port: int = 0):
    """Start the fake server in a daemon thread.

    Returns (base_url, server, stop). `stop()` shuts the server down and joins
    the thread.
    """
    server = FakeOllama(models=models, port=port)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    def stop() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return f"http://127.0.0.1:{server.server_address[1]}", server, stop


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake Ollama server")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--models", nargs="*", default=list(DEFAULT_MODELS))
    args = parser.parse_args()

    server = FakeOllama(models=args.models, port=args.port)
    print(f"fake ollama on http://127.0.0.1:{server.server_address[1]} models={server.models}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
