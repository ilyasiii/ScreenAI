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
    # Reject absurd uploads before decoding them. The browser sends ~1-2 MB.
    max_image_bytes: int = _int("MAX_IMAGE_BYTES", 6 * 1024 * 1024)
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

    # ── Authentication ───────────────────────────────────────────────────
    # Every API call must carry the caller's Supabase access token. Without
    # this the backend is an open relay: anyone who finds the URL can burn CPU
    # on image and PDF decoding, or route their own traffic through it.
    supabase_url: str = _str("SUPABASE_URL").rstrip("/")
    # Only needed for projects still on the legacy shared-secret (HS256) JWTs.
    # Projects on asymmetric signing keys are verified against the public JWKS
    # and need nothing secret here.
    supabase_jwt_secret: str = _str("SUPABASE_JWT_SECRET")
    # Escape hatch for offline local development only. Never disable in production.
    require_auth: bool = _bool("REQUIRE_AUTH", True)

    # ── Abuse limits ─────────────────────────────────────────────────────
    # Whole-request cap, enforced before the body is parsed. FastAPI has no
    # limit of its own, so without this a single request can exhaust memory.
    max_request_bytes: int = _int("MAX_REQUEST_BYTES", 12 * 1024 * 1024)
    max_audio_bytes: int = _int("MAX_AUDIO_BYTES", 10 * 1024 * 1024)
    max_pdf_pages: int = _int("MAX_PDF_PAGES", 40)
    # Sessions hold decoded screenshots in memory, so they are capped per user
    # and globally.
    max_sessions_per_user: int = _int("MAX_SESSIONS_PER_USER", 4)
    max_sessions_total: int = _int("MAX_SESSIONS_TOTAL", 500)
    # Memory held by pinned screenshots across all sessions. Pinning is refused
    # (503) past this, rather than letting a few accounts exhaust the server.
    # Size it to roughly a quarter of the machine's RAM.
    max_context_bytes_total: int = _int("MAX_CONTEXT_BYTES_TOTAL", 256 * 1024 * 1024)
    # Requests per user per minute, per endpoint group.
    rate_limit_analyze: int = _int("RATE_LIMIT_ANALYZE_PER_MIN", 20)
    rate_limit_upload: int = _int("RATE_LIMIT_UPLOAD_PER_MIN", 40)
    rate_limit_voice: int = _int("RATE_LIMIT_VOICE_PER_MIN", 20)
    rate_limit_session: int = _int("RATE_LIMIT_SESSION_PER_MIN", 20)
    # PDF parsing is the most expensive request; it gets its own small budget.
    rate_limit_pdf: int = _int("RATE_LIMIT_PDF_PER_MIN", 6)
    # Cheap housekeeping calls (clear context, delete session, reset memory).
    rate_limit_light: int = _int("RATE_LIMIT_LIGHT_PER_MIN", 60)

    # ── Server ───────────────────────────────────────────────────────────
    environment: str = _str("ENVIRONMENT", "development").lower()
    cors_origins: list[str] = [
        o.strip().rstrip("/")
        for o in _str("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
        if o.strip()
    ]
    log_level: str = _str("LOG_LEVEL", "INFO").upper()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

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
