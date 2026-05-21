"""
modules/capture.py
Thread 1 — WASAPI Loopback Audio Capture

Continuously reads raw audio from the system's default playback device
(whatever is going to your headphones) using PyAudioWPatch's loopback mode.
Raw float32 stereo chunks are placed onto RAW_QUEUE for Thread 2 to consume.
"""

import threading
import queue
import logging
import numpy as np

import pyaudiowpatch as pyaudio

import config

logger = logging.getLogger(__name__)


class AudioCapture:
    """
    Captures system audio via WASAPI loopback.
    Runs in its own daemon thread.
    Produces raw numpy chunks onto raw_queue.
    """

    def __init__(self, raw_queue: queue.Queue):
        self.raw_queue   = raw_queue
        self._stop_event = threading.Event()
        self._thread     = threading.Thread(
            target=self._run, name="Thread-Capture", daemon=True
        )
        self._pa         = None
        self._stream     = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
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
        logger.info("AudioCapture stopped.")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_loopback_device(self):
        """Return the WASAPI loopback device info for the default output."""
        wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out_idx = wasapi_info["defaultOutputDevice"]
        device_info = self._pa.get_device_info_by_index(default_out_idx)

        if not device_info.get("isLoopbackDevice", False):
            # Find the loopback sibling of the default output device
            for i in range(self._pa.get_device_count()):
                d = self._pa.get_device_info_by_index(i)
                if d.get("isLoopbackDevice", False) and d["name"].startswith(
                    device_info["name"][:20]
                ):
                    return d
            raise RuntimeError(
                "Could not find a WASAPI loopback device. "
                "Make sure your headphones are set as the default playback device."
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
        channels    = int(device_info["maxInputChannels"])
        chunk_size  = int(sample_rate * config.LOOPBACK_CHUNK_MS / 1000)

        logger.info(
            "Loopback device: %s | %d Hz | %d ch | chunk=%d samples",
            device_info["name"], sample_rate, channels, chunk_size
        )

        def _callback(in_data, frame_count, time_info, status):
            if self._stop_event.is_set():
                return (None, pyaudio.paAbort)
            try:
                chunk = np.frombuffer(in_data, dtype=np.float32).copy()
                if not self.raw_queue.full():
                    self.raw_queue.put_nowait((chunk, sample_rate, channels))
            except Exception as exc:
                logger.warning("Capture callback error: %s", exc)
            return (None, pyaudio.paContinue)

        self._stream = self._pa.open(
            format              = pyaudio.paFloat32,
            channels            = channels,
            rate                = sample_rate,
            input               = True,
            input_device_index  = device_info["index"],
            frames_per_buffer   = chunk_size,
            stream_callback     = _callback,
        )

        self._stream.start_stream()
        logger.info("Loopback stream active.")

        # Keep thread alive until stop requested
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=0.1)

        logger.info("Capture thread exiting.")
