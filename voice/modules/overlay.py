"""
modules/overlay.py
Main Thread — PyQt6 Stealth Overlay Window

Features:
  • Top-right corner, always on top
  • Invisible to screen capture (SetWindowDisplayAffinity WDA_EXCLUDEFROMCAPTURE)
  • Semi-transparent dark panel
  • State-aware: IDLE → RECORDING → PROCESSING → ANSWER
  • Streams LLM tokens as they arrive
  • Ctrl+Shift+H global hotkey to toggle visibility
  • Ctrl+Shift+C to clear conversation memory
"""

import ctypes
import logging
import textwrap

from PyQt6.QtCore    import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui     import QFont, QColor, QPalette, QScreen
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QSizePolicy
)

import config

logger = logging.getLogger(__name__)

# Windows API constant
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def _apply_stealth(hwnd: int):
    """Make the window invisible to screen capture tools (Windows only)."""
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        logger.info("Stealth mode applied (WDA_EXCLUDEFROMCAPTURE).")
    except Exception as exc:
        logger.warning("Could not apply stealth mode: %s", exc)


# ── Qt Signals bridge (thread-safe UI updates) ───────────────────────────────

class _Signals(QObject):
    set_idle       = pyqtSignal()
    set_recording  = pyqtSignal(str)       # timer text
    set_processing = pyqtSignal()
    append_token   = pyqtSignal(str)
    set_answer_done= pyqtSignal()
    set_error      = pyqtSignal(str)
    update_timer   = pyqtSignal(str)


# ── State constants ───────────────────────────────────────────────────────────
STATE_IDLE       = "idle"
STATE_RECORDING  = "recording"
STATE_PROCESSING = "processing"
STATE_ANSWER     = "answer"


class OverlayWindow(QWidget):
    """
    The main stealth overlay window.
    All UI mutations MUST happen on the main (Qt) thread via signals.
    """

    def __init__(self, signals: _Signals, on_clear_memory=None):
        super().__init__()
        self.signals          = signals
        self.on_clear_memory  = on_clear_memory
        self._state           = STATE_IDLE
        self._answer_text     = ""
        self._visible         = True

        self._build_ui()
        self._connect_signals()
        self._position_window()
        self._apply_stealth()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("Voice AI")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(config.OVERLAY_OPACITY)

        # ── Root layout inside a styled container ─────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._container = QFrame()
        self._container.setObjectName("container")
        self._container.setStyleSheet(f"""
            QFrame#container {{
                background-color: {config.OVERLAY_BG_COLOR};
                border-radius: 12px;
                border: 1px solid #2A2A2A;
            }}
        """)
        root.addWidget(self._container)

        inner = QVBoxLayout(self._container)
        inner.setContentsMargins(14, 12, 14, 14)
        inner.setSpacing(8)

        # ── Header row ────────────────────────────────────────────────────
        header = QHBoxLayout()
        inner.addLayout(header)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(
            f"color: #555555; font-size: 11px; font-weight: bold;"
        )
        header.addWidget(self._dot)

        self._status_label = QLabel("Hold Ctrl to capture")
        self._status_label.setStyleSheet(
            f"color: #888888; font-size: 11px;"
        )
        header.addWidget(self._status_label)
        header.addStretch()

        # Hint key label
        hint = QLabel("Ctrl+Shift+H hide")
        hint.setStyleSheet("color: #444444; font-size: 9px;")
        header.addWidget(hint)

        # ── Separator ─────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2A2A2A;")
        inner.addWidget(sep)

        # ── Transcript label (what was heard) ─────────────────────────────
        self._transcript_label = QLabel("")
        self._transcript_label.setWordWrap(True)
        self._transcript_label.setStyleSheet(
            f"color: #666666; font-size: 10px; font-style: italic;"
        )
        self._transcript_label.setVisible(False)
        inner.addWidget(self._transcript_label)

        # ── Answer scroll area ────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setMinimumHeight(200)
        inner.addWidget(scroll)

        self._answer_label = QLabel("")
        self._answer_label.setWordWrap(True)
        self._answer_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._answer_label.setTextFormat(Qt.TextFormat.PlainText)
        self._answer_label.setFont(
            QFont("Segoe UI", config.OVERLAY_FONT_SIZE)
        )
        self._answer_label.setStyleSheet(
            f"color: {config.OVERLAY_TEXT_COLOR}; background: transparent; padding: 4px;"
        )
        self._answer_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        scroll.setWidget(self._answer_label)
        self._scroll = scroll

        # ── Bottom buttons ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        inner.addLayout(btn_row)

        self._clear_btn = QPushButton("Clear Memory")
        self._clear_btn.setStyleSheet("""
            QPushButton {
                background: #1E1E1E;
                color: #666666;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #2A2A2A;
                color: #AAAAAA;
            }
        """)
        self._clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setStyleSheet("""
            QPushButton {
                background: #1E1E1E;
                color: #666666;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #2A2A2A;
                color: #AAAAAA;
            }
        """)
        self._copy_btn.clicked.connect(self._on_copy)
        btn_row.addWidget(self._copy_btn)

        self.setFixedWidth(config.OVERLAY_WIDTH)

    # ── Connect signals ───────────────────────────────────────────────────────

    def _connect_signals(self):
        self.signals.set_idle.connect(self._on_idle)
        self.signals.set_recording.connect(self._on_recording)
        self.signals.set_processing.connect(self._on_processing)
        self.signals.append_token.connect(self._on_token)
        self.signals.set_answer_done.connect(self._on_answer_done)
        self.signals.set_error.connect(self._on_error)
        self.signals.update_timer.connect(self._on_timer_update)

    # ── Window positioning ────────────────────────────────────────────────────

    def _position_window(self):
        screen: QScreen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.right() - config.OVERLAY_WIDTH - config.OVERLAY_MARGIN
        y = geo.top() + config.OVERLAY_MARGIN
        self.move(x, y)

    # ── Stealth ───────────────────────────────────────────────────────────────

    def _apply_stealth(self):
        self.show()                         # must be visible to get HWND
        hwnd = int(self.winId())
        _apply_stealth(hwnd)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_idle(self):
        self._state = STATE_IDLE
        self._dot.setStyleSheet("color: #555555; font-size: 11px; font-weight: bold;")
        self._status_label.setText("Hold Ctrl to capture")
        self._status_label.setStyleSheet("color: #888888; font-size: 11px;")
        self._transcript_label.setVisible(False)

    def _on_recording(self, timer_text: str):
        self._state = STATE_RECORDING
        self._dot.setStyleSheet(
            f"color: {config.OVERLAY_ACCENT_REC}; font-size: 11px; font-weight: bold;"
        )
        self._status_label.setText(f"Recording  {timer_text}")
        self._status_label.setStyleSheet(
            f"color: {config.OVERLAY_ACCENT_REC}; font-size: 11px; font-weight: bold;"
        )

    def _on_timer_update(self, timer_text: str):
        if self._state == STATE_RECORDING:
            self._status_label.setText(f"Recording  {timer_text}")

    def _on_processing(self):
        self._state = STATE_PROCESSING
        self._dot.setStyleSheet(
            f"color: {config.OVERLAY_ACCENT_PROC}; font-size: 11px; font-weight: bold;"
        )
        self._status_label.setText("Transcribing…")
        self._status_label.setStyleSheet(
            f"color: {config.OVERLAY_ACCENT_PROC}; font-size: 11px;"
        )

    def _on_token(self, token: str):
        if self._state != STATE_ANSWER:
            # First token — switch to answer state
            self._state = STATE_ANSWER
            self._answer_text = ""
            self._dot.setStyleSheet(
                f"color: {config.OVERLAY_ACCENT_DONE}; font-size: 11px; font-weight: bold;"
            )
            self._status_label.setText("Answer")
            self._status_label.setStyleSheet(
                f"color: {config.OVERLAY_ACCENT_DONE}; font-size: 11px;"
            )

        self._answer_text += token
        self._answer_label.setText(self._answer_text)

        # Auto-scroll to bottom
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_answer_done(self):
        self._state = STATE_ANSWER
        # Show what was heard (transcript stored in label tooltip)
        transcript = self._transcript_label.toolTip()
        if transcript:
            self._transcript_label.setText(f"Q: {transcript[:120]}…" if len(transcript) > 120 else f"Q: {transcript}")
            self._transcript_label.setVisible(True)

    def _on_error(self, error: str):
        self._state = STATE_IDLE
        self._dot.setStyleSheet("color: #FF5252; font-size: 11px; font-weight: bold;")
        self._status_label.setText("Error")
        self._status_label.setStyleSheet("color: #FF5252; font-size: 11px;")
        self._answer_label.setText(f"[Error] {error}")

    def _on_clear(self):
        self._answer_text = ""
        self._answer_label.setText("")
        self._transcript_label.setVisible(False)
        if self.on_clear_memory:
            self.on_clear_memory()
        self._on_idle()

    def _on_copy(self):
        if self._answer_text:
            QApplication.clipboard().setText(self._answer_text)

    # ── Public methods (called from main.py) ──────────────────────────────────

    def set_transcript_hint(self, text: str):
        """Store transcript so it shows after answer completes."""
        self._transcript_label.setToolTip(text)

    def toggle_visibility(self):
        self._visible = not self._visible
        self.setVisible(self._visible)


# ── Factory: create signals object (used by main.py) ─────────────────────────

def make_signals() -> _Signals:
    return _Signals()
