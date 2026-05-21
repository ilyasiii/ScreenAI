"""
config.py
Central configuration for the Voice AI Assistant.
All tunable parameters live here — change as needed.
"""

# ── Hotkey ──────────────────────────────────────────────────────────────────
HOTKEY = "shift"                    # Hold to record, release to process

# ── Audio Capture ────────────────────────────────────────────────────────────
LOOPBACK_CHUNK_MS   = 30            # ms per capture chunk
LOOPBACK_SAMPLE_RATE = 48000        # Hz — standard Windows loopback rate
LOOPBACK_CHANNELS   = 2             # Stereo from system output

# ── Audio Processing ─────────────────────────────────────────────────────────
TARGET_SAMPLE_RATE  = 16000         # Hz — required by Whisper
TARGET_CHANNELS     = 1             # Mono

# ── Voice Activity Detection (Silero VAD) ────────────────────────────────────
VAD_THRESHOLD       = 0.50          # 0.0–1.0  |  >0.5 = speech
VAD_WINDOW_SAMPLES  = 512           # samples per VAD inference window (16kHz)

# ── Noise Suppression (DeepFilterNet) ────────────────────────────────────────
DENOISE_ENABLED     = True

# ── RMS Normalisation ────────────────────────────────────────────────────────
NORM_TARGET_RMS     = 0.05          # target RMS amplitude (0.0–1.0)

# ── Buffer Safety Guards ──────────────────────────────────────────────────────
BUFFER_MIN_SECONDS  = 0.5           # discard accidental presses shorter than this
BUFFER_MAX_SECONDS  = 60            # hard cap — trim if user holds > 60s

# ── ASR — Groq / whisper-large-v3 ────────────────────────────────────────────
GROQ_ASR_MODEL      = "whisper-large-v3"
ASR_LANGUAGE        = "en"          # set to None for auto-detect

# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_MEMORY_TURNS    = 10            # number of Q&A exchanges to keep in context
LLM_MAX_TOKENS      = 1024
LLM_TEMPERATURE     = 0.4
LLM_SYSTEM_PROMPT   = (
    "You are an expert interview assistant. "
    "When given a question or statement from an interviewer, "
    "respond with a clear, concise, structured answer. "
    "Use the STAR method for behavioural questions. "
    "Keep answers under 150 words unless the question demands more detail. "
    "Do NOT mention that you are an AI or that you are assisting anyone."
)

# ── Overlay UI ────────────────────────────────────────────────────────────────
OVERLAY_WIDTH       = 420           # pixels
OVERLAY_HEIGHT      = 560           # pixels
OVERLAY_MARGIN      = 18            # px from screen edge (top-right)
OVERLAY_OPACITY     = 0.93          # 0.0 (invisible) – 1.0 (opaque)
OVERLAY_FONT_SIZE   = 13            # pt
OVERLAY_BG_COLOR    = "#0D0D0D"
OVERLAY_TEXT_COLOR  = "#E8E8E8"
OVERLAY_ACCENT_REC  = "#E53935"     # red  — recording
OVERLAY_ACCENT_PROC = "#FFA726"     # amber — processing
OVERLAY_ACCENT_DONE = "#43A047"     # green — answer ready

# ── Queue max sizes (prevents unbounded memory growth) ───────────────────────
RAW_QUEUE_MAXSIZE   = 500           # ~15 seconds of 30ms chunks
ASR_QUEUE_MAXSIZE   = 5
LLM_QUEUE_MAXSIZE   = 5
