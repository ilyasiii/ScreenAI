"""
Central configuration.

Every tunable lives here so the rest of the code never calls os.getenv()
directly. Import `settings` and read attributes.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Values shipped in .env.example that mean "not configured yet".
_PLACEHOLDERS = {
    "",
    "sk-your-api-key-here",
    "gsk-your-groq-key-here",
    "sk-ant-your-anthropic-key-here",
}


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _key(name: str) -> str:
    """Read an API key, treating .env.example placeholders as unset."""
    value = _str(name)
    return "" if value in _PLACEHOLDERS else value


def _bool(name: str, default: bool) -> bool:
    raw = _str(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name) or default)
    except ValueError:
        return default


class Settings:
    # ── Credentials ──────────────────────────────────────────────────────
    openai_api_key: str = _key("OPENAI_API_KEY")
    groq_api_key: str = _key("GROQ_API_KEY")
    anthropic_api_key: str = _key("ANTHROPIC_API_KEY")

    # ── Vision (screen analysis) ─────────────────────────────────────────
    vision_model: str = _str("OPENAI_MODEL", "gpt-4.1")
    vision_temperature: float = _float("VISION_TEMPERATURE", 0.1)
    vision_max_tokens: int = _int("VISION_MAX_TOKENS", 4096)

    # ── Voice ────────────────────────────────────────────────────────────
    llm_provider: str = _str("LLM_PROVIDER", "openai").lower()
    llm_model: str = _str("LLM_MODEL", "gpt-4.1")
    asr_model: str = _str("ASR_MODEL", "whisper-large-v3")
    asr_language: str = _str("ASR_LANGUAGE", "en")

    # ── Image pipeline ───────────────────────────────────────────────────
    # The vision API rescales every `detail: high` image so its SHORT side is
    # 768px, then bills ceil(w/512) * ceil(h/512) tiles. Sending anything
    # larger costs the same tokens and is thrown away; sending anything
    # smaller costs the same tokens and is upscaled back into a blur.
    # 768 on the short side is therefore the only sensible target.
    image_short_side: int = _int("IMAGE_SHORT_SIDE", 768)
    # Bound the long side so an ultrawide monitor cannot balloon the tile count.
    image_max_long_side: int = _int("IMAGE_MAX_LONG_SIDE", 2048)
    # Screenshots are mostly text. 4:4:4 chroma (no subsampling) at q88 keeps
    # syntax-highlighted code legible; the old q40 shredded small glyphs.
    image_jpeg_quality: int = _int("IMAGE_JPEG_QUALITY", 88)
    # Reject absurd uploads before decoding them.
    max_image_bytes: int = _int("MAX_IMAGE_BYTES", 12 * 1024 * 1024)
    max_pdf_bytes: int = _int("MAX_PDF_BYTES", 10 * 1024 * 1024)

    # ── Session state ────────────────────────────────────────────────────
    max_context_images: int = _int("MAX_CONTEXT_IMAGES", 6)
    max_conversation_messages: int = _int("MAX_CONVERSATION_MESSAGES", 10)
    session_ttl_seconds: int = _int("SESSION_TTL_SECONDS", 3600)
    # Two screenshots whose perceptual hashes differ by <= this many bits are
    # treated as the same frame. Stops a dozen identical captures of a static
    # page from being paid for a dozen times.
    duplicate_hash_distance: int = _int("DUPLICATE_HASH_DISTANCE", 4)

    # ── Credentials supplied by the browser ──────────────────────────────
    # When the server has no key of its own, the app can ask the user for
    # theirs and pass it per request. A server key always takes precedence, so
    # turning this on cannot redirect billing. Set false to require a
    # server-side key and refuse client-supplied ones outright.
    allow_client_keys: bool = _bool("ALLOW_CLIENT_API_KEYS", True)

    # ── Server ───────────────────────────────────────────────────────────
    cors_origins: list[str] = [
        o.strip()
        for o in _str("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
        if o.strip()
    ]
    log_level: str = _str("LOG_LEVEL", "INFO").upper()

    # ── Derived ──────────────────────────────────────────────────────────
    @property
    def vision_configured(self) -> bool:
        return bool(self.openai_api_key)

    def voice_llm_key(self) -> str:
        """API key for the configured voice provider.

        Each provider gets its own key. The previous build read
        OPENAI_API_KEY for all three, so selecting groq or anthropic was
        impossible without breaking vision.
        """
        return {
            "openai": self.openai_api_key,
            "groq": self.groq_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(self.llm_provider, "")


settings = Settings()
