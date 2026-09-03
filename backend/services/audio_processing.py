"""
Audio processing for the voice pipeline.

What changed and why
--------------------
The previous implementation ran, per 30 ms chunk: resample -> VAD -> discard if
below threshold -> normalise -> append. Three things went wrong with that.

1. Chunks scoring below the VAD threshold were *dropped*. Speech onsets ramp up
   over 50-100 ms, so the leading consonant of almost every utterance scored
   low and was thrown away before Whisper ever saw it. Pauses inside a sentence
   were excised too, which removes exactly the cues Whisper uses to punctuate.

2. Each chunk was normalised to a fixed RMS *independently*. A quiet 30 ms
   window was amplified as hard as a loud one, so the buffer handed to ASR had
   its dynamics pumped flat and its background noise boosted between words.

3. `scipy.signal.resample` is FFT-based and treats its input as periodic.
   Applied per chunk, 33 times a second, it stamped a discontinuity into every
   single chunk boundary.

Now: every sample is kept. VAD runs live but only records a speech/silence flag
per frame; it never deletes audio. On release the whole recording is resampled
in one pass (no internal boundaries), trimmed to the speech region with generous
padding on both ends, and normalised once as a single signal.
"""

import logging
import math
import queue
import threading

import numpy as np
import scipy.signal
import torch

logger = logging.getLogger(__name__)

# -- Config -----------------------------------------------------------------
TARGET_SAMPLE_RATE = 16000

# Silero expects exactly 512 samples per frame at 16 kHz. The old code padded a
# 480-sample frame with zeros, which is off-spec and biased every score low.
VAD_FRAME_SAMPLES = 512
VAD_THRESHOLD = 0.5

# Keep this much audio either side of the detected speech region. Cheap
# insurance: a little leading silence costs Whisper nothing, a clipped first
# syllable costs a wrong transcript.
EDGE_PADDING_SECONDS = 0.35

NORM_TARGET_RMS = 0.05
NORM_MAX_GAIN = 8.0  # never amplify near-silence into a wall of noise
PEAK_CEILING = 0.99

BUFFER_MIN_SPEECH_SECONDS = 0.2  # shorter than this is a cough or a stray click
BUFFER_MAX_SECONDS = 120

# -- Lazy model singleton ---------------------------------------------------
_vad_model = None
_models_lock = threading.Lock()


def _load_models():
    global _vad_model
    with _models_lock:
        if _vad_model is None:
            logger.info("Loading Silero VAD...")
            from silero_vad import load_silero_vad

            _vad_model = load_silero_vad()
            _vad_model.eval()
            logger.info("Silero VAD loaded.")


def _to_mono(chunk: np.ndarray, channels: int) -> np.ndarray:
    if channels > 1:
        usable = (len(chunk) // channels) * channels
        chunk = chunk[:usable].reshape(-1, channels).mean(axis=1)
    return chunk.astype(np.float32)


def _resample(audio: np.ndarray, src_rate: int) -> np.ndarray:
    """Rate-convert a whole signal at once.

    `resample_poly` is a polyphase FIR: no periodicity assumption, no edge
    discontinuity, and materially faster than the FFT path for the rational
    ratios sound cards actually produce (48k -> 16k is exactly 1/3).
    """
    if src_rate == TARGET_SAMPLE_RATE or len(audio) == 0:
        return audio.astype(np.float32)
    divisor = math.gcd(int(src_rate), TARGET_SAMPLE_RATE)
    up = TARGET_SAMPLE_RATE // divisor
    down = int(src_rate) // divisor
    return scipy.signal.resample_poly(audio, up, down).astype(np.float32)


def _vad_score(frame: np.ndarray) -> float:
    tensor = torch.from_numpy(frame).unsqueeze(0)
    with torch.no_grad():
        return _vad_model(tensor, TARGET_SAMPLE_RATE).item()


def _normalise(audio: np.ndarray) -> np.ndarray:
    """Bring the whole utterance to a target RMS, once, with a peak limiter."""
    if len(audio) == 0:
        return audio
    rms = float(np.sqrt(np.mean(audio**2)))
    if rms < 1e-9:
        return audio
    audio = audio * min(NORM_TARGET_RMS / rms, NORM_MAX_GAIN)
    peak = float(np.max(np.abs(audio)))
    if peak > PEAK_CEILING:
        audio = audio * (PEAK_CEILING / peak)
    return audio.astype(np.float32)


class AudioProcessor:
    """Buffers a push-to-talk recording and hands a clean utterance to ASR."""

    def __init__(self, raw_queue: queue.Queue, asr_queue: queue.Queue):
        self.raw_queue = raw_queue
        self.asr_queue = asr_queue

        self._recording = False
        self._src_rate: int | None = None

        # Everything captured, at the source rate, untouched.
        self._raw_buf: list[np.ndarray] = []
        # Live VAD bookkeeping. These decide *where* the speech is; they never
        # decide what gets kept.
        self._vad_residual = np.zeros(0, dtype=np.float32)
        self._speech_flags: list[bool] = []

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # -- Lifecycle ----------------------------------------------------------

    def start(self):
        _load_models()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="Thread-Processing", daemon=True)
        self._thread.start()
        logger.info("AudioProcessor thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("AudioProcessor stopped.")

    # -- Push-to-talk -------------------------------------------------------

    def on_key_press(self):
        self._raw_buf = []
        self._speech_flags = []
        self._vad_residual = np.zeros(0, dtype=np.float32)
        # Silero is an RNN: without a reset it carries hidden state from the
        # previous utterance into the first frames of this one.
        if _vad_model is not None:
            try:
                _vad_model.reset_states()
            except Exception:  # noqa: BLE001 - older builds lack the method
                pass
        self._recording = True

    def on_key_release(self):
        self._recording = False
        self._dispatch_buffer()

    # -- Pipeline -----------------------------------------------------------

    def _run(self):
        while not self._stop_event.is_set():
            try:
                raw_chunk, src_rate, channels = self.raw_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if not self._recording:
                continue

            try:
                self._src_rate = src_rate
                mono = _to_mono(raw_chunk, channels)
                self._raw_buf.append(mono)
                self._score_frames(mono, src_rate)
            except Exception as exc:  # noqa: BLE001
                logger.error("Processing error: %s", exc, exc_info=True)

    def _score_frames(self, mono_chunk: np.ndarray, src_rate: int) -> None:
        """Update the speech/silence flag track for the audio just captured.

        This path is allowed to be slightly lossy - per-chunk resampling
        artefacts do not bother a VAD - because its output is a set of booleans,
        not the audio that reaches Whisper.
        """
        resampled = _resample(mono_chunk, src_rate)
        self._vad_residual = np.concatenate([self._vad_residual, resampled])

        while len(self._vad_residual) >= VAD_FRAME_SAMPLES:
            frame = self._vad_residual[:VAD_FRAME_SAMPLES]
            self._vad_residual = self._vad_residual[VAD_FRAME_SAMPLES:]
            self._speech_flags.append(_vad_score(frame) >= VAD_THRESHOLD)

    def _speech_bounds(self, total_samples: int) -> tuple[int, int] | None:
        """Sample range covering the speech, padded, or None if nobody spoke."""
        speech_indices = [i for i, flag in enumerate(self._speech_flags) if flag]
        if not speech_indices:
            return None

        speech_seconds = len(speech_indices) * VAD_FRAME_SAMPLES / TARGET_SAMPLE_RATE
        if speech_seconds < BUFFER_MIN_SPEECH_SECONDS:
            logger.debug("Only %.2fs of speech detected - discarding.", speech_seconds)
            return None

        pad = int(EDGE_PADDING_SECONDS * TARGET_SAMPLE_RATE)
        start = max(0, speech_indices[0] * VAD_FRAME_SAMPLES - pad)
        end = min(total_samples, (speech_indices[-1] + 1) * VAD_FRAME_SAMPLES + pad)
        return start, end

    def _dispatch_buffer(self):
        if not self._raw_buf or self._src_rate is None:
            return

        raw = np.concatenate(self._raw_buf)
        self._raw_buf = []

        # One resample over the whole recording: no per-chunk edge artefacts.
        audio = _resample(raw, self._src_rate)

        bounds = self._speech_bounds(len(audio))
        if bounds is None:
            logger.debug("No speech in buffer - discarding.")
            return
        start, end = bounds
        audio = audio[start:end]

        max_samples = BUFFER_MAX_SECONDS * TARGET_SAMPLE_RATE
        if len(audio) > max_samples:
            # Keep the tail. If someone held the key through a long preamble,
            # the question they want answered is the part they just heard.
            logger.warning(
                "Recording is %.1fs - keeping the last %ds.",
                len(audio) / TARGET_SAMPLE_RATE,
                BUFFER_MAX_SECONDS,
            )
            audio = audio[-max_samples:]

        audio = _normalise(audio)

        logger.info("Dispatching %.2fs of audio to ASR.", len(audio) / TARGET_SAMPLE_RATE)
        try:
            self.asr_queue.put_nowait(audio)
        except queue.Full:
            logger.warning("ASR queue full - dropping buffer.")
