"""
Audio Processing Service
Consumes raw audio chunks and applies:
  1. Format conversion (any-rate stereo → 16kHz mono)
  2. Silero VAD (discard silence)
  3. RMS normalisation
"""

import threading
import queue
import logging
import numpy as np
import scipy.signal
import torch

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_SAMPLE_RATE = 16000
VAD_THRESHOLD = 0.50
VAD_WINDOW_SAMPLES = 512
NORM_TARGET_RMS = 0.05
BUFFER_MIN_SECONDS = 0.5
BUFFER_MAX_SECONDS = 60

# ── Lazy model singletons ────────────────────────────────────────────────────
_vad_model = None
_models_lock = threading.Lock()


def _load_models():
    global _vad_model

    with _models_lock:
        if _vad_model is None:
            logger.info("Loading Silero VAD…")
            from silero_vad import load_silero_vad
            _vad_model = load_silero_vad()
            _vad_model.eval()
            logger.info("Silero VAD loaded.")


def _to_16k_mono(chunk: np.ndarray, src_rate: int, src_channels: int) -> np.ndarray:
    if src_channels > 1:
        chunk = chunk.reshape(-1, src_channels)
        chunk = chunk.mean(axis=1)
    if src_rate != TARGET_SAMPLE_RATE:
        num_samples = int(len(chunk) * TARGET_SAMPLE_RATE / src_rate)
        chunk = scipy.signal.resample(chunk, num_samples)
    return chunk.astype(np.float32)


def _vad_score(chunk_16k: np.ndarray) -> float:
    window = VAD_WINDOW_SAMPLES
    if len(chunk_16k) < window:
        chunk_16k = np.pad(chunk_16k, (0, window - len(chunk_16k)))
    chunk_16k = chunk_16k[:window]
    tensor = torch.from_numpy(chunk_16k).unsqueeze(0)
    with torch.no_grad():
        score = _vad_model(tensor, TARGET_SAMPLE_RATE).item()
    return score


def _normalise(chunk: np.ndarray) -> np.ndarray:
    rms = np.sqrt(np.mean(chunk ** 2))
    if rms < 1e-9:
        return chunk
    return (chunk * (NORM_TARGET_RMS / rms)).astype(np.float32)


class AudioProcessor:
    """
    Consumes raw_queue, processes audio while recording,
    dispatches completed buffer to asr_queue on stop.
    """

    def __init__(self, raw_queue: queue.Queue, asr_queue: queue.Queue):
        self.raw_queue = raw_queue
        self.asr_queue = asr_queue
        self._recording = False
        self._clean_buf: list[np.ndarray] = []
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        _load_models()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="Thread-Processing", daemon=True
        )
        self._thread.start()
        logger.info("AudioProcessor thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("AudioProcessor stopped.")

    def on_key_press(self):
        self._clean_buf = []
        self._recording = True

    def on_key_release(self):
        self._recording = False
        self._dispatch_buffer()

    def _dispatch_buffer(self):
        if not self._clean_buf:
            return

        audio = np.concatenate(self._clean_buf)
        self._clean_buf = []
        duration = len(audio) / TARGET_SAMPLE_RATE

        if duration < BUFFER_MIN_SECONDS:
            logger.debug("Buffer too short (%.2fs) — discarding.", duration)
            return

        if duration > BUFFER_MAX_SECONDS:
            audio = audio[: int(BUFFER_MAX_SECONDS * TARGET_SAMPLE_RATE)]

        logger.info("Dispatching %.2fs of clean audio to ASR.", duration)
        try:
            self.asr_queue.put_nowait(audio)
        except queue.Full:
            logger.warning("ASR queue full — dropping buffer.")

    def _run(self):
        while not self._stop_event.is_set():
            try:
                raw_chunk, src_rate, src_ch = self.raw_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if not self._recording:
                continue

            try:
                chunk = _to_16k_mono(raw_chunk, src_rate, src_ch)
                score = _vad_score(chunk)
                if score < VAD_THRESHOLD:
                    continue
                chunk = _normalise(chunk)
                self._clean_buf.append(chunk)
            except Exception as exc:
                logger.error("Processing error: %s", exc, exc_info=True)
