import unittest
from unittest.mock import patch

from backend.command_executor import (
    execute_command,
    extract_website_open_target,
    validate_website_url,
)


class CommandExecutorTests(unittest.TestCase):
    @patch("backend.command_executor.open_website")
    def test_english_open_command_replies_in_english(self, open_website):
        result = execute_command("open youtube")

        self.assertEqual(result["reply"], "Opening youtube.")
        open_website.assert_called_once_with("https://www.youtube.com")

    def test_extracts_dynamic_website_targets(self):
        self.assertEqual(extract_website_open_target("Could you open Reddit?"), "Reddit")
        self.assertEqual(
            extract_website_open_target("открой сайт Wikipedia"),
            "Wikipedia",
        )

    def test_validates_only_public_https_website_urls(self):
        self.assertEqual(
            validate_website_url("https://www.reddit.com/r/python"),
            "https://www.reddit.com/r/python",
        )
        for url in (
            "http://example.com",
            "javascript:alert(1)",
            "https://localhost",
            "https://127.0.0.1",
            "https://user@example.com",
        ):
            with self.subTest(url=url):
                self.assertIsNone(validate_website_url(url))

    @patch("backend.command_executor.open_website")
    def test_russian_open_command_replies_in_russian(self, open_website):
        result = execute_command("открой youtube")

        self.assertEqual(result["reply"], "Открываю youtube.")
        open_website.assert_called_once_with("https://www.youtube.com")

    @patch("backend.command_executor.open_website")
    def test_english_youtube_search_replies_in_english(self, open_website):
        result = execute_command("search youtube cats")

        self.assertEqual(result["reply"], "Searching YouTube for: cats.")
        open_website.assert_called_once_with(
            "https://www.youtube.com/results?search_query=cats"
        )


if __name__ == "__main__":
    unittest.main()
