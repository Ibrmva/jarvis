
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from backend.config import PROJECT_ROOT

WHISPER_MODEL = PROJECT_ROOT / "models" / "whisper" / "ggml-base-q5_1.bin"

SUPPORTED_FORMATS = {".wav", ".mp3", ".flac", ".ogg"}
MAX_AUDIO_SIZE = 20 * 1024 * 1024
ALLOWED_LANGUAGES = {"en", "ru"}


class SpeechRecognitionError(RuntimeError):
    pass


def get_whisper_executable() -> str:
    executable = shutil.which("whisper-cli")

    if not executable:
        fallback = Path("/opt/homebrew/bin/whisper-cli")
        if fallback.exists():
            executable = str(fallback)

    if not executable:
        raise SpeechRecognitionError(
            "whisper-cli was not found. Install it using: brew install whisper.cpp"
        )

    return executable


def run_whisper(executable, audio_path, output_prefix, language):
    command = [
        executable,
        "-m", str(WHISPER_MODEL),
        "-f", str(audio_path),
        "-l", language,
        "-t", "4",
        "-np",
        "-oj",
        "-of", str(output_prefix),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SpeechRecognitionError(
            "Speech recognition timed out. Try a shorter recording."
        ) from exc
    except OSError as exc:
        raise SpeechRecognitionError(
            f"Could not start Whisper: {exc}"
        ) from exc

    if result.returncode != 0:
        raise SpeechRecognitionError(
            f"Whisper failed: {result.stderr[-1000:]}"
        )

    json_path = Path(f"{output_prefix}.json")

    if not json_path.is_file():
        raise SpeechRecognitionError(
            "Whisper did not produce a transcription file."
        )

    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SpeechRecognitionError(
            "Could not read Whisper's transcription result."
        ) from exc


def extract_transcription(payload):
    segments = payload.get("transcription", [])

    transcript = " ".join(
        segment.get("text", "").strip()
        for segment in segments
        if segment.get("text", "").strip()
    ).strip()

    return transcript


def transcribe_audio(audio_data: bytes, filename: str) -> dict:
    if not audio_data:
        raise SpeechRecognitionError("The uploaded audio is empty.")

    if len(audio_data) > MAX_AUDIO_SIZE:
        raise SpeechRecognitionError("Audio file exceeds the 20 MB limit.")

    extension = Path(filename).suffix.lower()

    if extension not in SUPPORTED_FORMATS:
        raise SpeechRecognitionError(
            "Unsupported audio format. Use WAV, MP3, FLAC, or OGG."
        )

    if not WHISPER_MODEL.is_file():
        raise SpeechRecognitionError(
            f"Whisper model not found: {WHISPER_MODEL}"
        )

    executable = get_whisper_executable()

    with tempfile.TemporaryDirectory(prefix="jarvis_audio_") as temp_dir:
        temp_path = Path(temp_dir)
        audio_path = temp_path / f"input{extension}"

        audio_path.write_bytes(audio_data)

        # First pass: detect the spoken language.
        detection_prefix = temp_path / "detection"

        detection = run_whisper(
            executable,
            audio_path,
            detection_prefix,
            "auto",
        )

        detected_language = (
            detection.get("result", {}).get("language", "unknown")
        )

        if detected_language not in ALLOWED_LANGUAGES:
            raise SpeechRecognitionError(
                "JARVIS currently supports only English and Russian. "
                f"Detected language: {detected_language}."
            )

        # Second pass: transcribe using the detected language.
        transcription_prefix = temp_path / "transcription"

        result = run_whisper(
            executable,
            audio_path,
            transcription_prefix,
            detected_language,
        )

        transcript = extract_transcription(result)

        if not transcript:
            raise SpeechRecognitionError(
                "No speech was recognized. Please try again."
            )

        return {
            "text": transcript,
            "language": detected_language,
            "engine": "whisper.cpp",
            "model": WHISPER_MODEL.name,
        }
