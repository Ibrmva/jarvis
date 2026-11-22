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

    @patch("backend.command_executor.open_website")
    def test_search_query_before_youtube_opens_encoded_results(self, open_website):
        result = execute_command("search for cats & dogs on YouTube")

        self.assertEqual(result["action"], "youtube_search")
        open_website.assert_called_once_with(
            "https://www.youtube.com/results?search_query=cats+%26+dogs"
        )

    @patch("backend.command_executor.open_website")
    def test_search_google_for_query_opens_results(self, open_website):
        result = execute_command("find weather in Tokyo on Google")

        self.assertEqual(result["action"], "google_search")
        open_website.assert_called_once_with(
            "https://www.google.com/search?q=weather+in+Tokyo"
        )

    @patch("backend.command_executor.open_website")
    def test_russian_youtube_search_with_query_first(self, open_website):
        result = execute_command("найди смешные коты на ютубе")

        self.assertEqual(result["reply"], "Ищу на YouTube: смешные коты.")
        open_website.assert_called_once_with(
            "https://www.youtube.com/results?search_query="
            "%D1%81%D0%BC%D0%B5%D1%88%D0%BD%D1%8B%D0%B5+%D0%BA%D0%BE%D1%82%D1%8B"
        )


if __name__ == "__main__":
    unittest.main()
