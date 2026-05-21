"""
main.py
Entry point — Voice AI Interview Assistant

Wires all four threads together with thread-safe queues:

  Thread 1 (AudioCapture)   →  RAW_QUEUE
  Thread 2 (AudioProcessor) →  RAW_QUEUE  →  ASR_QUEUE
  Thread 3 (Transcriber)    →  ASR_QUEUE  →  LLM_QUEUE
  Thread 4 (LLMResponder)   →  LLM_QUEUE  →  Qt Signals → Overlay

Hotkeys (global, work even when window is not focused):
  Shift             Hold to record, release to process
  Shift+Ctrl+H      Toggle overlay visibility
  Shift+Ctrl+C      Clear conversation memory
  Shift+Ctrl+Q      Quit application
"""

import sys
import queue
import logging
import time
import threading

from dotenv import load_dotenv
load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s  %(levelname)-8s  [%(threadName)s]  %(message)s",
    datefmt= "%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Qt must be imported before anything spawns a QApplication ─────────────────
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore    import QTimer
import keyboard

import config
from modules.capture       import AudioCapture
from modules.processing    import AudioProcessor
from modules.transcription import Transcriber
from modules.llm           import LLMResponder
from modules.overlay       import OverlayWindow, make_signals


# ── Shared queues ─────────────────────────────────────────────────────────────
raw_queue = queue.Queue(maxsize=config.RAW_QUEUE_MAXSIZE)
asr_queue = queue.Queue(maxsize=config.ASR_QUEUE_MAXSIZE)
llm_queue = queue.Queue(maxsize=config.LLM_QUEUE_MAXSIZE)


# ── Recording timer (updates overlay every 100 ms while key held) ─────────────
class RecordingTimer:
    def __init__(self, tick_cb):
        self._tick_cb  = tick_cb
        self._start    = 0.0
        self._active   = False
        self._timer    = None

    def start(self):
        self._start  = time.monotonic()
        self._active = True
        self._tick()

    def stop(self):
        self._active = False
        if self._timer:
            self._timer.cancel()

    def _tick(self):
        if not self._active:
            return
        elapsed = time.monotonic() - self._start
        self._tick_cb(f"{elapsed:.1f}s")
        self._timer = threading.Timer(0.1, self._tick)
        self._timer.daemon = True
        self._timer.start()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ── Signals bridge (thread → Qt UI) ──────────────────────────────────────
    sigs = make_signals()

    # ── Instantiate all components ────────────────────────────────────────────
    capture   = AudioCapture(raw_queue)
    processor = AudioProcessor(raw_queue, asr_queue)

    def on_asr_start():
        sigs.set_processing.emit()

    def on_asr_result(transcript: str):
        # Store transcript hint so overlay can show "Q: …" after answer
        overlay.set_transcript_hint(transcript)

    def on_asr_error(err: str):
        sigs.set_error.emit(err)
        sigs.set_idle.emit()

    transcriber = Transcriber(
        asr_queue    = asr_queue,
        llm_queue    = llm_queue,
        on_start_cb  = on_asr_start,
        on_result_cb = on_asr_result,
        on_error_cb  = on_asr_error,
    )

    def on_llm_start():
        sigs.set_processing.emit()   # stay in processing state until first token

    def on_token(tok: str):
        sigs.append_token.emit(tok)

    def on_answer_done():
        sigs.set_answer_done.emit()

    def on_llm_error(err: str):
        sigs.set_error.emit(err)
        sigs.set_idle.emit()

    responder = LLMResponder(
        llm_queue          = llm_queue,
        on_token_cb        = on_token,
        on_answer_start_cb = on_llm_start,
        on_answer_end_cb   = on_answer_done,
        on_error_cb        = on_llm_error,
    )

    # ── Overlay window ────────────────────────────────────────────────────────
    overlay = OverlayWindow(
        signals         = sigs,
        on_clear_memory = responder.clear_memory,
    )

    # ── Recording timer ───────────────────────────────────────────────────────
    rec_timer = RecordingTimer(
        tick_cb=lambda txt: sigs.update_timer.emit(txt)
    )

    # ── Hotkey state (debounce: only fire once per hold) ──────────────────────
    _shift_held = False

    def on_shift_down():
        nonlocal _shift_held
        if _shift_held:
            return                  # already recording — ignore repeat events
        _shift_held = True
        sigs.set_recording.emit("0.0s")
        rec_timer.start()
        processor.on_key_press()
        logger.info("Shift DOWN → recording started")

    def on_shift_up():
        nonlocal _shift_held
        if not _shift_held:
            return
        _shift_held = False
        rec_timer.stop()
        processor.on_key_release()
        logger.info("Shift UP → buffer dispatched")

    def on_toggle_visibility():
        overlay.toggle_visibility()

    def on_clear_memory():
        responder.clear_memory()
        sigs.set_idle.emit()

    def on_quit():
        logger.info("Quit hotkey pressed — shutting down.")
        _shutdown()
        app.quit()

    # ── Register hotkeys ──────────────────────────────────────────────────────
    # Shift alone: suppress=False so normal Shift typing still works
    keyboard.on_press_key  ("shift",  lambda _: on_shift_down(), suppress=False)
    keyboard.on_release_key("shift",  lambda _: on_shift_up(),   suppress=False)
    keyboard.add_hotkey("shift+ctrl+h", on_toggle_visibility,  suppress=True)
    keyboard.add_hotkey("shift+ctrl+c", on_clear_memory,       suppress=True)
    keyboard.add_hotkey("shift+ctrl+q", on_quit,               suppress=True)

    logger.info("Hotkeys registered.")

    # ── Start all threads ─────────────────────────────────────────────────────
    capture.start()
    processor.start()
    transcriber.start()
    responder.start()

    logger.info("All threads running. Overlay visible (top-right).")
    logger.info("Hold Ctrl while interviewer speaks, release for AI answer.")

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    def _shutdown():
        logger.info("Shutting down…")
        keyboard.unhook_all()
        rec_timer.stop()
        capture.stop()
        processor.stop()
        transcriber.stop()
        responder.stop()

    app.aboutToQuit.connect(_shutdown)

    # ── Enter Qt event loop ───────────────────────────────────────────────────
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
