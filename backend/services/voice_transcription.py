"""
Transcription - Groq-hosted whisper-large-v3.

Reads a clean utterance off the ASR queue, encodes it as 16-bit PCM WAV in
memory, transcribes, and puts the text on the LLM queue.

Accuracy note: Whisper accepts a `prompt` that biases decoding toward a
vocabulary. Feeding it the target job title and a handful of terms lifted from
the job description is what makes it write "Kubernetes" and "PostgreSQL"
instead of "Cubernetties" and "post-gress" - which matters, because the LLM
downstream only ever sees the transcript.
"""

import io
import logging
import queue
import re
import threading
import wave

import numpy as np
from groq import Groq

from config import settings

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
# Whisper's prompt window is small; overrunning it silently truncates.
MAX_PROMPT_CHARS = 800

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{2,}")
_STOPWORDS = {
    "and", "the", "for", "with", "you", "your", "our", "are", "will", "have",
    "has", "this", "that", "from", "they", "their", "who", "what", "which",
    "role", "team", "work", "working", "years", "experience", "ability",
    "strong", "including", "such", "help", "must", "should", "would", "can",
    "job", "candidate", "position", "company", "about", "requirements",
}


def _numpy_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return buf.getvalue()


def build_asr_prompt(profile: dict | None) -> str:
    """A short vocabulary hint for Whisper, derived from the user's profile."""
    if not profile:
        return ""

    fragments: list[str] = []
    job_title = (profile.get("job_title") or "").strip()
    if job_title:
        fragments.append(f"A technical interview for a {job_title} position.")

    # Distinctive terms from the job description: capitalised names and
    # tech-shaped tokens are the ones Whisper is most likely to mangle.
    source = f"{profile.get('job_description') or ''} {profile.get('cv_text') or ''}"
    seen: dict[str, None] = {}
    for match in _WORD_RE.findall(source):
        if match.lower() in _STOPWORDS:
            continue
        # Keep things that look like proper nouns or tech tokens.
        if match[0].isupper() or any(c in match for c in "+#./-"):
            seen.setdefault(match, None)
        if len(seen) >= 40:
            break

    if seen:
        fragments.append("Terms that may come up: " + ", ".join(seen) + ".")

    return " ".join(fragments)[:MAX_PROMPT_CHARS]


class Transcriber:
    """ASR worker thread. Fires callbacks for status and results."""

    def __init__(
        self,
        asr_queue: queue.Queue,
        llm_queue: queue.Queue,
        api_key: str,
        on_start_cb=None,
        on_result_cb=None,
        on_error_cb=None,
    ):
        self.asr_queue = asr_queue
        self.llm_queue = llm_queue
        self.on_start_cb = on_start_cb
        self.on_result_cb = on_result_cb
        self.on_error_cb = on_error_cb

        # Resolved by the caller: the server's key when one is configured,
        # otherwise the key the user supplied in the browser.
        if not api_key:
            raise ValueError("No Groq API key available for transcription.")
        self._client = Groq(api_key=api_key)

        self._prompt = ""
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def set_profile(self, profile: dict | None):
        self._prompt = build_asr_prompt(profile)
        if self._prompt:
            logger.info("ASR vocabulary hint set (%d chars).", len(self._prompt))

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="Thread-ASR", daemon=True)
        self._thread.start()
        logger.info("Transcriber thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("Transcriber stopped.")

    def _transcribe(self, audio: np.ndarray) -> str:
        kwargs = {
            "file": ("audio.wav", _numpy_to_wav_bytes(audio, TARGET_SAMPLE_RATE), "audio/wav"),
            "model": settings.asr_model,
            "response_format": "text",
            # Greedy decoding. Whisper's default samples, which on short
            # utterances is where its hallucinated filler comes from.
            "temperature": 0.0,
        }
        if settings.asr_language:
            kwargs["language"] = settings.asr_language
        if self._prompt:
            kwargs["prompt"] = self._prompt

        response = self._client.audio.transcriptions.create(**kwargs)
        text = response if isinstance(response, str) else response.text
        return text.strip()

    def _run(self):
        while not self._stop_event.is_set():
            try:
                audio = self.asr_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            logger.info("Transcribing %.2fs of audio...", len(audio) / TARGET_SAMPLE_RATE)
            if self.on_start_cb:
                self.on_start_cb()

            try:
                transcript = self._transcribe(audio)
                if not transcript:
                    logger.warning("Empty transcript - skipping.")
                    continue

                logger.info("Transcript: %s", transcript)
                if self.on_result_cb:
                    self.on_result_cb(transcript)
                try:
                    self.llm_queue.put_nowait(transcript)
                except queue.Full:
                    logger.warning("LLM queue full - dropping transcript.")
            except Exception as exc:  # noqa: BLE001
                logger.error("ASR error: %s", exc, exc_info=True)
                if self.on_error_cb:
                    self.on_error_cb("Transcription failed. Check the backend log.")
