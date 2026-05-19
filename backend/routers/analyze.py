"""
Analyze Router - with SSE streaming for fast perceived response
"""

import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import uuid

from services.context_manager import context_manager
from services.openai_vision import analyze_screenshots_stream, compress_image, CTX_MAX_DIMENSION

router = APIRouter(tags=["analyze"])


# --- Request / Response Models ---

class ScreenshotRequest(BaseModel):
    session_id: str
    image_base64: str

class AnalyzeRequest(BaseModel):
    session_id: str
    image_base64: Optional[str] = None
    question: Optional[str] = None

class SessionResponse(BaseModel):
    session_id: str


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
    # Compress to context quality in a thread pool — non-blocking, result cached
    # for all future analyze requests (never recompressed again)
    loop = asyncio.get_running_loop()
    compressed = await loop.run_in_executor(
        None, compress_image, req.image_base64, CTX_MAX_DIMENSION, 40
    )
    count = context_manager.add_screenshot(req.session_id, compressed)
    return {"status": "ok", "context_count": count, "session_id": req.session_id}


@router.post("/analyze/stream")
async def analyze_stream(req: AnalyzeRequest):
    """
    SSE streaming endpoint - tokens arrive in real-time.
    Current screenshot is NOT stored in context. Context only from /screenshot/add.
    """
    context_images = context_manager.get_context_images(req.session_id)
    conv_history = context_manager.get_conversation_history(req.session_id)
    if not context_images and not req.image_base64:
        raise HTTPException(status_code=400, detail="No screenshot provided.")

    async def event_generator():
        try:
            usage = None
            full_response = ""
            async for token in analyze_screenshots_stream(context_images, req.image_base64, req.question, conv_history):
                if isinstance(token, dict) and "__usage__" in token:
                    usage = token["__usage__"]
                else:
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
            # Save every Q&A turn to conversation history so follow-up analyzes
            # ("now optimize the above solution") have the prior context they need.
            user_text = req.question or "Analyze the screen."
            context_manager.add_message(req.session_id, "user", user_text)
            context_manager.add_message(req.session_id, "assistant", full_response)
            done_data: dict = {"done": True, "context_count": len(context_images)}
            if usage:
                done_data["usage"] = usage
            yield f"data: {json.dumps(done_data)}\n\n"
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


@router.post("/context/clear/{session_id}")
async def clear_context(session_id: str):
    context_manager.clear_session(session_id)
    return {"status": "ok", "message": "Context cleared"}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    context_manager.delete_session(session_id)
    return {"status": "ok", "message": "Session deleted"}
