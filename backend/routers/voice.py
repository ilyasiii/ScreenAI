"""
Voice Router — WebSocket-based Interview Mode
Handles real-time audio capture, transcription, and LLM streaming via WebSocket.

Client messages:
  {"action": "start_recording"}
  {"action": "stop_recording"}
  {"action": "clear_memory"}
  {"action": "set_profile", "profile": {"job_title": "...", "job_description": "...", "cv_text": "..."}}

Server messages:
  {"type": "status", "state": "idle|recording|transcribing|answering"}
  {"type": "transcription", "text": "..."}
  {"type": "token", "text": "..."}
  {"type": "done"}
  {"type": "error", "message": "..."}
  {"type": "profile_updated"}
"""

import io
import json
import queue
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import JSONResponse

from services.audio_capture import AudioCapture
from services.audio_processing import AudioProcessor
from services.voice_transcription import Transcriber
from services.voice_llm import VoiceLLMResponder

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voice"])


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF file."""
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


@router.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)):
    """Parse a PDF file and return extracted text."""
    if not file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "Only PDF files are supported."})
    content = await file.read()
    try:
        text = _extract_pdf_text(content)
        return {"text": text}
    except Exception as exc:
        logger.error("PDF parse error: %s", exc)
        return JSONResponse(status_code=400, content={"error": f"Failed to parse PDF: {exc}"})


class VoiceSession:
    """
    Manages the full voice pipeline for one WebSocket connection.
    Thread-safe message queue bridges worker threads → async WebSocket send.
    """

    def __init__(self):
        self._msg_queue: asyncio.Queue = None
        self._loop: asyncio.AbstractEventLoop = None

        # Thread-safe queues between pipeline stages
        self._raw_queue = queue.Queue(maxsize=500)
        self._asr_queue = queue.Queue(maxsize=5)
        self._llm_queue = queue.Queue(maxsize=5)

        # Pipeline components
        self._capture = AudioCapture(self._raw_queue)
        self._processor = AudioProcessor(self._raw_queue, self._asr_queue)
        self._transcriber = None
        self._responder = None
        self._running = False

    def initialize(self, loop: asyncio.AbstractEventLoop, msg_queue: asyncio.Queue):
        """Set the event loop and message queue for thread→async bridging."""
        self._loop = loop
        self._msg_queue = msg_queue

        # Set up transcriber with callbacks
        self._transcriber = Transcriber(
            asr_queue=self._asr_queue,
            llm_queue=self._llm_queue,
            on_start_cb=lambda: self._send({"type": "status", "state": "transcribing"}),
            on_result_cb=lambda text: self._send({"type": "transcription", "text": text}),
            on_error_cb=lambda err: self._send({"type": "error", "message": err}),
        )

        # Set up LLM responder with callbacks
        self._responder = VoiceLLMResponder(
            llm_queue=self._llm_queue,
            on_token_cb=lambda tok: self._send({"type": "token", "text": tok}),
            on_answer_start_cb=lambda: self._send({"type": "status", "state": "answering"}),
            on_answer_end_cb=lambda: self._send({"type": "done"}),
            on_error_cb=lambda err: self._send({"type": "error", "message": err}),
        )

    def start_pipeline(self):
        """Start all background threads."""
        if self._running:
            return
        self._capture.start()
        self._processor.start()
        self._transcriber.start()
        self._responder.start()
        self._running = True
        logger.info("Voice pipeline started.")

    def stop_pipeline(self):
        """Stop all background threads."""
        if not self._running:
            return
        self._capture.stop()
        self._processor.stop()
        self._transcriber.stop()
        self._responder.stop()
        self._running = False
        logger.info("Voice pipeline stopped.")

    def start_recording(self):
        """Begin capturing audio into buffer."""
        self._processor.on_key_press()
        self._send({"type": "status", "state": "recording"})

    def stop_recording(self):
        """Stop capturing and dispatch buffer for transcription."""
        self._processor.on_key_release()
        self._send({"type": "status", "state": "transcribing"})

    def clear_memory(self):
        """Clear LLM conversation memory."""
        if self._responder:
            self._responder.clear_memory()
        self._send({"type": "status", "state": "idle"})

    def set_profile(self, profile: dict | None):
        """Update the LLM profile context."""
        if self._responder:
            self._responder.set_profile(profile)
        self._send({"type": "profile_updated"})

    def _send(self, msg: dict):
        """Thread-safe: push message to async queue."""
        if self._loop and self._msg_queue:
            self._loop.call_soon_threadsafe(self._msg_queue.put_nowait, msg)


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("Voice WebSocket connected.")

    loop = asyncio.get_running_loop()
    msg_queue: asyncio.Queue = asyncio.Queue()

    session = VoiceSession()

    try:
        session.initialize(loop, msg_queue)
    except Exception as exc:
        logger.error("Failed to initialize voice session: %s", exc, exc_info=True)
        await websocket.send_json({"type": "error", "message": f"Init failed: {exc}"})
        await websocket.close()
        return

    # Start pipeline in a thread to avoid blocking the event loop
    try:
        await asyncio.get_event_loop().run_in_executor(None, session.start_pipeline)
    except Exception as exc:
        logger.error("Failed to start voice pipeline: %s", exc, exc_info=True)
        await websocket.send_json({"type": "error", "message": f"Pipeline start failed: {exc}"})
        await websocket.close()
        return

    try:
        # Send initial idle status
        await websocket.send_json({"type": "status", "state": "idle"})

        # Two concurrent tasks:
        # 1. Read messages from client
        # 2. Forward messages from pipeline threads to client

        async def _read_client():
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    action = msg.get("action")
                    if action == "start_recording":
                        session.start_recording()
                    elif action == "stop_recording":
                        session.stop_recording()
                    elif action == "clear_memory":
                        session.clear_memory()
                    elif action == "set_profile":
                        session.set_profile(msg.get("profile"))
                except json.JSONDecodeError:
                    pass

        async def _send_to_client():
            while True:
                msg = await msg_queue.get()
                await websocket.send_json(msg)

        await asyncio.gather(_read_client(), _send_to_client())

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected.")
    except Exception as exc:
        logger.error("Voice WebSocket error: %s", exc)
    finally:
        session.stop_pipeline()
