"""HTTP-level tests against the FastAPI app, with a fake Ollama upstream.

These exercise the real request path (validation, routing, persistence, the
macOS command intercept, degradation when a model is missing) without needing a
GPU, a whisper binary or Ollama installed.
"""

import unittest
import uuid
from unittest.mock import AsyncMock, patch

from tests import support  # noqa: F401  (import side effects: paths + fake Ollama)

from fastapi.testclient import TestClient  # noqa: E402

import backend.main as main  # noqa: E402
from backend.config import ADVANCED_MODEL, FAST_MODEL, NUM_CTX  # noqa: E402


class ApiTests(unittest.TestCase):
    def setUp(self):
        support.reset_db()
        support.reset_fake_requests()
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.session_id = str(uuid.uuid4())

    def tearDown(self):
        self.client.__exit__(None, None, None)

    # ---- chat ---------------------------------------------------------
    def test_fast_route_end_to_end(self):
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": self.session_id,
                "message": "what is a tuple in python",
                "model_mode": "auto",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["model"], FAST_MODEL)
        self.assertEqual(body["tier"], "fast")
        self.assertTrue(body["routing_reason"])
        self.assertIn("Fake reply from", body["reply"])

        upstream = support.fake_requests()[-1]
        self.assertEqual(upstream["model"], FAST_MODEL)
        self.assertEqual(upstream["options"]["num_ctx"], NUM_CTX)
        self.assertIn("keep_alive", upstream)
        self.assertEqual(upstream["messages"][0]["role"], "system")

    def test_advanced_route_for_code(self):
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": self.session_id,
                "message": "```python\ndef f(x): return x\n```",
                "model_mode": "auto",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["model"], ADVANCED_MODEL)
        self.assertEqual(body["tier"], "advanced")
        self.assertIn("code", body["routing_reason"])

    def test_user_message_is_sent_upstream_exactly_once(self):
        self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "hello there", "model_mode": "fast"},
        )

        users = [
            message
            for message in support.fake_requests()[-1]["messages"]
            if message["role"] == "user"
        ]
        self.assertEqual([m["content"] for m in users], ["hello there"])

    def test_history_is_shared_across_model_switches(self):
        self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "first question", "model_mode": "fast"},
        )
        self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "second question", "model_mode": "advanced"},
        )

        messages = support.fake_requests()[-1]["messages"]
        contents = [m["content"] for m in messages if m["role"] == "user"]
        self.assertEqual(contents, ["first question", "second question"])

    def test_reply_is_persisted_with_model(self):
        self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "hello", "model_mode": "fast"},
        )

        history = self.client.get(f"/api/history/{self.session_id}").json()["messages"]
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])
        self.assertEqual(history[1]["model"], FAST_MODEL)

    def test_macos_command_is_intercepted_before_the_model(self):
        canned = {"reply": "Opening youtube.", "action": "open_website"}

        with patch.object(main, "execute_command", return_value=canned) as executor:
            response = self.client.post(
                "/api/chat",
                json={"session_id": self.session_id, "message": "open youtube", "model_mode": "auto"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["model"], "macOS")
        self.assertEqual(body["tier"], "action")
        self.assertEqual(body["reply"], "Opening youtube.")
        executor.assert_called_once_with("open youtube")
        self.assertEqual(support.fake_requests(), [])

    # ---- degradation --------------------------------------------------
    def test_missing_advanced_model_in_manual_mode_returns_409(self):
        with patch.object(main, "get_available_models", new=AsyncMock(return_value=[FAST_MODEL])):
            response = self.client.post(
                "/api/chat",
                json={"session_id": self.session_id, "message": "hi", "model_mode": "advanced"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("ollama pull", response.json()["detail"])

    def test_missing_advanced_model_in_auto_mode_falls_back_to_fast(self):
        with patch.object(main, "get_available_models", new=AsyncMock(return_value=[FAST_MODEL])):
            response = self.client.post(
                "/api/chat",
                json={
                    "session_id": self.session_id,
                    "message": "```python\nprint(1)\n```",
                    "model_mode": "auto",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["model"], FAST_MODEL)
        self.assertEqual(body["tier"], "fast")
        self.assertIn("fell back", body["routing_reason"])

    def test_no_models_installed_returns_503(self):
        with patch.object(main, "get_available_models", new=AsyncMock(return_value=[])):
            response = self.client.post(
                "/api/chat",
                json={"session_id": self.session_id, "message": "hi", "model_mode": "auto"},
            )

        self.assertEqual(response.status_code, 503)

    # ---- validation ---------------------------------------------------
    def test_invalid_session_id_rejected(self):
        response = self.client.post(
            "/api/chat",
            json={"session_id": "not-a-uuid", "message": "hi", "model_mode": "auto"},
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_model_mode_rejected(self):
        response = self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "hi", "model_mode": "turbo"},
        )
        self.assertEqual(response.status_code, 422)

    def test_blank_message_rejected(self):
        response = self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "    ", "model_mode": "auto"},
        )
        self.assertEqual(response.status_code, 400)

    def test_oversized_message_rejected(self):
        response = self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "x" * 12001, "model_mode": "auto"},
        )
        self.assertEqual(response.status_code, 422)

    def test_history_endpoint_validates_session_id(self):
        self.assertEqual(self.client.get("/api/history/nope").status_code, 400)
        self.assertEqual(self.client.delete("/api/history/nope").status_code, 400)

    # ---- other endpoints ----------------------------------------------
    def test_health_reports_models(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["fast_model_available"])
        self.assertTrue(body["advanced_model_available"])
        self.assertEqual(body["speech_engine"], "whisper.cpp")

    def test_models_endpoint_lists_three_modes(self):
        body = self.client.get("/api/models").json()
        self.assertEqual([m["id"] for m in body["models"]], ["auto", "fast", "advanced"])
        self.assertTrue(all(m["available"] for m in body["models"]))

    def test_sessions_endpoint_lists_created_session(self):
        self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "hello", "model_mode": "fast"},
        )

        sessions = self.client.get("/api/sessions").json()["sessions"]
        self.assertEqual(sessions[0]["session_id"], self.session_id)
        self.assertEqual(sessions[0]["title"], "hello")

    def test_delete_history_clears_session(self):
        self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": "hello", "model_mode": "fast"},
        )

        self.assertEqual(self.client.delete(f"/api/history/{self.session_id}").json()["status"], "cleared")
        self.assertEqual(self.client.get(f"/api/history/{self.session_id}").json()["messages"], [])

    def test_transcribe_rejects_unsupported_format(self):
        response = self.client.post(
            "/api/transcribe",
            files={"audio": ("notes.txt", b"not audio", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported audio format", response.json()["detail"])

    def test_transcribe_rejects_empty_upload(self):
        response = self.client.post(
            "/api/transcribe",
            files={"audio": ("empty.wav", b"", "audio/wav")},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
