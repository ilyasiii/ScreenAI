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
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from openai import AuthenticationError, PermissionDeniedError, RateLimitError
from pydantic import BaseModel, Field

from config import settings
from services.context_manager import context_manager
from services.credentials import MissingCredentialError, resolve_openai_key
from services.image_utils import is_duplicate, prepare_image
from services.openai_vision import analyze_screenshots_stream

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analyze"])


# --- Request / response models ---------------------------------------------


class ScreenshotRequest(BaseModel):
    session_id: str
    image_base64: str


class AnalyzeRequest(BaseModel):
    session_id: str
    image_base64: Optional[str] = None
    question: Optional[str] = Field(default=None, max_length=4000)
    profile: Optional[dict] = None


class SessionResponse(BaseModel):
    session_id: str


# --- Helpers ---------------------------------------------------------------


def _require_session(session_id: str):
    """Fetch a session or 404.

    Unknown IDs are an error, not an invitation to create one. The client
    treats `session_not_found` as "make a new session and retry", which also
    recovers transparently from a backend restart.
    """
    session = context_manager.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "session_not_found", "message": "Session expired or unknown."},
        )
    return session


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
        return await loop.run_in_executor(None, prepare_image, image_base64)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Image could not be decoded.") from exc
    except Exception as exc:  # noqa: BLE001 - Pillow raises a wide variety
        logger.warning("Image preparation failed: %s", exc)
        raise HTTPException(status_code=400, detail="Image could not be processed.") from exc


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


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


@router.post("/session/create", response_model=SessionResponse)
async def create_session():
    return SessionResponse(session_id=context_manager.create_session())


@router.post("/screenshot/add")
async def add_screenshot(req: ScreenshotRequest):
    """Pin the current frame as reference context."""
    session = _require_session(req.session_id)
    _validate_image(req.image_base64)

    prepared, meta = await _prepare(req.image_base64)
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
    req: AnalyzeRequest,
    x_openai_api_key: str | None = Header(default=None),
):
    """Analyse the current screen, streaming the answer as it is generated.

    A user-supplied key travels in a header rather than the JSON body, so it
    stays out of request-body logs and is never stored with session state.
    """
    session = _require_session(req.session_id)
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

    async def event_generator():
        request_id = uuid.uuid4().hex[:8]
        yield _sse({"type": "start"})

        usage: dict | None = None
        chunks: list[str] = []
        try:
            async for token in analyze_screenshots_stream(
                context_images,
                current_prepared,
                question,
                conversation,
                req.profile,
                api_key=api_key,
            ):
                if isinstance(token, dict) and "__usage__" in token:
                    usage = token["__usage__"]
                    continue
                chunks.append(token)
                yield _sse({"type": "token", "text": token})

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
            yield _sse(done)

        except asyncio.CancelledError:
            logger.info("[%s] client disconnected mid-stream", request_id)
            raise
        except (AuthenticationError, PermissionDeniedError) as exc:
            # Distinct from a generic failure: the browser can re-prompt for a
            # key instead of showing an error the user cannot act on.
            logger.warning("[%s] API key rejected: %s", request_id, exc)
            yield _sse(
                {
                    "type": "error",
                    "code": "invalid_api_key",
                    "message": "That API key was rejected. Check it and try again.",
                }
            )
        except RateLimitError:
            logger.warning("[%s] rate limited or out of quota", request_id)
            yield _sse(
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
            yield _sse(
                {
                    "type": "error",
                    "code": "analysis_failed",
                    "message": f"Analysis failed. Reference {request_id}.",
                }
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stop nginx buffering the stream
        },
    )


@router.post("/context/clear/{session_id}")
async def clear_context(session_id: str):
    session = _require_session(session_id)
    session.clear_screenshots()
    return {"status": "ok", "context_count": 0}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    if not context_manager.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"status": "ok"}
