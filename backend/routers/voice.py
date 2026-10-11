"""
Voice router - interview mode, plus CV/JD PDF extraction.

The browser captures the interviewer's audio itself (the meeting tab, the
system output, or a microphone) and records one clip per push-to-talk press.
Each clip is uploaded here and answered over SSE:

    POST /api/voice/answer   multipart: session_id, audio, profile (JSON, optional)

    {"type": "start"}
    {"type": "transcription", "text": "..."}
    {"type": "no_speech"}                         nothing intelligible was said
    {"type": "token", "text": "..."}
    {"type": "done"}
    {"type": "error", "code": "...", "message": "...", "provider": "..."}

Keys the server does not hold travel as X-Groq-Api-Key / X-OpenAI-Api-Key /
X-Anthropic-Api-Key headers. Conversation memory lives in the same per-user
session store the screen analysis uses, so follow-up questions resolve.

The previous design captured audio on the *server's* sound card (Windows
WASAPI loopback). That only ever worked with the backend on the user's own PC;
on a hosted server it would have heard nothing.
"""

import asyncio
import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from config import settings
from routers.common import SESSION_ID_PATTERN, SSE_HEADERS, Profile, require_session, sse
from services import pdf_text
from services.auth import AuthUser
from services.credentials import (
    MissingCredentialError,
    resolve_groq_key,
    resolve_voice_llm_key,
)
from services.rate_limit import rate_limited
from services.voice_llm import VoiceConfigError, build_messages, stream_answer
from services.voice_transcription import audio_extension, is_silence, transcribe

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voice"])

# Enough for any real CV or job description; bounds what one upload can make
# the server hold and send back.
MAX_PDF_TEXT_CHARS = 60_000
PDF_TIMEOUT_SECONDS = 20
# One extraction at a time across the server (each runs in its own process),
# on a dedicated thread so waiting never ties up the shared default executor,
# which asyncio also uses for DNS lookups. A short queue absorbs bursts;
# beyond it, callers are told to retry rather than piling up.
_PDF_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf")
_PDF_MAX_PENDING = 3
_pdf_pending = 0
_pdf_pending_lock = threading.Lock()

_SESSION_ID_RE = re.compile(SESSION_ID_PATTERN)
# The profile travels as a JSON form field; Profile truncates each value.
_MAX_PROFILE_FIELD_BYTES = 512 * 1024


@asynccontextmanager
async def _read_form(request: Request, max_fields: int, max_part_size: int):
    """Parse a multipart body, only ever after authentication has passed.

    As with JSON bodies (see routers.common.read_json), uploads are read inside
    the handler, so an anonymous caller is refused before anything is parsed
    or spooled to disk. Spooled files are closed on exit.
    """
    try:
        form = await request.form(
            max_files=1, max_fields=max_fields, max_part_size=max_part_size
        )
    except MultiPartException as exc:
        raise HTTPException(status_code=400, detail="Malformed upload.") from exc
    try:
        yield form
    finally:
        await form.close()


async def _extract_pdf(data: bytes) -> str:
    global _pdf_pending
    with _pdf_pending_lock:
        if _pdf_pending >= _PDF_MAX_PENDING:
            raise HTTPException(
                status_code=503,
                detail={"code": "server_busy", "message": "The server is busy. Try again shortly."},
                headers={"Retry-After": "10"},
            )
        _pdf_pending += 1
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _PDF_POOL,
            pdf_text.extract_text,
            data,
            settings.max_pdf_pages,
            MAX_PDF_TEXT_CHARS,
            PDF_TIMEOUT_SECONDS,
        )
    finally:
        with _pdf_pending_lock:
            _pdf_pending -= 1


# --- PDF extraction ----------------------------------------------------------


@router.post("/api/parse-pdf")
async def parse_pdf(
    request: Request,
    user: AuthUser = Depends(rate_limited("pdf", lambda: settings.rate_limit_pdf)),
):
    """Extract text from an uploaded CV or job description."""
    async with _read_form(request, max_fields=1, max_part_size=1024) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=422, detail="A PDF file is required.")
        content = await upload.read(settings.max_pdf_bytes + 1)

    if len(content) > settings.max_pdf_bytes:
        return JSONResponse(
            status_code=413,
            content={"error": f"PDF exceeds {settings.max_pdf_bytes // (1024 * 1024)} MB limit."},
        )
    # Check the content, not the filename or the client-declared type.
    if not content.startswith(b"%PDF-"):
        return JSONResponse(status_code=400, content={"error": "Only PDF files are supported."})

    try:
        text = await _extract_pdf(content)
    except pdf_text.PdfTimeout:
        logger.warning("PDF parse timed out for user %s", user.id)
        return JSONResponse(
            status_code=400,
            content={"error": "That PDF took too long to read. Try pasting the text instead."},
        )
    except pdf_text.PdfError as exc:
        logger.info("PDF parse failed: %s", exc)
        return JSONResponse(status_code=400, content={"error": "Could not read that PDF."})

    if not text.strip():
        return JSONResponse(
            status_code=422,
            content={"error": "No selectable text found. This looks like a scanned PDF."},
        )
    return {"text": text}


# --- Voice answers -----------------------------------------------------------


def _resolve_voice_keys(
    groq_key: str | None, openai_key: str | None, anthropic_key: str | None
) -> tuple[str, str]:
    """(transcription key, answer key), or a 401 naming every missing key."""
    client_keys = {"groq_key": groq_key, "openai_key": openai_key, "anthropic_key": anthropic_key}
    needed: list[str] = []
    asr_key = llm_key = ""
    refused = False

    try:
        asr_key = resolve_groq_key(groq_key)
    except MissingCredentialError as exc:
        needed.append("groq_key")
        refused = not exc.client_keys_allowed
    try:
        llm_key = resolve_voice_llm_key(client_keys)
    except MissingCredentialError as exc:
        needed.append(f"{settings.llm_provider}_key")
        refused = refused or not exc.client_keys_allowed

    if needed:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "api_key_refused" if refused else "api_key_required",
                "needed": sorted(set(needed)),
                "message": (
                    "This server does not accept API keys from the browser."
                    if refused
                    else "API keys are required for voice mode."
                ),
            },
        )
    return asr_key, llm_key


def _provider_error(exc: Exception, provider: str, request_id: str) -> dict:
    """Map an upstream failure to an event the browser can act on."""
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        logger.warning("[%s] %s key rejected", request_id, provider)
        return {
            "type": "error",
            "code": "invalid_api_key",
            "provider": provider,
            "message": f"Your {provider} API key was rejected. Check it and try again.",
        }
    if status == 429:
        logger.warning("[%s] %s rate limited", request_id, provider)
        return {
            "type": "error",
            "code": "rate_limited",
            "provider": provider,
            "message": f"The {provider} key is rate limited or out of quota.",
        }
    logger.error("[%s] %s call failed: %s", request_id, provider, exc, exc_info=True)
    return {
        "type": "error",
        "code": "voice_failed",
        "message": f"Could not answer that. Reference {request_id}.",
    }


@router.post("/api/voice/answer")
async def voice_answer(
    request: Request,
    x_groq_api_key: str | None = Header(default=None),
    x_openai_api_key: str | None = Header(default=None),
    x_anthropic_api_key: str | None = Header(default=None),
    user: AuthUser = Depends(rate_limited("voice", lambda: settings.rate_limit_voice)),
):
    """Transcribe one recorded question and stream the answer.

    Multipart fields: `session_id`, `audio` (the recording), optional `profile`
    (JSON).
    """
    # Keys first: a request that cannot be answered is refused before its
    # upload is parsed.
    asr_key, llm_key = _resolve_voice_keys(x_groq_api_key, x_openai_api_key, x_anthropic_api_key)

    async with _read_form(
        request, max_fields=2, max_part_size=_MAX_PROFILE_FIELD_BYTES
    ) as form:
        session_id = form.get("session_id")
        audio = form.get("audio")
        profile = form.get("profile")
        if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
            raise HTTPException(status_code=422, detail="A valid session_id is required.")
        if not isinstance(audio, UploadFile):
            raise HTTPException(status_code=422, detail="An audio recording is required.")
        session = require_session(session_id, user)

        extension = audio_extension(audio.content_type)
        if extension is None:
            raise HTTPException(status_code=415, detail="Unsupported audio format.")

        clip = await audio.read(settings.max_audio_bytes + 1)

    if len(clip) > settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="Recording is too long.")
    if len(clip) < 1024:
        raise HTTPException(status_code=400, detail="Recording is empty.")
    if profile is not None and not isinstance(profile, str):
        profile = None

    profile_data: dict | None = None
    if profile:
        try:
            profile_data = Profile.model_validate_json(profile).as_dict()
        except ValidationError:
            profile_data = None

    history = session.conversation_history()

    async def event_generator():
        request_id = uuid.uuid4().hex[:8]
        yield sse({"type": "start"})

        try:
            transcript = await transcribe(clip, extension, asr_key, profile_data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            yield sse(_provider_error(exc, "groq", request_id))
            return

        if is_silence(transcript):
            yield sse({"type": "no_speech"})
            yield sse({"type": "done"})
            return

        yield sse({"type": "transcription", "text": transcript})

        parts: list[str] = []
        try:
            async for token in stream_answer(
                build_messages(transcript, history, profile_data), llm_key
            ):
                parts.append(token)
                yield sse({"type": "token", "text": token})
        except asyncio.CancelledError:
            logger.info("[%s] client disconnected mid-answer", request_id)
            raise
        except VoiceConfigError as exc:
            # Operator configuration (unknown provider, missing package): the
            # message is ours, so it is safe and useful to show.
            logger.error("[%s] voice configuration error: %s", request_id, exc)
            yield sse({"type": "error", "code": "voice_failed", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            yield sse(_provider_error(exc, settings.llm_provider, request_id))
            return

        answer = "".join(parts)
        if answer.strip():
            session.add_exchange(transcript, answer)
        yield sse({"type": "done"})

    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/api/voice/reset/{session_id}")
async def voice_reset(
    session_id: str = Path(pattern=SESSION_ID_PATTERN),
    user: AuthUser = Depends(rate_limited("light", lambda: settings.rate_limit_light)),
):
    """Forget the conversation so far."""
    require_session(session_id, user).clear_conversation()
    return {"status": "ok"}
