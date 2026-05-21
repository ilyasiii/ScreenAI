"""
Voice Transcription Service — Groq Whisper
Consumes clean audio buffers from ASR queue.
Encodes as 16-bit PCM WAV in memory.
Sends to Groq's whisper-large-v3 endpoint.
"""

import io
import wave
import queue
import threading
import logging
import os
import numpy as np

from groq import Groq

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
GROQ_ASR_MODEL = "whisper-large-v3"
ASR_LANGUAGE = "en"


def _numpy_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    audio_clipped = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio_clipped * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    buf.seek(0)
    return buf.read()


class Transcriber:
    """
    Reads clean audio from asr_queue, transcribes via Groq whisper-large-v3,
    places transcript onto llm_queue. Fires callbacks for status updates.
    """

    def __init__(
        self,
        asr_queue: queue.Queue,
        llm_queue: queue.Queue,
        on_start_cb=None,
        on_result_cb=None,
        on_error_cb=None,
    ):
        self.asr_queue = asr_queue
        self.llm_queue = llm_queue
        self.on_start_cb = on_start_cb
        self.on_result_cb = on_result_cb
        self.on_error_cb = on_error_cb

        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in backend .env file.")
        self._client = Groq(api_key=api_key)

        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="Thread-ASR", daemon=True
        )
        self._thread.start()
        logger.info("Transcriber thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("Transcriber stopped.")

    def _transcribe(self, audio: np.ndarray) -> str:
        wav_bytes = _numpy_to_wav_bytes(audio, TARGET_SAMPLE_RATE)
        kwargs = dict(
            file=("audio.wav", wav_bytes, "audio/wav"),
            model=GROQ_ASR_MODEL,
            response_format="text",
        )
        if ASR_LANGUAGE:
            kwargs["language"] = ASR_LANGUAGE
        response = self._client.audio.transcriptions.create(**kwargs)
        transcript = response.strip() if isinstance(response, str) else response.text.strip()
        return transcript

    def _run(self):
        while not self._stop_event.is_set():
            try:
                audio = self.asr_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            duration = len(audio) / TARGET_SAMPLE_RATE
            logger.info("Transcribing %.2fs of audio…", duration)

            if self.on_start_cb:
                self.on_start_cb()

            try:
                transcript = self._transcribe(audio)
                if not transcript:
                    logger.warning("Empty transcript — skipping.")
                    continue
                logger.info("Transcript: %s", transcript)
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
