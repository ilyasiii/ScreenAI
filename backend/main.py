"""
ScreenAI backend.

Screenshot analysis and voice answers, both streamed over SSE. All tunables
live in config.py.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("screenai")

from middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware  # noqa: E402
from routers import analyze, voice  # noqa: E402 - must follow load_dotenv in config
from services.auth import auth_configured  # noqa: E402
from services.context_manager import context_manager  # noqa: E402
from services.credentials import credential_status  # noqa: E402
from services.rate_limit import limiter  # noqa: E402


async def _cleanup_loop():
    """Evict idle sessions so a long-running process does not accumulate
    screenshots for browsers that closed hours ago."""
    while True:
        await asyncio.sleep(600)
        try:
            removed = context_manager.cleanup_old_sessions()
            if removed:
                logger.info("Removed %d idle session(s).", removed)
            limiter.prune()
        except Exception:  # noqa: BLE001 - never let the janitor kill itself
            logger.exception("Session cleanup failed.")


def _check_configuration() -> None:
    if not settings.require_auth:
        logger.warning(
            "REQUIRE_AUTH is off - the API accepts unauthenticated requests. "
            "Use this for offline local development only."
        )
        if settings.is_production:
            raise RuntimeError("REQUIRE_AUTH must not be disabled in production.")
    elif not auth_configured():
        logger.error(
            "SUPABASE_URL is not set - every API request will be refused until it is."
        )

    if settings.is_production:
        insecure = [o for o in settings.cors_origins if not o.startswith("https://")]
        if insecure:
            logger.warning("Non-HTTPS CORS origins in production: %s", ", ".join(insecure))

    if not settings.vision_configured:
        if settings.allow_client_keys:
            logger.info(
                "OPENAI_API_KEY is not set - users will be asked for their own key "
                "in the browser."
            )
        else:
            logger.warning(
                "OPENAI_API_KEY is not set and ALLOW_CLIENT_API_KEYS is off - "
                "screenshot analysis cannot work."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_configuration()

    # Held on app.state: asyncio only keeps a weak reference to running tasks,
    # so a bare create_task() can be garbage-collected mid-flight.
    app.state.cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        app.state.cleanup_task.cancel()
        try:
            await app.state.cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="ScreenAI",
    description="Screen reading and question answering",
    version="2.1.0",
    lifespan=lifespan,
    # The interactive docs map every endpoint for anyone who finds them.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Order matters: the last one added runs first. CORS is outermost so that even
# a request refused for its size still carries CORS headers, and the browser
# shows the real 413 instead of an opaque CORS failure.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Auth is a bearer token in a header, never a cookie.
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-OpenAI-Api-Key",
        "X-Groq-Api-Key",
        "X-Anthropic-Api-Key",
    ],
    expose_headers=["Retry-After"],
    max_age=600,
)

app.include_router(analyze.router, prefix="/api")
app.include_router(voice.router)


@app.get("/")
async def root():
    return {"message": "ScreenAI backend is running"}


@app.get("/health")
async def health():
    """Configuration the browser needs to decide whether to prompt for a key.

    Public, so it reports only whether each key is present, never any part of
    its value, and nothing about load or internals.
    """
    return {
        "status": "healthy",
        "voice_provider": settings.llm_provider,
        **credential_status(),
    }
