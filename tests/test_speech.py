"""Speech-to-text tests with a stand-in `whisper-cli`.

The real binary is whisper.cpp, which we cannot assume is installed. The fake
below speaks the same command-line contract the module relies on (`-m`, `-f`,
`-l`, `-of`, `-oj`, `-np`) and writes the JSON shape whisper.cpp produces:
`{"result": {"language": "en"}, "transcription": [{"text": "..."}]}`.

This lets the two-pass flow (detect language, then transcribe) be tested for
real: argument handling, JSON parsing, the language allowlist, and the
actionable error when the model or binary is missing.
"""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support  # noqa: F401

import backend.speech_recognition as speech  # noqa: E402

FAKE_BIN = """#!/usr/bin/env python3
import json, os, sys

args = sys.argv[1:]
opts = {}
i = 0
while i < len(args):
    a = args[i]
    if a in ("-m", "-f", "-l", "-t", "-of"):
        opts[a] = args[i + 1]
        i += 2
    else:
        i += 1

mode = os.environ.get("FAKE_WHISPER_MODE", "ok")
if mode == "fail":
    sys.stderr.write("boom: model failed to load\\n")
    sys.exit(1)

requested = opts.get("-l", "en")
language = os.environ.get("FAKE_WHISPER_LANG", "en" if requested == "auto" else requested)
text = os.environ.get("FAKE_WHISPER_TEXT", "hello from the fake engine")

payload = {"result": {"language": language}, "transcription": [{"text": text}]}
with open(opts["-of"] + ".json", "w") as handle:
    json.dump(payload, handle)
"""


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin_dir = self.dir / "bin"
        self.bin_dir.mkdir()
        self.exe = self.bin_dir / "whisper-cli"
        self.exe.write_text(FAKE_BIN)
        self.exe.chmod(self.exe.stat().st_mode | stat.S_IEXEC)
        self.model = self.dir / "ggml-test.bin"
        self.model.write_bytes(b"fake-weights")

        self.patches = [
            patch.dict(os.environ, {"PATH": f"{self.bin_dir}:{os.environ['PATH']}"}),
            patch.object(speech, "WHISPER_MODEL", self.model),
            patch.object(speech, "WHISPER_EXECUTABLE", ""),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def test_transcribes_and_detects_language(self):
        result = speech.transcribe_audio(b"RIFFfakewavdata", "clip.wav")

        self.assertEqual(result["text"], "hello from the fake engine")
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["engine"], "whisper.cpp")
        self.assertEqual(result["model"], "ggml-test.bin")

    def test_two_pass_flow_calls_whisper_twice(self):
        with patch.object(speech, "run_whisper", wraps=speech.run_whisper) as runner:
            speech.transcribe_audio(b"audio", "clip.mp3")

        self.assertEqual(runner.call_count, 2)
        languages = [call.args[3] for call in runner.call_args_list]
        self.assertEqual(languages[0], "auto")
        self.assertEqual(languages[1], "en")

    def test_rejects_language_outside_allowlist(self):
        with patch.dict(os.environ, {"FAKE_WHISPER_LANG": "fr"}):
            with self.assertRaises(speech.SpeechRecognitionError) as ctx:
                speech.transcribe_audio(b"audio", "clip.wav")

        self.assertIn("English and Russian", str(ctx.exception))
        self.assertIn("fr", str(ctx.exception))

    def test_missing_model_names_the_fetch_script(self):
        speech.WHISPER_MODEL = self.dir / "absent" / "ggml-base-q5_1.bin"

        with self.assertRaises(speech.SpeechRecognitionError) as ctx:
            speech.transcribe_audio(b"audio", "clip.wav")

        message = str(ctx.exception)
        self.assertIn("Whisper model not found", message)
        self.assertIn("fetch_models.sh", message)

    def test_missing_binary_is_actionable(self):
        self.exe.unlink()
        with patch.dict(os.environ, {"PATH": str(self.dir)}):
            with patch.object(speech, "WHISPER_EXECUTABLE", ""):
                with self.assertRaises(speech.SpeechRecognitionError) as ctx:
                    speech.transcribe_audio(b"audio", "clip.wav")

        self.assertIn("brew install whisper.cpp", str(ctx.exception))

    def test_whisper_executable_override(self):
        with patch.object(speech, "WHISPER_EXECUTABLE", str(self.exe)):
            self.assertEqual(speech.get_whisper_executable(), str(self.exe))

    def test_whisper_executable_override_must_exist(self):
        with patch.object(speech, "WHISPER_EXECUTABLE", str(self.dir / "nope")):
            with self.assertRaises(speech.SpeechRecognitionError) as ctx:
                speech.get_whisper_executable()

        self.assertIn("WHISPER_EXECUTABLE", str(ctx.exception))

    def test_failed_whisper_run_surfaces_stderr(self):
        with patch.dict(os.environ, {"FAKE_WHISPER_MODE": "fail"}):
            with self.assertRaises(speech.SpeechRecognitionError) as ctx:
                speech.transcribe_audio(b"audio", "clip.wav")

        self.assertIn("Whisper failed", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_empty_transcript_rejected(self):
        with patch.dict(os.environ, {"FAKE_WHISPER_TEXT": ""}):
            with self.assertRaises(speech.SpeechRecognitionError) as ctx:
                speech.transcribe_audio(b"audio", "clip.wav")

        self.assertIn("No speech was recognized", str(ctx.exception))

    def test_input_guards(self):
        with self.assertRaises(speech.SpeechRecognitionError):
            speech.transcribe_audio(b"", "clip.wav")
        with self.assertRaises(speech.SpeechRecognitionError):
            speech.transcribe_audio(b"x" * (speech.MAX_AUDIO_SIZE + 1), "clip.wav")
        with self.assertRaises(speech.SpeechRecognitionError):
            speech.transcribe_audio(b"data", "clip.txt")


if __name__ == "__main__":
    unittest.main()
