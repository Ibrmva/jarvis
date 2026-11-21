import unittest
from unittest.mock import patch

from backend.command_executor import execute_command


class CommandExecutorTests(unittest.TestCase):
    @patch("backend.command_executor.open_website")
    def test_english_open_command_replies_in_english(self, open_website):
        result = execute_command("open youtube")

        self.assertEqual(result["reply"], "Opening youtube.")
        open_website.assert_called_once_with("https://www.youtube.com")

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
