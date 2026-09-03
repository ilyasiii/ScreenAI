"""
System audio capture via WASAPI loopback - records what is playing through the
speakers, which is how the interviewer's side of the call is heard.

Windows only: PyAudioWPatch is the Windows-specific PortAudio fork that exposes
loopback devices.
"""

import logging
import queue
import threading
import time

import numpy as np
import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)

LOOPBACK_CHUNK_MS = 30
MAX_OPEN_RETRIES = 3


class AudioCapture:
    """Produces raw numpy chunks onto raw_queue from its own daemon thread."""

    def __init__(self, raw_queue: queue.Queue, on_error_cb=None):
        self.raw_queue = raw_queue
        # Without this, a failure to open the device left the capture thread
        # dead and the UI waiting on audio that would never arrive.
        self.on_error_cb = on_error_cb
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pa = None
        self._stream = None
        self._dropped = 0

    def start(self):
        self._stop_event.clear()
        self._dropped = 0
        self._thread = threading.Thread(target=self._run, name="Thread-Capture", daemon=True)
        self._thread.start()
        logger.info("AudioCapture thread started.")

    def stop(self):
        self._stop_event.set()
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:  # noqa: BLE001
                pass
        self._pa = None
        self._stream = None
        if self._dropped:
            logger.warning("Dropped %d chunk(s) - the processing thread fell behind.", self._dropped)
        logger.info("AudioCapture stopped.")

    def _fail(self, message: str):
        logger.error(message)
        if self.on_error_cb:
            self.on_error_cb(message)

    def _get_loopback_device(self):
        """WASAPI loopback device for the default output."""
        try:
            default_speakers = self._pa.get_default_wasapi_loopback()
            if default_speakers:
                return default_speakers
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_default_wasapi_loopback failed: %s", exc)

        wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        device_info = self._pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        if device_info.get("isLoopbackDevice", False):
            return device_info

        name_prefix = device_info["name"][:20]
        candidates = [
            self._pa.get_device_info_by_index(i) for i in range(self._pa.get_device_count())
        ]
        loopbacks = [d for d in candidates if d.get("isLoopbackDevice", False)]

        for device in loopbacks:
            if device["name"].startswith(name_prefix):
                return device
        if loopbacks:
            logger.info("Using fallback loopback device: %s", loopbacks[0]["name"])
            return loopbacks[0]

        raise RuntimeError(
            "No WASAPI loopback device found. Set your headphones or speakers as the "
            "default playback device and reconnect."
        )

    def _run(self):
        self._pa = pyaudio.PyAudio()

        try:
            device_info = self._get_loopback_device()
        except Exception as exc:  # noqa: BLE001
            self._fail(str(exc))
            return

        sample_rate = int(device_info["defaultSampleRate"])
        channels = int(device_info["maxInputChannels"])
        chunk_size = int(sample_rate * LOOPBACK_CHUNK_MS / 1000)

        logger.info(
            "Loopback device: %s | %d Hz | %d ch | chunk=%d samples",
            device_info["name"],
            sample_rate,
            channels,
            chunk_size,
        )

        def _callback(in_data, frame_count, time_info, status):
            if self._stop_event.is_set():
                return (None, pyaudio.paAbort)
            try:
                chunk = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                self.raw_queue.put_nowait((chunk, sample_rate, channels))
            except queue.Full:
                self._dropped += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Capture callback error: %s", exc)
            return (None, pyaudio.paContinue)

        for attempt in range(1, MAX_OPEN_RETRIES + 1):
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
                    attempt,
                    MAX_OPEN_RETRIES,
                    exc,
                )
                if attempt == MAX_OPEN_RETRIES:
                    self._fail(
                        "Could not open the system audio stream. Another application may have "
                        "exclusive control of the playback device."
                    )
                    return
                time.sleep(1.0)

        self._stream.start_stream()
        logger.info("Loopback stream active.")

        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=0.1)

        logger.info("Capture thread exiting.")
