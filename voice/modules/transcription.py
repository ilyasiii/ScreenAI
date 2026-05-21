"""
modules/transcription.py
Thread 3 — ASR via Groq API (whisper-large-v3)

Consumes clean audio buffers from ASR_QUEUE.
Encodes each buffer as a 16-bit PCM WAV in memory (no disk I/O).
Sends to Groq's whisper-large-v3 endpoint.
Places the resulting transcript string onto LLM_QUEUE.
"""

import io
import wave
import queue
import threading
import logging
import numpy as np

from groq import Groq
from dotenv import load_dotenv
import os

import config

load_dotenv()
logger = logging.getLogger(__name__)


def _numpy_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """
    Encode a float32 mono numpy array as 16-bit PCM WAV bytes in memory.
    Groq API requires WAV/MP3/FLAC — WAV is fastest (no encoding overhead).
    """
    # Clip to [-1, 1] then scale to int16
    audio_clipped = np.clip(audio, -1.0, 1.0)
    audio_int16   = (audio_clipped * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)          # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())

    buf.seek(0)
    return buf.read()


class Transcriber:
    """
    Reads clean audio from asr_queue, transcribes via Groq whisper-large-v3,
    places transcript text onto llm_queue.
    Fires an optional callback so the UI can show 'Transcribing…' state.
    """

    def __init__(
        self,
        asr_queue:  queue.Queue,
        llm_queue:  queue.Queue,
        on_start_cb   = None,   # called when transcription begins
        on_result_cb  = None,   # called with (transcript: str)
        on_error_cb   = None,   # called with (error: str)
    ):
        self.asr_queue    = asr_queue
        self.llm_queue    = llm_queue
        self.on_start_cb  = on_start_cb
        self.on_result_cb = on_result_cb
        self.on_error_cb  = on_error_cb

        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY not set. Add it to your .env file."
            )
        self._client = Groq(api_key=api_key)

        self._stop_event = threading.Event()
        self._thread     = threading.Thread(
            target=self._run, name="Thread-ASR", daemon=True
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self._thread.start()
        logger.info("Transcriber thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("Transcriber stopped.")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _transcribe(self, audio: np.ndarray) -> str:
        wav_bytes = _numpy_to_wav_bytes(audio, config.TARGET_SAMPLE_RATE)

        kwargs = dict(
            file      = ("audio.wav", wav_bytes, "audio/wav"),
            model     = config.GROQ_ASR_MODEL,
            response_format = "text",
        )
        if config.ASR_LANGUAGE:
            kwargs["language"] = config.ASR_LANGUAGE

        response = self._client.audio.transcriptions.create(**kwargs)

        # response is a plain string when response_format="text"
        transcript = response.strip() if isinstance(response, str) else response.text.strip()
        return transcript

    def _run(self):
        logger.info("Transcriber waiting for audio buffers…")
        while not self._stop_event.is_set():
            try:
                audio = self.asr_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            duration = len(audio) / config.TARGET_SAMPLE_RATE
            logger.info("Transcribing %.2fs of audio…", duration)

            if self.on_start_cb:
                self.on_start_cb()

            try:
                transcript = self._transcribe(audio)
                logger.info("Transcript: %s", transcript)

                if not transcript:
                    logger.warning("Empty transcript returned — skipping.")
                    continue

                if self.on_result_cb:
                    self.on_result_cb(transcript)

                try:
                    self.llm_queue.put_nowait(transcript)
                except queue.Full:
                    logger.warning("LLM queue full — dropping transcript.")

            except Exception as exc:
                logger.error("ASR error: %s", exc, exc_info=True)
                if self.on_error_cb:
                    self.on_error_cb(str(exc))

        logger.info("Transcriber thread exiting.")
