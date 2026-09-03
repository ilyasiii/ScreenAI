"""
ScreenAI backend.

Screenshot analysis over SSE, and a WebSocket voice pipeline. All tunables
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
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("screenai")

from routers import analyze, voice  # noqa: E402 - must follow load_dotenv in config
from services.context_manager import context_manager  # noqa: E402
from services.credentials import credential_status  # noqa: E402


async def _cleanup_loop():
    """Evict idle sessions so a long-running process does not accumulate
    screenshots for browsers that closed hours ago."""
    while True:
        await asyncio.sleep(600)
        try:
            removed = context_manager.cleanup_old_sessions()
            if removed:
                logger.info("Removed %d idle session(s).", removed)
        except Exception:  # noqa: BLE001 - never let the janitor kill itself
            logger.exception("Session cleanup failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(analyze.router, prefix="/api")
app.include_router(voice.router)


@app.get("/")
async def root():
    return {"message": "ScreenAI backend is running", "version": app.version}


@app.get("/health")
async def health():
    """Configuration the browser needs to decide whether to prompt for a key.

    Reports only whether each key is present, never any part of its value.
    """
    return {
        "status": "healthy",
        "model": settings.vision_model,
        "voice_provider": settings.llm_provider,
        "active_sessions": context_manager.session_count(),
        **credential_status(),
    }
