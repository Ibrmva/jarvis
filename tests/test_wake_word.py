import unittest
from unittest.mock import Mock, patch

from backend import wake_word


class FakeWakeWordModel:
    def __init__(self, score):
        self.score = score
        self.samples = None

    def predict(self, samples):
        self.samples = samples
        return {"hey_jarvis": self.score}


class WakeWordTests(unittest.TestCase):
    def test_detects_hey_jarvis_above_threshold(self):
        model = FakeWakeWordModel(0.6)
        with patch.object(wake_word, "load_wake_word_model", return_value=model):
            self.assertTrue(wake_word.detect_wake_word(b"\x01\x00" * 1280))
        self.assertEqual(len(model.samples), 1280)

    def test_ignores_scores_below_threshold(self):
        model = FakeWakeWordModel(0.49)
        with patch.object(wake_word, "load_wake_word_model", return_value=model):
            self.assertFalse(wake_word.detect_wake_word(b"\x00\x00" * 1280))

    def test_rejects_malformed_pcm(self):
        with self.assertRaises(ValueError):
            wake_word.detect_wake_word(b"\x00")

    def test_resets_loaded_model_state(self):
        model = FakeWakeWordModel(0.6)
        model.reset = Mock()
        with patch.object(wake_word, "_model", model):
            wake_word.reset_wake_word_model()
        model.reset.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
