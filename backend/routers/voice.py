"""
Voice router - WebSocket interview mode, plus CV/JD PDF extraction.

Handshake: the socket opens, the server states which credentials it still
needs, and the client answers with `init`. Only then is the pipeline built.
Nothing touches the audio device until that point, so simply opening the page
no longer seizes the loopback stream.

Client -> server:
  {"action": "init", "credentials": {"groq_key": "...", "openai_key": "..."}}
  {"action": "start_recording"}
  {"action": "stop_recording"}
  {"action": "clear_memory"}
  {"action": "set_profile", "profile": {"job_title", "job_description", "cv_text"}}

Server -> client:
  {"type": "ready", "needs_groq_key": bool, "needs_llm_key": bool, ...}
  {"type": "status", "state": "idle|recording|transcribing|answering"}
  {"type": "transcription", "text": "..."}
  {"type": "token", "text": "..."}
  {"type": "done"}
  {"type": "error", "message": "..."}
  {"type": "profile_updated"}
"""

import asyncio
import io
import json
import logging
import queue

from fastapi import APIRouter, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from config import settings
from services.audio_capture import AudioCapture
from services.audio_processing import AudioProcessor
from services.credentials import (
    MissingCredentialError,
    resolve_groq_key,
    resolve_voice_llm_key,
)
from services.voice_llm import VoiceLLMResponder
from services.voice_transcription import Transcriber

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voice"])


def _extract_pdf_text(file_bytes: bytes) -> str:
    # pypdf is the maintained successor to PyPDF2, same API.
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = [text for page in reader.pages if (text := page.extract_text())]
    return "\n".join(pages)


@router.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)):
    """Extract text from an uploaded CV or job description."""
    if not (file.filename or "").lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "Only PDF files are supported."})

    content = await file.read()
    if len(content) > settings.max_pdf_bytes:
        return JSONResponse(
            status_code=413,
            content={"error": f"PDF exceeds {settings.max_pdf_bytes // (1024 * 1024)} MB limit."},
        )

    try:
        # Parsing is CPU-bound and synchronous. Left on the event loop, a big
        # PDF would stall every other request, live SSE streams included.
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _extract_pdf_text, content)
    except Exception as exc:  # noqa: BLE001
        logger.error("PDF parse error: %s", exc, exc_info=True)
        return JSONResponse(status_code=400, content={"error": "Could not read that PDF."})

    if not text.strip():
        return JSONResponse(
            status_code=422,
            content={"error": "No selectable text found. This looks like a scanned PDF."},
        )
    return {"text": text}


class VoiceSession:
    """The full voice pipeline for one WebSocket connection.

    Worker threads push messages onto an asyncio queue via
    `loop.call_soon_threadsafe`, which the send task drains.
    """

    def __init__(self):
        self._msg_queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self._raw_queue: queue.Queue = queue.Queue(maxsize=500)
        self._asr_queue: queue.Queue = queue.Queue(maxsize=5)
        self._llm_queue: queue.Queue = queue.Queue(maxsize=5)

        self._capture = AudioCapture(
            self._raw_queue,
            on_error_cb=lambda err: self._send({"type": "error", "message": err}),
        )
        self._processor = AudioProcessor(self._raw_queue, self._asr_queue)
        self._transcriber: Transcriber | None = None
        self._responder: VoiceLLMResponder | None = None
        self._running = False

    def initialize(
        self,
        loop: asyncio.AbstractEventLoop,
        msg_queue: asyncio.Queue,
        groq_key: str,
        llm_key: str,
    ):
        self._loop = loop
        self._msg_queue = msg_queue

        self._transcriber = Transcriber(
            asr_queue=self._asr_queue,
            llm_queue=self._llm_queue,
            api_key=groq_key,
            on_start_cb=lambda: self._send({"type": "status", "state": "transcribing"}),
            on_result_cb=lambda text: self._send({"type": "transcription", "text": text}),
            on_error_cb=lambda err: self._send({"type": "error", "message": err}),
        )

        self._responder = VoiceLLMResponder(
            llm_queue=self._llm_queue,
            on_token_cb=lambda tok: self._send({"type": "token", "text": tok}),
            on_answer_start_cb=lambda: self._send({"type": "status", "state": "answering"}),
            on_answer_end_cb=lambda: self._send({"type": "done"}),
            on_error_cb=lambda err: self._send({"type": "error", "message": err}),
            api_key=llm_key,
        )

    def start_pipeline(self):
        if self._running:
            return
        self._capture.start()
        self._processor.start()
        self._transcriber.start()
        self._responder.start()
        self._running = True
        logger.info("Voice pipeline started.")

    def stop_pipeline(self):
        if not self._running:
            return
        self._capture.stop()
        self._processor.stop()
        self._transcriber.stop()
        self._responder.stop()
        self._running = False
        logger.info("Voice pipeline stopped.")

    def start_recording(self):
        self._processor.on_key_press()
        self._send({"type": "status", "state": "recording"})

    def stop_recording(self):
        self._processor.on_key_release()
        self._send({"type": "status", "state": "transcribing"})

    def clear_memory(self):
        if self._responder:
            self._responder.clear_memory()
        self._send({"type": "status", "state": "idle"})

    def set_profile(self, profile: dict | None):
        if self._responder:
            self._responder.set_profile(profile)
        if self._transcriber:
            # The same profile also biases Whisper's vocabulary, so role-specific
            # jargon survives the transcript instead of being mangled before the
            # answering model ever sees it.
            self._transcriber.set_profile(profile)
        self._send({"type": "profile_updated"})

    def _send(self, msg: dict):
        """Thread-safe hand-off to the WebSocket send task."""
        if self._loop and self._msg_queue and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._msg_queue.put_nowait, msg)
            except RuntimeError:
                # Loop shut down while a worker thread was still running.
                pass


def _credentials_needed() -> dict:
    """Which keys this server cannot supply from its own configuration."""
    return {
        "needs_groq_key": not settings.groq_api_key,
        "needs_llm_key": not settings.voice_llm_key(),
        "llm_provider": settings.llm_provider,
        "allows_client_keys": settings.allow_client_keys,
    }


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("Voice WebSocket connected.")

    loop = asyncio.get_running_loop()
    msg_queue: asyncio.Queue = asyncio.Queue()
    session = VoiceSession()
    started = False

    try:
        # Tell the client what it must supply, then wait for `init`. The
        # pipeline - and the audio device it seizes - stays untouched until the
        # client has answered, so merely opening the page no longer takes over
        # the loopback stream.
        await websocket.send_json({"type": "ready", **_credentials_needed()})

        while not started:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("action") != "init":
                continue

            credentials = msg.get("credentials") or {}
            try:
                groq_key = resolve_groq_key(credentials.get("groq_key"))
                llm_key = resolve_voice_llm_key(credentials)
            except MissingCredentialError as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": (
                            "api_key_required" if exc.client_keys_allowed else "api_key_refused"
                        ),
                        "provider": exc.provider,
                        "message": (
                            f"An API key for {exc.provider} is required for voice mode."
                            if exc.client_keys_allowed
                            else "This server does not accept API keys from the browser."
                        ),
                    }
                )
                # Stay open: the user can enter a key and send `init` again.
                continue

            try:
                session.initialize(loop, msg_queue, groq_key, llm_key)
                # Loading the VAD model and opening a WASAPI stream both block.
                await loop.run_in_executor(None, session.start_pipeline)
            except ValueError as exc:
                # Configuration the user can act on: unknown provider, missing
                # optional package. Keep the socket open.
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to start voice pipeline: %s", exc, exc_info=True)
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Could not start audio capture. Check the backend log.",
                    }
                )
                await websocket.close()
                return

            started = True
            await websocket.send_json({"type": "status", "state": "idle"})

        async def _read_client():
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    continue

                action = msg.get("action")
                if action == "start_recording":
                    session.start_recording()
                elif action == "stop_recording":
                    session.stop_recording()
                elif action == "clear_memory":
                    session.clear_memory()
                elif action == "set_profile":
                    session.set_profile(msg.get("profile"))

        async def _send_to_client():
            while True:
                await websocket.send_json(await msg_queue.get())

        await asyncio.gather(_read_client(), _send_to_client())

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Voice WebSocket error: %s", exc, exc_info=True)
    finally:
        # Closing the audio device blocks; keep it off the event loop so a
        # shutdown cannot stall other connections.
        if started:
            await loop.run_in_executor(None, session.stop_pipeline)
