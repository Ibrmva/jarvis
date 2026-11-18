
from contextlib import asynccontextmanager
from uuid import UUID
import logging

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.config import (
    JARVIS_NAME,
    MAX_HISTORY_MESSAGES,
    FAST_MODEL,
    ADVANCED_MODEL,
    PROJECT_ROOT,
)
from backend.database import (
    clear_history,
    get_history,
    get_display_history,
    initialize_database,
    save_message,
)
from backend.model_router import choose_model
from backend.ollama_client import (
    check_ollama,
    generate_reply,
    get_available_models,
    OllamaUnavailable,
)
from backend.speech_recognition import (
    transcribe_audio,
    SpeechRecognitionError,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis")

FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title=f"{JARVIS_NAME} Hybrid-Ready Assistant",
    version="0.3.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=12000)
    model_mode: str = Field(
        default="auto",
        pattern="^(auto|fast|advanced)$",
    )


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    model: str
    tier: str
    routing_reason: str


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
async def health():
    try:
        status = await check_ollama(FAST_MODEL, ADVANCED_MODEL)
        any_available = (
            status["fast_model_available"]
            or status["advanced_model_available"]
        )

        return {
            "status": "ok" if any_available else "models_missing",
            "assistant": JARVIS_NAME,
            **status,
            "speech_engine": "whisper.cpp",
        }

    except OllamaUnavailable as exc:
        return {
            "status": "offline",
            "assistant": JARVIS_NAME,
            "detail": str(exc),
            "speech_engine": "whisper.cpp",
        }


@app.get("/api/models")
async def models():
    try:
        available = await get_available_models()

    except OllamaUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    return {
        "models": [
            {
                "id": "auto",
                "label": "Auto — recommended",
                "available": True,
            },
            {
                "id": "fast",
                "label": f"Fast — {FAST_MODEL}",
                "available": FAST_MODEL in available,
            },
            {
                "id": "advanced",
                "label": f"Advanced — {ADVANCED_MODEL}",
                "available": ADVANCED_MODEL in available,
            },
        ]
    }


@app.get("/api/history/{session_id}")
async def history(session_id: str):
    try:
        UUID(session_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID.",
        ) from exc

    return {"messages": get_display_history(session_id)}


@app.post("/api/transcribe")
async def speech_to_text(audio: UploadFile = File(...)):
    filename = audio.filename or "recording.wav"

    try:
        audio_data = await audio.read()

        result = await run_in_threadpool(
            transcribe_audio,
            audio_data,
            filename,
        )

        logger.info(
            "Speech transcribed: language=%s characters=%s",
            result["language"],
            len(result["text"]),
        )

        return result

    except SpeechRecognitionError as exc:
        logger.warning("Speech recognition error: %s", exc)

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    finally:
        await audio.close()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        UUID(request.session_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID.",
        ) from exc

    user_message = request.message.strip()

    if not user_message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    try:
        available = await get_available_models()
        route = choose_model(user_message, request.model_mode)
        selected_model = route.model

        if selected_model not in available:
            if request.model_mode == "advanced":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"{selected_model} is not installed. "
                        f"Run: ollama pull {selected_model}"
                    ),
                )

            if FAST_MODEL in available:
                selected_model = FAST_MODEL
                route.tier = "fast"
                route.reason = (
                    f"Advanced model unavailable; fell back to {FAST_MODEL}"
                )

            else:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "No configured JARVIS model is installed. "
                        f"Run: ollama pull {FAST_MODEL}"
                    ),
                )

        save_message(request.session_id, "user", user_message)

        history_items = get_history(
            request.session_id,
            limit=MAX_HISTORY_MESSAGES,
        )

        reply = await generate_reply(history_items, selected_model)

        save_message(
            request.session_id,
            "assistant",
            reply,
            selected_model,
        )

        logger.info(
            "session=%s tier=%s model=%s reason=%s",
            request.session_id,
            route.tier,
            selected_model,
            route.reason,
        )

        return ChatResponse(
            session_id=request.session_id,
            reply=reply,
            model=selected_model,
            tier=route.tier,
            routing_reason=route.reason,
        )

    except OllamaUnavailable as exc:
        logger.warning("Model unavailable: %s", exc)

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc


@app.delete("/api/history/{session_id}")
async def delete_history(session_id: str):
    try:
        UUID(session_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID.",
        ) from exc

    clear_history(session_id)

    return {"status": "cleared"}
