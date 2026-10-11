"""Pieces shared by the analysis and voice routers."""

import json
from typing import TypeVar

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from services.auth import AuthUser
from services.context_manager import SessionContext, SessionLimitError, context_manager

SESSION_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# Generous next to what the prompts actually use (3k / 6k characters), so the
# limits never bite a real CV, while still bounding what is held per request.
_PROFILE_LIMITS = {"job_title": 200, "job_description": 20_000, "cv_text": 50_000}


class Profile(BaseModel):
    """The candidate context sent with a question. Unknown keys are dropped."""

    model_config = ConfigDict(extra="ignore")

    job_title: str | None = None
    job_description: str | None = None
    cv_text: str | None = None

    @field_validator("job_title", "job_description", "cv_text", mode="before")
    @classmethod
    def _truncate(cls, value, info):
        # Truncate rather than reject: a long CV should still work, just
        # clipped, instead of failing the user's question with a 422.
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value[: _PROFILE_LIMITS[info.field_name]]

    def as_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


# --- Request bodies ---------------------------------------------------------
#
# Bodies are read inside the handler, after the auth and rate-limit
# dependencies have run, never as FastAPI body parameters: FastAPI parses those
# before any dependency, so an anonymous caller could make the server decode
# a 20 MB body before being turned away.

ModelT = TypeVar("ModelT", bound=BaseModel)

# A real request is one long base64 string plus some text, so it contains very
# few JSON containers or separators. Capping them bounds how many objects any
# parse can allocate: without this, 20 MB of "[{},{},...]" expands to roughly
# 500 MB of Python objects. Generous next to legitimate use (a CV's commas).
_MAX_JSON_CONTAINERS = 10_000
_MAX_JSON_SEPARATORS = 100_000


def _validation_error(exc: ValidationError) -> RequestValidationError:
    # Drop the offending input from the 422 body: it can be a multi-megabyte
    # image string, and echoing request content back is never useful here.
    return RequestValidationError(
        [{k: v for k, v in err.items() if k in ("type", "loc", "msg")} for err in exc.errors()]
    )


async def read_json(request: Request, model: type[ModelT]) -> ModelT:
    """Parse and validate a JSON body after the caller has been authenticated."""
    body = await request.body()  # size already capped by BodySizeLimitMiddleware
    if (
        body.count(b"{") + body.count(b"[") > _MAX_JSON_CONTAINERS
        or body.count(b",") > _MAX_JSON_SEPARATORS
    ):
        raise HTTPException(status_code=400, detail="Malformed request body.")
    try:
        # Validated straight from bytes: no intermediate dict of the whole body.
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise _validation_error(exc) from exc


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # stop nginx buffering the stream
}


def require_session(session_id: str, user: AuthUser) -> SessionContext:
    """Fetch the caller's session or 404.

    Unknown IDs, and IDs that belong to another user, both 404 with the same
    body, so a caller cannot probe for other people's sessions. The client
    treats `session_not_found` as "make a new session and retry", which also
    recovers transparently from a backend restart.
    """
    session = context_manager.get(session_id, owner_id=user.id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "session_not_found", "message": "Session expired or unknown."},
        )
    return session


def create_session_for(user: AuthUser) -> str:
    try:
        return context_manager.create_session(owner_id=user.id)
    except SessionLimitError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "server_busy", "message": "The server is busy. Try again shortly."},
            headers={"Retry-After": "30"},
        ) from exc
