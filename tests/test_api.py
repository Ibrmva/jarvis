"""HTTP-level tests against the FastAPI app, with a fake Ollama upstream.

These exercise the real request path (validation, routing, persistence, the
macOS command intercept, degradation when a model is missing) without needing a
GPU, a whisper binary or Ollama installed.
"""

import base64
import json
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from tests import support  # noqa: F401  (import side effects: paths + fake Ollama)

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import backend.main as main  # noqa: E402
from backend.config import ADVANCED_MODEL, FAST_MODEL, NUM_CTX  # noqa: E402


class ApiTests(unittest.TestCase):
    def setUp(self):
        support.reset_db()
        support.reset_fake_requests()
        support.FAKE_SERVER.models = [FAST_MODEL, ADVANCED_MODEL]
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

    def test_streaming_route_emits_chunks_and_persists_final_reply(self):
        response = self.client.post(
            "/api/chat/stream",
            json={
                "session_id": self.session_id,
                "message": "hello streaming",
                "model_mode": "advanced",
                "reasoning": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(events[0]["type"], "meta")
        self.assertEqual([event["type"] for event in events].count("content"), 2)
        self.assertEqual([event["type"] for event in events].count("thinking"), 1)
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("Fake reply from", events[-1]["reply"])
        self.assertEqual(events[-1]["thinking"], "Fake reasoning trace")
        self.assertTrue(support.fake_requests()[-1]["think"])
        self.assertTrue(support.fake_requests()[-1]["stream"])

        history_response = self.client.get(f"/api/history/{self.session_id}")
        self.assertEqual(history_response.headers["cache-control"], "no-store")
        history = history_response.json()["messages"]
        self.assertEqual([message["role"] for message in history], ["user", "assistant"])
        self.assertEqual(history[-1]["content"], events[-1]["reply"])

    def test_streaming_route_handles_persisted_image_and_text_attachments(self):
        image = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-image-data").decode("ascii")
        thumbnail = base64.b64encode(
            b"\xff\xd8\xff" + b"x" * (96 * 1024 - 3)
        ).decode("ascii")
        attachments = [
            {
                "name": "notes.txt",
                "kind": "text",
                "mime": "text/plain",
                "content": "Project deadline is Friday.",
            },
            {
                "name": "diagram.png",
                "kind": "image",
                "mime": "image/png",
                "content": image,
                "thumbnail": thumbnail,
            },
        ]
        response = self.client.post(
            "/api/chat/stream",
            json={
                "session_id": self.session_id,
                "message": "",
                "model_mode": "fast",
                "attachments": attachments,
            },
        )

        self.assertEqual(response.status_code, 200)
        upstream_user = [
            message
            for message in support.fake_requests()[-1]["messages"]
            if message["role"] == "user"
        ][-1]
        self.assertIn("Project deadline is Friday.", upstream_user["content"])
        self.assertIn("Please analyze the attached file(s).", upstream_user["content"])
        self.assertEqual(upstream_user["images"], [image])

        history = self.client.get(f"/api/history/{self.session_id}").json()["messages"]
        user_message = history[0]
        self.assertEqual(
            [item["name"] for item in user_message["attachments"]],
            ["notes.txt", "diagram.png"],
        )
        self.assertNotIn("content", user_message["attachments"][0])
        self.assertNotIn(image, json.dumps(history))
        self.assertEqual(user_message["attachments"][1]["thumbnail"], thumbnail)

        self.client.post(
            "/api/chat",
            json={
                "session_id": self.session_id,
                "message": "When is the deadline?",
                "model_mode": "fast",
            },
        )
        followup_user = [
            message
            for message in support.fake_requests()[-1]["messages"]
            if message["role"] == "user"
        ]
        self.assertIn("Project deadline is Friday.", followup_user[0]["content"])
        self.assertEqual(followup_user[0]["images"], [image])

    def test_attachment_image_content_must_match_declared_type(self):
        response = self.client.post(
            "/api/chat/stream",
            json={
                "session_id": self.session_id,
                "message": "Describe this",
                "attachments": [
                    {
                        "name": "not-an-image.png",
                        "kind": "image",
                        "mime": "image/png",
                        "content": base64.b64encode(b"not an image").decode("ascii"),
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(support.fake_requests(), [])

    def test_chat_rejects_unknown_fields_instead_of_silently_ignoring_them(self):
        response = self.client.post(
            "/api/chat/stream",
            json={
                "session_id": self.session_id,
                "message": "Describe this",
                "attachments": [],
                "unexpected": True,
            },
        )
        self.assertEqual(response.status_code, 422)

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

    def test_regenerate_replaces_latest_reply_without_duplicating_user_message(self):
        request = {
            "session_id": self.session_id,
            "message": "hello there",
            "model_mode": "fast",
        }
        self.assertEqual(self.client.post("/api/chat", json=request).status_code, 200)

        response = self.client.post("/api/chat", json={**request, "regenerate": True})

        self.assertEqual(response.status_code, 200)
        history = self.client.get(f"/api/history/{self.session_id}").json()["messages"]
        self.assertEqual([message["role"] for message in history], ["user", "assistant"])
        self.assertEqual(history[0]["content"], "hello there")
        generated_messages = support.fake_requests()[-1]["messages"]
        self.assertEqual(
            [message["role"] for message in generated_messages if message["role"] == "user"],
            ["user"],
        )
        self.assertFalse(any(message["role"] == "assistant" for message in generated_messages))

    def test_regenerate_does_not_repeat_macos_actions(self):
        canned = {"reply": "Opening youtube.", "action": "open_website"}
        request = {
            "session_id": self.session_id,
            "message": "open youtube",
            "model_mode": "auto",
        }
        with patch.object(main, "execute_command", return_value=canned) as executor:
            self.assertEqual(self.client.post("/api/chat", json=request).status_code, 200)
            response = self.client.post("/api/chat", json={**request, "regenerate": True})

        self.assertEqual(response.status_code, 409)
        executor.assert_called_once_with("open youtube")

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

    def test_unknown_website_is_resolved_by_local_model_and_opened(self):
        with (
            patch.object(
                main,
                "resolve_website_url",
                new=AsyncMock(return_value="https://www.reddit.com"),
            ),
            patch.object(main, "open_website") as open_website,
        ):
            response = self.client.post(
                "/api/chat",
                json={
                    "session_id": self.session_id,
                    "message": "Could you open Reddit?",
                    "model_mode": "fast",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["model"], "macOS")
        self.assertEqual(body["tier"], "action")
        self.assertEqual(body["reply"], "Opening Reddit.")
        open_website.assert_called_once_with("https://www.reddit.com")

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
        with patch.object(
            main,
            "get_available_models",
            new=AsyncMock(return_value=[FAST_MODEL, ADVANCED_MODEL]),
        ):
            body = self.client.get("/api/models").json()
        self.assertEqual([m["id"] for m in body["models"]], ["auto", "fast", "advanced"])
        self.assertTrue(all(m["available"] for m in body["models"]))
        self.assertIn(FAST_MODEL, body["models"][1]["label"])
        self.assertIn(ADVANCED_MODEL, body["models"][2]["label"])

    def test_wake_word_websocket_reports_detection(self):
        with (
            patch.object(main, "load_wake_word_model"),
            patch.object(main, "detect_wake_word", side_effect=[False, True]),
            patch.object(main, "reset_wake_word_model") as reset_model,
        ):
            with self.client.websocket_connect("/api/wake-word") as websocket:
                self.assertEqual(websocket.receive_json(), {"type": "ready"})
                websocket.send_bytes(b"\0\0" * 1280)
                websocket.send_bytes(b"\0\0" * 1280)
                self.assertEqual(websocket.receive_json(), {"type": "wake"})
        reset_model.assert_called_once_with()

    def test_wake_word_rejects_cross_origin_websocket(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/wake-word",
                headers={"origin": "https://attacker.example"},
            ):
                pass

    def test_audio_upload_limit_is_checked_before_transcription(self):
        with patch.object(main, "MAX_AUDIO_SIZE", 4), patch.object(
            main, "transcribe_audio"
        ) as transcribe:
            response = self.client.post(
                "/api/transcribe",
                files={"audio": ("recording.wav", b"12345", "audio/wav")},
            )

        self.assertEqual(response.status_code, 413)
        transcribe.assert_not_called()

    def test_http_responses_include_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_chat_rejects_cross_origin_post(self):
        response = self.client.post(
            "/api/chat",
            headers={"origin": "https://attacker.example"},
            json={
                "session_id": self.session_id,
                "message": "hello",
                "model_mode": "fast",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(support.fake_requests(), [])

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
