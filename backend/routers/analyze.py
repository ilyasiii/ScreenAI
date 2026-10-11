"""
Screen analysis endpoints.

The SSE protocol every event carries a `type`:

    {"type": "start"}                                  connection is live
    {"type": "token", "text": "..."}                   answer content
    {"type": "done",  "context_count": n, "usage": {}} finished cleanly
    {"type": "error", "message": "...", "code": "..."} failed

`start` is emitted before the model is called so the browser can drop its
skeleton loader the moment the request is accepted, rather than waiting on
time-to-first-token.
"""

import asyncio
import binascii
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from openai import AuthenticationError, PermissionDeniedError, RateLimitError
from pydantic import BaseModel, Field

from config import settings
from routers.common import (
    SESSION_ID_PATTERN,
    SSE_HEADERS,
    Profile,
    create_session_for,
    read_json,
    require_session,
    sse,
)
from services.auth import AuthUser
from services.context_manager import context_manager
from services.credentials import MissingCredentialError, resolve_openai_key
from services.image_utils import is_duplicate, prepare_image
from services.openai_vision import analyze_screenshots_stream
from services.rate_limit import rate_limited

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analyze"])

# Decoding a screenshot briefly needs tens of megabytes. A small dedicated pool
# caps how many run at once, so a burst of uploads queues instead of
# exhausting memory, and never starves the shared default executor.
_IMAGE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="image")

_light = rate_limited("light", lambda: settings.rate_limit_light)


# --- Request / response models ---------------------------------------------


class ScreenshotRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    image_base64: str


class AnalyzeRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    image_base64: Optional[str] = None
    question: Optional[str] = Field(default=None, max_length=4000)
    profile: Optional[Profile] = None


class SessionResponse(BaseModel):
    session_id: str


# --- Helpers ---------------------------------------------------------------


def _validate_image(image_base64: str) -> None:
    """Cheap guards before spending CPU on a decode."""
    if not image_base64:
        raise HTTPException(status_code=400, detail="image_base64 is required")

    # base64 inflates by 4/3; check the encoded length to avoid decoding first.
    approx_bytes = len(image_base64) * 3 // 4
    if approx_bytes > settings.max_image_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds {settings.max_image_bytes // (1024 * 1024)} MB limit.",
        )


async def _prepare(image_base64: str) -> tuple[str, dict]:
    """Resize and re-encode off the event loop - PIL is CPU-bound and would
    otherwise stall every other request, including live SSE streams."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(_IMAGE_POOL, prepare_image, image_base64)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Image could not be decoded.") from exc
    except Exception as exc:  # noqa: BLE001 - Pillow raises a wide variety
        logger.warning("Image preparation failed: %s", exc)
        raise HTTPException(status_code=400, detail="Image could not be processed.") from exc


def _require_openai_key(client_key: str | None) -> str:
    """Server key, else the one the browser supplied.

    A 401 carrying `api_key_required` is the browser's cue to prompt the user
    for a key. `api_key_refused` means the operator has disabled
    client-supplied keys, so prompting would be pointless.
    """
    try:
        return resolve_openai_key(client_key)
    except MissingCredentialError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "api_key_required" if exc.client_keys_allowed else "api_key_refused",
                "message": (
                    "An OpenAI API key is required to analyse the screen."
                    if exc.client_keys_allowed
                    else "This server has no OpenAI key configured and does not accept "
                    "keys from the browser."
                ),
            },
        ) from exc


# --- Endpoints -------------------------------------------------------------


_SessionPath = Path(pattern=SESSION_ID_PATTERN)


@router.post("/session/create", response_model=SessionResponse)
async def create_session(
    user: AuthUser = Depends(rate_limited("session", lambda: settings.rate_limit_session)),
):
    return SessionResponse(session_id=create_session_for(user))


@router.post("/screenshot/add")
async def add_screenshot(
    request: Request,
    user: AuthUser = Depends(rate_limited("upload", lambda: settings.rate_limit_upload)),
):
    """Pin the current frame as reference context."""
    req = await read_json(request, ScreenshotRequest)
    session = require_session(req.session_id, user)
    _validate_image(req.image_base64)

    prepared, meta = await _prepare(req.image_base64)
    if not context_manager.has_room_for(len(prepared)):
        raise HTTPException(
            status_code=503,
            detail={"code": "server_busy", "message": "The server is busy. Try again shortly."},
            headers={"Retry-After": "30"},
        )
    result = session.add_screenshot(prepared, meta["hash"], meta["estimated_tokens"])

    return {
        "status": "ok",
        "added": result["added"],
        "reason": result["reason"],
        "context_count": result["count"],
        "context_tokens": session.context_tokens(),
        "session_id": req.session_id,
    }


@router.post("/analyze/stream")
async def analyze_stream(
    request: Request,
    x_openai_api_key: str | None = Header(default=None),
    user: AuthUser = Depends(rate_limited("analyze", lambda: settings.rate_limit_analyze)),
):
    """Analyse the current screen, streaming the answer as it is generated.

    A user-supplied key travels in a header rather than the JSON body, so it
    stays out of request-body logs and is never stored with session state.
    """
    req = await read_json(request, AnalyzeRequest)
    session = require_session(req.session_id, user)
    api_key = _require_openai_key(x_openai_api_key)

    current_prepared: str | None = None
    if req.image_base64:
        _validate_image(req.image_base64)
        current_prepared, meta = await _prepare(req.image_base64)

        # If the live screen is already pinned as context, don't send it twice.
        # A duplicate pair wastes a full image's worth of tokens and gives the
        # model two copies of the same thing to reconcile.
        if any(is_duplicate(h, meta["hash"]) for h in session.context_hashes()):
            logger.debug("Current frame duplicates a pinned reference; sending once.")
            current_prepared = None

    context_images = session.context_images()
    if not context_images and not current_prepared:
        raise HTTPException(status_code=400, detail="No screenshot provided.")

    conversation = session.conversation_history()
    question = (req.question or "").strip() or None
    profile = req.profile.as_dict() if req.profile else None

    async def event_generator():
        request_id = uuid.uuid4().hex[:8]
        yield sse({"type": "start"})

        usage: dict | None = None
        chunks: list[str] = []
        try:
            async for token in analyze_screenshots_stream(
                context_images,
                current_prepared,
                question,
                conversation,
                profile,
                api_key=api_key,
            ):
                if isinstance(token, dict) and "__usage__" in token:
                    usage = token["__usage__"]
                    continue
                chunks.append(token)
                yield sse({"type": "token", "text": token})

            answer = "".join(chunks)
            if answer.strip():
                # Record the turn so follow-ups ("now make it iterative") have
                # the prior exchange to resolve against.
                session.add_exchange(question or "Analyse the current screen.", answer)

            done: dict = {
                "type": "done",
                "context_count": len(context_images),
                "context_tokens": session.context_tokens(),
            }
            if usage:
                done["usage"] = usage
            yield sse(done)

        except asyncio.CancelledError:
            logger.info("[%s] client disconnected mid-stream", request_id)
            raise
        except (AuthenticationError, PermissionDeniedError) as exc:
            # Distinct from a generic failure: the browser can re-prompt for a
            # key instead of showing an error the user cannot act on.
            logger.warning("[%s] API key rejected: %s", request_id, exc)
            yield sse(
                {
                    "type": "error",
                    "code": "invalid_api_key",
                    "message": "That API key was rejected. Check it and try again.",
                }
            )
        except RateLimitError:
            logger.warning("[%s] rate limited or out of quota", request_id)
            yield sse(
                {
                    "type": "error",
                    "code": "rate_limited",
                    "message": "The API key is rate limited or out of quota.",
                }
            )
        except Exception as exc:  # noqa: BLE001
            # Log the detail, return a reference. The old code streamed str(e)
            # straight to the browser, which leaked internals on any failure.
            logger.error("[%s] analysis failed: %s", request_id, exc, exc_info=True)
            yield sse(
                {
                    "type": "error",
                    "code": "analysis_failed",
                    "message": f"Analysis failed. Reference {request_id}.",
                }
            )

    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/context/clear/{session_id}")
async def clear_context(session_id: str = _SessionPath, user: AuthUser = Depends(_light)):
    session = require_session(session_id, user)
    session.clear_screenshots()
    return {"status": "ok", "context_count": 0}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str = _SessionPath, user: AuthUser = Depends(_light)):
    if not context_manager.delete_session(session_id, owner_id=user.id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"status": "ok"}
