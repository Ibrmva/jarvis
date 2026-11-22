
from contextlib import asynccontextmanager
from uuid import UUID
import logging
import re
import subprocess

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
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
    get_latest_exchange,
    get_recent_sessions,
    initialize_database,
    replace_latest_assistant,
    save_message,
)
from backend.model_router import choose_model
from backend.ollama_client import (
    check_ollama,
    generate_reply,
    get_available_models,
    OllamaUnavailable,
    resolve_website_url,
)
from backend.speech_recognition import (
    transcribe_audio,
    SpeechRecognitionError,
)
from backend.command_executor import (
    execute_command,
    extract_website_open_target,
    open_website,
    validate_website_url,
)
from backend.wake_word import (
    WakeWordError,
    detect_wake_word,
    load_wake_word_model,
    reset_wake_word_model,
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
    version="0.4.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=12000)
    regenerate: bool = False
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


@app.get("/api/sessions")
async def recent_sessions():
    return {"sessions": get_recent_sessions()}


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


@app.websocket("/api/wake-word")
async def wake_word(websocket: WebSocket):
    await websocket.accept()
    model_loaded = False

    try:
        await run_in_threadpool(load_wake_word_model)
        model_loaded = True
        await websocket.send_json({"type": "ready"})

        while True:
            frame = await websocket.receive_bytes()
            if len(frame) > 8192:
                await websocket.close(code=1009, reason="Audio frame is too large.")
                return
            if not frame or len(frame) % 2:
                await websocket.close(code=1003, reason="Expected 16-bit PCM audio.")
                return

            detected = await run_in_threadpool(detect_wake_word, frame)
            if detected:
                await websocket.send_json({"type": "wake"})
                await websocket.close()
                return
    except WebSocketDisconnect:
        return
    except WakeWordError as exc:
        logger.warning("Wake-word detector error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=1011)
        except RuntimeError:
            pass
    finally:
        if model_loaded:
            await run_in_threadpool(reset_wake_word_model)


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

    previous_exchange = None
    if request.regenerate:
        previous_exchange = get_latest_exchange(request.session_id)
        if previous_exchange is None or previous_exchange["user_content"] != user_message:
            raise HTTPException(
                status_code=409,
                detail="Only the latest assistant response can be regenerated.",
            )
        if previous_exchange["assistant_model"] == "macOS":
            raise HTTPException(
                status_code=409,
                detail="macOS actions cannot be repeated with regenerate.",
            )
    else:
        save_message(request.session_id, "user", user_message)

    # Execute recognized macOS actions before calling the AI model.
    command_result = None
    website_target = None
    if not request.regenerate:
        command_result = await run_in_threadpool(execute_command, user_message)
        if command_result is None:
            website_target = extract_website_open_target(user_message)

    if command_result is not None:
        reply = command_result["reply"]

        save_message(
            request.session_id,
            "assistant",
            reply,
            "macOS",
        )

        logger.info(
            "macOS action: %s",
            command_result["action"],
        )

        return ChatResponse(
            session_id=request.session_id,
            reply=reply,
            model="macOS",
            tier="action",
            routing_reason=command_result["action"],
        )

    # Normal AI conversation.
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

        if website_target:
            resolved_url = validate_website_url(
                await resolve_website_url(website_target, selected_model)
            )
            if resolved_url:
                try:
                    await run_in_threadpool(open_website, resolved_url)
                    russian = bool(re.search(r"[А-Яа-яЁё]", user_message))
                    reply = (
                        f"Открываю {website_target}."
                        if russian
                        else f"Opening {website_target}."
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    logger.warning("Could not open website %s: %s", resolved_url, exc)
                    reply = "I identified the website, but could not open it."

                save_message(request.session_id, "assistant", reply, "macOS")
                return ChatResponse(
                    session_id=request.session_id,
                    reply=reply,
                    model="macOS",
                    tier="action",
                    routing_reason="open_website",
                )

        history_items = get_history(
            request.session_id,
            limit=MAX_HISTORY_MESSAGES,
            exclude_message_id=(
                previous_exchange["assistant_id"] if previous_exchange else None
            ),
        )

        reply = await generate_reply(history_items, selected_model)

        if previous_exchange:
            replaced = replace_latest_assistant(
                request.session_id,
                previous_exchange["assistant_id"],
                reply,
                selected_model,
            )
            if not replaced:
                raise HTTPException(
                    status_code=409,
                    detail="Conversation changed before the response could be regenerated.",
                )
        else:
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
