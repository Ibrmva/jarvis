"""Routing regressions.

The bugs these lock down: substring matching sent plain English to the big
model whenever it contained "class", "import" or "def", and the README's own
"fast" example never actually exercised a discriminating signal.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import ADVANCED_MODEL, FAST_MODEL  # noqa: E402
from backend.model_router import choose_model  # noqa: E402


class RouterTests(unittest.TestCase):
    def assertTier(self, message: str, tier: str) -> None:
        route = choose_model(message)
        self.assertEqual(
            route.tier,
            tier,
            msg=f"{message!r} routed to {route.tier} ({route.reason})",
        )
        self.assertEqual(route.model, FAST_MODEL if tier == "fast" else ADVANCED_MODEL)
        self.assertTrue(route.reason)

    def test_prose_with_code_keywords_stays_fast(self):
        # Every one of these is ordinary English, not code.
        for message in (
            "import duty on tea exports was reduced",
            "Explain the class system in Victorian Britain in two sentences",
            "select one from the list please",
            "What is the difference between a list and a tuple in Python?",
            "Tell me about the history of the Roman empire please",
            "hi",
        ):
            with self.subTest(message=message):
                self.assertTier(message, "fast")

    def test_real_code_escalates(self):
        for message in (
            "def f(x): return x",
            "class Foo:\n    pass",
            "from collections import OrderedDict\n\nimport os\n",
            "SELECT name FROM users WHERE id = 1",
            "```python\nx = 1\n```",
        ):
            with self.subTest(message=message):
                self.assertTier(message, "advanced")

    def test_reasoning_intent_escalates(self):
        for message in (
            "Please compare approaches",
            "Teach me to debug this",
            "Разработай архитектуру сервиса",
            "I want to build a bench out of oak, step by step",
        ):
            with self.subTest(message=message):
                self.assertTier(message, "advanced")

    def test_readme_examples(self):
        self.assertTier("What is the difference between a list and a tuple in Python?", "fast")
        self.assertTier(
            "Review this Python code and explain how to refactor it for better "
            "performance: ```python\ndef f(x): return sorted(set(x))\n```",
            "advanced",
        )

    def test_long_request_escalates(self):
        self.assertTier("x" * 1900, "advanced")

    def test_manual_modes_win(self):
        self.assertEqual(choose_model("why is the sky blue", "fast").model, FAST_MODEL)
        self.assertEqual(choose_model("```python\nprint(1)\n```", "fast").tier, "fast")
        self.assertEqual(choose_model("hi", "advanced").model, ADVANCED_MODEL)
        self.assertEqual(choose_model("hi", "advanced").tier, "advanced")

    def test_unknown_mode_falls_back_to_auto(self):
        self.assertTier("hi", "fast")
        self.assertEqual(choose_model("hi", "bogus").tier, "fast")


if __name__ == "__main__":
    unittest.main()
