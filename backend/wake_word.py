from threading import Lock


class WakeWordError(RuntimeError):
    pass


_model = None
_model_lock = Lock()
_prediction_lock = Lock()


def load_wake_word_model():
    global _model

    with _model_lock:
        if _model is not None:
            return _model

        try:
            import openwakeword
            import requests
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            download_models(model_names=["hey_jarvis"])
            _model = Model(
                wakeword_models=["hey_jarvis"],
                inference_framework="onnx",
            )
        except ImportError as exc:
            raise WakeWordError(
                "Wake-word detection requires openwakeword and ONNX Runtime. "
                "Install the project requirements and restart JARVIS."
            ) from exc
        except (OSError, RuntimeError, ValueError, requests.RequestException) as exc:
            raise WakeWordError(
                "Could not load the local Hey JARVIS wake-word model. "
                "Check your network connection for the first model download "
                "and ensure openwakeword is installed."
            ) from exc

        return _model


def detect_wake_word(frame: bytes) -> bool:
    if not frame or len(frame) % 2:
        raise ValueError("Wake-word audio must contain 16-bit PCM samples.")

    try:
        import numpy as np
    except ImportError as exc:
        raise WakeWordError("Wake-word detection requires NumPy.") from exc

    model = load_wake_word_model()
    samples = np.frombuffer(frame, dtype=np.int16)

    try:
        with _prediction_lock:
            scores = model.predict(samples)
    except (OSError, RuntimeError, ValueError) as exc:
        raise WakeWordError("Local wake-word detection failed.") from exc

    return any(
        name.startswith("hey_jarvis") and score >= 0.5
        for name, score in scores.items()
    )


def reset_wake_word_model() -> None:
    with _prediction_lock:
        if _model is not None:
            _model.reset()
