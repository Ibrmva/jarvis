
import base64
import binascii
import json
import logging
import re
import subprocess
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import UUID
from typing import Literal

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    clean_assistant_text,
    generate_reply,
    get_available_models,
    OllamaUnavailable,
    resolve_website_url,
    stream_reply,
)
from backend.speech_recognition import (
    MAX_AUDIO_SIZE,
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


def is_same_origin(origin: str, host: str) -> bool:
    try:
        parsed_origin = urlsplit(origin)
    except ValueError:
        return False
    return (
        parsed_origin.scheme in {"http", "https"}
        and bool(parsed_origin.netloc)
        and not parsed_origin.path
        and not parsed_origin.query
        and not parsed_origin.fragment
        and parsed_origin.netloc.lower() == host.lower()
    )


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


@app.middleware("http")
async def add_security_headers(request, call_next):
    origin = request.headers.get("origin")
    content_length = request.headers.get("content-length")
    oversized_chat = False
    if request.url.path in {"/api/chat", "/api/chat/stream"} and content_length:
        try:
            oversized_chat = int(content_length) > 13_000_000
        except ValueError:
            oversized_chat = True
    if (
        origin
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and not is_same_origin(origin, request.headers.get("host", ""))
    ):
        response = JSONResponse(
            status_code=403,
            content={"detail": "Cross-origin requests are not allowed."},
        )
    elif oversized_chat:
        response = JSONResponse(
            status_code=413,
            content={"detail": "Chat request exceeds the 13 MB limit."},
        )
    else:
        response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(self), microphone=(self), geolocation=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net 'wasm-unsafe-eval'; "
        "style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "connect-src 'self' ws: wss: https://cdn.jsdelivr.net "
        "https://storage.googleapis.com; worker-src 'self' blob:; "
        "font-src 'self' data:",
    )
    return response


class ChatAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    kind: Literal["image", "text"]
    mime: str = Field(max_length=100)
    content: str = Field(max_length=11_200_000)
    thumbnail: str = Field(default="", max_length=128 * 1024)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(default="", max_length=12000)
    regenerate: bool = False
    reasoning: bool = False
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=5)
    model_mode: str = Field(
        default="auto",
        pattern="^(auto|fast|advanced)$",
    )

    @model_validator(mode="after")
    def validate_attachments(self):
        if sum(
            len(item.content) + len(item.thumbnail)
            for item in self.attachments
        ) > 12_000_000:
            raise ValueError("Attachments exceed the total request size limit.")

        image_bytes = 0
        text_bytes = 0
        thumbnail_bytes = 0
        for attachment in self.attachments:
            if (
                "/" in attachment.name
                or "\\" in attachment.name
                or any(ord(char) < 32 for char in attachment.name)
            ):
                raise ValueError("Attachment filenames must be plain filenames.")

            extension = "." + attachment.name.rsplit(".", 1)[-1].lower() if "." in attachment.name else ""
            if attachment.kind == "image":
                mime_extensions = {
                    "image/jpeg": {".jpg", ".jpeg"},
                    "image/png": {".png"},
                    "image/webp": {".webp"},
                }
                if extension not in mime_extensions.get(attachment.mime, set()):
                    raise ValueError("Only JPEG, PNG, and WebP images are supported.")
                try:
                    image = base64.b64decode(attachment.content, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("An attached image is not valid base64 data.") from exc
                valid_signature = (
                    (attachment.mime == "image/jpeg" and image.startswith(b"\xff\xd8\xff"))
                    or (attachment.mime == "image/png" and image.startswith(b"\x89PNG\r\n\x1a\n"))
                    or (
                        attachment.mime == "image/webp"
                        and len(image) >= 12
                        and image.startswith(b"RIFF")
                        and image[8:12] == b"WEBP"
                    )
                )
                if not valid_signature:
                    raise ValueError("The image content does not match its file type.")
                image_bytes += len(image)
                if attachment.thumbnail:
                    try:
                        thumbnail = base64.b64decode(
                            attachment.thumbnail,
                            validate=True,
                        )
                    except (binascii.Error, ValueError) as exc:
                        raise ValueError("An image preview is not valid base64 data.") from exc
                    if not thumbnail.startswith(b"\xff\xd8\xff"):
                        raise ValueError("Image previews must be JPEG thumbnails.")
                    thumbnail_bytes += len(thumbnail)
            else:
                if attachment.thumbnail:
                    raise ValueError("Text documents cannot have image previews.")
                if extension not in {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".xml", ".log"}:
                    raise ValueError("Only plain-text documents are supported.")
                if "\0" in attachment.content:
                    raise ValueError("Text documents must contain plain text.")
                text_bytes += len(attachment.content.encode("utf-8"))

        if image_bytes > 8 * 1024 * 1024:
            raise ValueError("Attached images may total at most 8 MB.")
        if text_bytes > 500 * 1024:
            raise ValueError("Text documents may total at most 500 KB.")
        if thumbnail_bytes > 480 * 1024:
            raise ValueError("Image previews exceed the total size limit.")
        return self


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    thinking: str = ""
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
        audio_data = await audio.read(MAX_AUDIO_SIZE + 1)
        if len(audio_data) > MAX_AUDIO_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Audio file exceeds the 20 MB limit.",
            )

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
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host", "")
    if origin and not is_same_origin(origin, host):
        await websocket.close(
            code=1008,
            reason="Cross-origin WebSocket connections are not allowed.",
        )
        return

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
    return await _chat(request, streaming=False)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    result = await _chat(request, streaming=True)
    if isinstance(result, ChatResponse):
        async def action_events():
            yield json.dumps({"type": "content", "text": result.reply}) + "\n"
            yield json.dumps({
                "type": "done",
                "reply": result.reply,
                "thinking": result.thinking,
                "model": result.model,
                "tier": result.tier,
                "routing_reason": result.routing_reason,
            }) + "\n"

        return StreamingResponse(action_events(), media_type="application/x-ndjson")
    return result


async def _chat(
    request: ChatRequest,
    streaming: bool,
) -> ChatResponse | StreamingResponse:
    try:
        UUID(request.session_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID.",
        ) from exc

    user_message = request.message.strip()
    if not user_message and not request.attachments:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )
    if not user_message:
        user_message = "Please analyze the attached file(s)."

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
        save_message(
            request.session_id,
            "user",
            user_message,
            attachments=[
                attachment.model_dump()
                for attachment in request.attachments
            ],
        )

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
        effective_mode = "advanced" if request.reasoning else request.model_mode
        route = choose_model(user_message, effective_mode)
        selected_model = route.model

        if selected_model not in available:
            if request.model_mode == "advanced" or request.reasoning:
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

        if streaming:
            async def stream_events():
                reply_parts: list[str] = []
                thinking_parts: list[str] = []
                yield json.dumps({
                    "type": "meta",
                    "model": selected_model,
                    "tier": route.tier,
                    "routing_reason": route.reason,
                }) + "\n"
                try:
                    async for event in stream_reply(
                        history_items,
                        selected_model,
                        reasoning=request.reasoning,
                    ):
                        text = event["text"]
                        if event["type"] == "thinking":
                            thinking_parts.append(text)
                        else:
                            reply_parts.append(text)
                        yield json.dumps(event, ensure_ascii=False) + "\n"

                    reply = clean_assistant_text("".join(reply_parts))
                    thinking = clean_assistant_text("".join(thinking_parts))
                    if not reply and thinking:
                        reply = thinking
                        yield json.dumps({
                            "type": "content",
                            "text": reply,
                        }, ensure_ascii=False) + "\n"
                    if not reply:
                        raise OllamaUnavailable(
                            "The local model returned an empty response."
                        )

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
                    yield json.dumps({
                        "type": "done",
                        "reply": reply,
                        "thinking": thinking,
                        "model": selected_model,
                        "tier": route.tier,
                        "routing_reason": route.reason,
                    }, ensure_ascii=False) + "\n"
                except OllamaUnavailable as exc:
                    logger.warning("Model unavailable: %s", exc)
                    yield json.dumps({"type": "error", "detail": str(exc)}) + "\n"
                except HTTPException as exc:
                    yield json.dumps({
                        "type": "error",
                        "detail": str(exc.detail),
                    }) + "\n"

            return StreamingResponse(
                stream_events(),
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        generated = await generate_reply(
            history_items,
            selected_model,
            reasoning=request.reasoning,
            return_thinking=True,
        )
        reply, thinking = generated

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
            thinking=thinking,
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
