"""
modules/processing.py
Thread 2 — Audio Processing Pipeline

Consumes raw chunks from RAW_QUEUE and applies the full pre-processing chain:
  1. Format conversion  (any-rate stereo float32 → 16 kHz mono float32)
  2. Silero VAD         (discard silence; only process confirmed speech)
  3. DeepFilterNet      (neural noise suppression)
  4. RMS normalisation  (stable volume for ASR)

When the hotkey is HELD:  clean chunks accumulate in an internal buffer.
When the hotkey is RELEASED: the full buffer is dispatched to ASR_QUEUE.
"""

import threading
import queue
import logging
import numpy as np
import scipy.signal
import torch

import config

logger = logging.getLogger(__name__)

# ── Lazy model singletons ────────────────────────────────────────────────────
_vad_model   = None
_vad_utils   = None
_df_model    = None
_df_state    = None
_df_info     = None
_models_lock = threading.Lock()


def _load_models():
    """Load Silero VAD and DeepFilterNet once (thread-safe)."""
    global _vad_model, _vad_utils, _df_model, _df_state, _df_info

    with _models_lock:
        if _vad_model is None:
            logger.info("Loading Silero VAD…")
            from silero_vad import load_silero_vad
            _vad_model = load_silero_vad()
            _vad_model.eval()
            # Provide the same utils interface expected downstream
            _vad_utils = (_vad_model,)
            logger.info("Silero VAD loaded.")

        if config.DENOISE_ENABLED and _df_model is None:
            try:
                logger.info("Loading DeepFilterNet…")
                from df import enhance, init_df
                _df_model, _df_state, _df_info = init_df()
                logger.info("DeepFilterNet loaded (sr=%d).", _df_info.sr)
            except Exception as exc:
                logger.warning(
                    "DeepFilterNet could not be loaded (%s). "
                    "Denoising disabled — install Rust toolchain + deepfilternet to enable.",
                    exc
                )


# ── Helper: format conversion ────────────────────────────────────────────────

def _to_16k_mono(chunk: np.ndarray, src_rate: int, src_channels: int) -> np.ndarray:
    """
    Convert raw loopback chunk to 16 kHz mono float32.
    chunk shape: (samples * channels,)  interleaved
    """
    # De-interleave channels
    if src_channels > 1:
        chunk = chunk.reshape(-1, src_channels)
        chunk = chunk.mean(axis=1)          # stereo → mono by averaging

    # Resample to 16 kHz
    if src_rate != config.TARGET_SAMPLE_RATE:
        num_samples = int(len(chunk) * config.TARGET_SAMPLE_RATE / src_rate)
        chunk = scipy.signal.resample(chunk, num_samples)

    return chunk.astype(np.float32)


# ── Helper: VAD ───────────────────────────────────────────────────────────────

def _vad_score(chunk_16k: np.ndarray) -> float:
    """Return Silero VAD probability (0.0 – 1.0) for a mono 16 kHz chunk."""
    # Silero expects tensors of exactly VAD_WINDOW_SAMPLES
    window = config.VAD_WINDOW_SAMPLES
    if len(chunk_16k) < window:
        chunk_16k = np.pad(chunk_16k, (0, window - len(chunk_16k)))
    chunk_16k = chunk_16k[:window]

    tensor = torch.from_numpy(chunk_16k).unsqueeze(0)
    with torch.no_grad():
        score = _vad_model(tensor, config.TARGET_SAMPLE_RATE).item()
    return score


# ── Helper: denoising ─────────────────────────────────────────────────────────

def _denoise(chunk_16k: np.ndarray) -> np.ndarray:
    """Run DeepFilterNet on a 16 kHz mono chunk. Returns denoised chunk."""
    if not config.DENOISE_ENABLED or _df_model is None:
        return chunk_16k
    try:
        from df import enhance
        import torchaudio

        # DeepFilterNet wants (1, samples) tensor at its native sr
        sr = _df_info.sr  # typically 48000 — resample if needed
        if sr != config.TARGET_SAMPLE_RATE:
            num = int(len(chunk_16k) * sr / config.TARGET_SAMPLE_RATE)
            audio_sr = scipy.signal.resample(chunk_16k, num)
        else:
            audio_sr = chunk_16k

        tensor = torch.from_numpy(audio_sr).unsqueeze(0)   # (1, samples)
        enhanced = enhance(_df_model, _df_state, tensor)   # (1, samples)
        enhanced_np = enhanced.squeeze(0).numpy()

        # Resample back to 16 kHz if needed
        if sr != config.TARGET_SAMPLE_RATE:
            enhanced_np = scipy.signal.resample(
                enhanced_np,
                len(chunk_16k)
            )
        return enhanced_np.astype(np.float32)
    except Exception as exc:
        logger.warning("DeepFilterNet error (skipping): %s", exc)
        return chunk_16k


# ── Helper: RMS normalisation ─────────────────────────────────────────────────

def _normalise(chunk: np.ndarray) -> np.ndarray:
    rms = np.sqrt(np.mean(chunk ** 2))
    if rms < 1e-9:
        return chunk
    return (chunk * (config.NORM_TARGET_RMS / rms)).astype(np.float32)


# ── Main processor class ─────────────────────────────────────────────────────

class AudioProcessor:
    """
    Consumes raw_queue, maintains a clean_buffer while recording flag is set,
    dispatches completed buffer to asr_queue on key-release.
    """

    def __init__(
        self,
        raw_queue:  queue.Queue,
        asr_queue:  queue.Queue,
    ):
        self.raw_queue    = raw_queue
        self.asr_queue    = asr_queue

        self._recording   = False          # controlled by hotkey callbacks
        self._clean_buf   : list[np.ndarray] = []
        self._stop_event  = threading.Event()
        self._thread      = threading.Thread(
            target=self._run, name="Thread-Processing", daemon=True
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        _load_models()
        self._thread.start()
        logger.info("AudioProcessor thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("AudioProcessor stopped.")

    def on_key_press(self):
        """Called by hotkey handler when Ctrl is pressed."""
        logger.debug("Key pressed → recording started.")
        self._clean_buf = []
        self._recording = True

    def on_key_release(self):
        """Called by hotkey handler when Ctrl is released."""
        logger.debug("Key released → dispatching buffer.")
        self._recording = False
        self._dispatch_buffer()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _dispatch_buffer(self):
        if not self._clean_buf:
            logger.debug("Buffer empty — nothing to dispatch.")
            return

        audio = np.concatenate(self._clean_buf)
        self._clean_buf = []

        duration = len(audio) / config.TARGET_SAMPLE_RATE

        if duration < config.BUFFER_MIN_SECONDS:
            logger.debug("Buffer too short (%.2fs) — discarding.", duration)
            return

        if duration > config.BUFFER_MAX_SECONDS:
            logger.warning("Buffer too long (%.1fs) — trimming.", duration)
            audio = audio[: int(config.BUFFER_MAX_SECONDS * config.TARGET_SAMPLE_RATE)]

        logger.info("Dispatching %.2fs of clean audio to ASR.", duration)
        try:
            self.asr_queue.put_nowait(audio)
        except queue.Full:
            logger.warning("ASR queue full — dropping buffer.")

    def _run(self):
        logger.info("Processing pipeline running…")
        while not self._stop_event.is_set():
            try:
                raw_chunk, src_rate, src_ch = self.raw_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            # Only do heavy work while key is held (saves CPU when idle)
            if not self._recording:
                continue

            try:
                # Step 1 — format conversion
                chunk = _to_16k_mono(raw_chunk, src_rate, src_ch)

                # Step 2 — VAD (discard silence)
                score = _vad_score(chunk)
                if score < config.VAD_THRESHOLD:
                    continue

                # Step 3 — noise suppression
                chunk = _denoise(chunk)

                # Step 4 — normalise
                chunk = _normalise(chunk)

                self._clean_buf.append(chunk)

            except Exception as exc:
                logger.error("Processing error: %s", exc, exc_info=True)

        logger.info("Processing thread exiting.")
