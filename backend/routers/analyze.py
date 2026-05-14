"""
Analyze Router - with SSE streaming for fast perceived response
"""

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import uuid

from services.context_manager import context_manager
from services.gemini_vision import analyze_screenshots, analyze_screenshots_stream

router = APIRouter(tags=["analyze"])


# --- Request / Response Models ---

class ScreenshotRequest(BaseModel):
    session_id: str
    image_base64: str

class AnalyzeRequest(BaseModel):
    session_id: str
    image_base64: Optional[str] = None
    question: Optional[str] = None

class AnalyzeResponse(BaseModel):
    answer: str
    model: str
    context_count: int
    usage: dict

class SessionResponse(BaseModel):
    session_id: str

class ContextStatusResponse(BaseModel):
    session_id: str
    screenshot_count: int
    max_context: int


# --- Endpoints ---

@router.post("/session/create", response_model=SessionResponse)
async def create_session():
    session_id = str(uuid.uuid4())
    context_manager.get_session(session_id)
    return SessionResponse(session_id=session_id)


@router.post("/screenshot/add")
async def add_screenshot(req: ScreenshotRequest):
    if not req.image_base64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    count = context_manager.add_screenshot(req.session_id, req.image_base64)
    return {"status": "ok", "context_count": count, "session_id": req.session_id}


@router.post("/analyze/stream")
async def analyze_stream(req: AnalyzeRequest):
    """
    SSE streaming endpoint - tokens arrive in real-time.
    Current screenshot is NOT stored in context. Context only from /screenshot/add.
    """
    context_images = context_manager.get_context_images(req.session_id)
    all_images = list(context_images)
    if req.image_base64:
        all_images.append(req.image_base64)
    if not all_images:
        raise HTTPException(status_code=400, detail="No screenshot provided.")

    async def event_generator():
        try:
            async for token in analyze_screenshots_stream(all_images, req.question):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True, 'context_count': len(context_images)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if behind proxy
        },
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """Non-streaming fallback."""
    context_images = context_manager.get_context_images(req.session_id)
    all_images = list(context_images)
    if req.image_base64:
        all_images.append(req.image_base64)
    if not all_images:
        raise HTTPException(status_code=400, detail="No screenshot provided.")

    try:
        result = await analyze_screenshots(all_images, req.question)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return AnalyzeResponse(
        answer=result["answer"],
        model=result["model"],
        context_count=len(context_images),
        usage=result["usage"],
    )


@router.get("/context/status/{session_id}", response_model=ContextStatusResponse)
async def context_status(session_id: str):
    session = context_manager.get_session(session_id)
    return ContextStatusResponse(
        session_id=session_id,
        screenshot_count=session.get_context_count(),
        max_context=session.max_screenshots,
    )


@router.post("/context/clear/{session_id}")
async def clear_context(session_id: str):
    context_manager.clear_session(session_id)
    return {"status": "ok", "message": "Context cleared"}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    context_manager.delete_session(session_id)
    return {"status": "ok", "message": "Session deleted"}
