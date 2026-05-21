"""
Audio Capture Service — WASAPI Loopback
Captures system audio (what's playing through speakers/headphones).
Adapted for use within FastAPI backend.
"""

import time
import threading
import queue
import logging
import numpy as np

import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)

LOOPBACK_CHUNK_MS = 30


class AudioCapture:
    """
    Captures system audio via WASAPI loopback.
    Runs in its own daemon thread.
    Produces raw numpy chunks onto raw_queue.
    """

    def __init__(self, raw_queue: queue.Queue):
        self.raw_queue = raw_queue
        self._stop_event = threading.Event()
        self._thread = None
        self._pa = None
        self._stream = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="Thread-Capture", daemon=True
        )
        self._thread.start()
        logger.info("AudioCapture thread started.")

    def stop(self):
        self._stop_event.set()
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
        self._pa = None
        self._stream = None
        logger.info("AudioCapture stopped.")

    def _get_loopback_device(self):
        """Return the WASAPI loopback device info for the default output."""
        # PyAudioWPatch provides a dedicated method for getting loopback devices
        try:
            # Use the built-in method to get loopback device for default speakers
            default_speakers = self._pa.get_default_wasapi_loopback()
            if default_speakers:
                return default_speakers
        except Exception as exc:
            logger.warning("get_default_wasapi_loopback failed: %s", exc)

        # Fallback: manually search
        wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out_idx = wasapi_info["defaultOutputDevice"]
        device_info = self._pa.get_device_info_by_index(default_out_idx)

        if not device_info.get("isLoopbackDevice", False):
            for i in range(self._pa.get_device_count()):
                d = self._pa.get_device_info_by_index(i)
                if d.get("isLoopbackDevice", False) and d["name"].startswith(
                    device_info["name"][:20]
                ):
                    return d
            # Fallback: try any loopback device
            for i in range(self._pa.get_device_count()):
                d = self._pa.get_device_info_by_index(i)
                if d.get("isLoopbackDevice", False):
                    logger.info("Using fallback loopback device: %s", d["name"])
                    return d
            raise RuntimeError(
                "Could not find a WASAPI loopback device. "
                "Make sure your headphones/speakers are set as the default playback device."
            )
        return device_info

    def _run(self):
        self._pa = pyaudio.PyAudio()

        try:
            device_info = self._get_loopback_device()
        except RuntimeError as exc:
            logger.error(str(exc))
            return

        sample_rate = int(device_info["defaultSampleRate"])
        channels = int(device_info["maxInputChannels"])
        chunk_size = int(sample_rate * LOOPBACK_CHUNK_MS / 1000)

        logger.info(
            "Loopback device: %s | %d Hz | %d ch | chunk=%d samples",
            device_info["name"], sample_rate, channels, chunk_size,
        )

        def _callback(in_data, frame_count, time_info, status):
            if self._stop_event.is_set():
                return (None, pyaudio.paAbort)
            try:
                # Convert from int16 to float32 normalized
                chunk = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                if not self.raw_queue.full():
                    self.raw_queue.put_nowait((chunk, sample_rate, channels))
            except Exception as exc:
                logger.warning("Capture callback error: %s", exc)
            return (None, pyaudio.paContinue)

        # Retry opening the stream a few times (WASAPI can be finicky)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=sample_rate,
                    input=True,
                    input_device_index=device_info["index"],
                    frames_per_buffer=chunk_size,
                    stream_callback=_callback,
                )
                break
            except OSError as exc:
                logger.warning(
                    "Failed to open loopback stream (attempt %d/%d): %s",
                    attempt + 1, max_retries, exc,
                )
                if attempt < max_retries - 1:
                    time.sleep(1.0)
                else:
                    logger.error(
                        "Could not open WASAPI loopback stream after %d attempts. "
                        "Audio capture unavailable.", max_retries
                    )
                    return

        self._stream.start_stream()
        logger.info("Loopback stream active.")

        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=0.1)

        logger.info("Capture thread exiting.")
