"""Gemini Vision Service
- Async Gemini client for non-blocking calls
- Streaming support (yields tokens as they arrive)
- Image compression (JPEG, resized) to reduce payload size
- Context images at lower resolution, current screen at full resolution
"""

import os
import io
import base64
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv
from PIL import Image
from typing import AsyncGenerator

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

_api_key = os.getenv("GEMINI_API_KEY", "")
client = genai.Client(api_key=_api_key) if _api_key else None
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Image compression settings ---
MAX_DIMENSION = 1280        # max px for current screenshot
CTX_MAX_DIMENSION = 800     # smaller for older context images
JPEG_QUALITY = 60           # lower = smaller = faster upload & processing


def compress_image(image_b64: str, max_dim: int = MAX_DIMENSION, quality: int = JPEG_QUALITY) -> bytes:
    """Compress a base64 image to a smaller JPEG. Returns raw bytes."""
    if image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]

    raw = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    w, h = img.size
    if w > max_dim or h > max_dim:
        ratio = min(max_dim / w, max_dim / h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# --- System prompt ---
SYSTEM_PROMPT = """You are a fast screen-reading AI that solves problems shown on screen.

Rules:
- ONLY give the answer. NEVER rewrite or repeat the question.
- Do NOT explain unless the user explicitly asks for an explanation.
- For CODING PROBLEMS (LeetCode, GeeksforGeeks, HackerRank, Codeforces, etc.):
  * You MUST provide a complete, working code solution in the required language.
  * Detect the language from the code editor/template visible on screen. Default to python if unclear.
  * Give ONLY the function/solution code ready to submit. No explanation unless asked.
- For MCQs: just state the correct answer letter/option. No reasoning unless asked.
- For written/theory questions: give a direct, concise answer.
- Multiple screenshots = continuous context. Latest = current screen.
- Combine info across screenshots if needed.
- Use markdown code blocks with language tags for code."""


def build_contents(
    context_images: list[str],
    user_question: str | None = None,
) -> list:
    """Build Gemini contents list with compressed images."""
    parts = []

    if len(context_images) > 1:
        parts.append(types.Part(text=f"{len(context_images)} screenshots. Last one is current screen."))

    for i, img_b64 in enumerate(context_images):
        is_current = i == len(context_images) - 1
        max_dim = MAX_DIMENSION if is_current else CTX_MAX_DIMENSION
        quality = JPEG_QUALITY if is_current else 40
        img_bytes = compress_image(img_b64, max_dim, quality)
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

    question_text = user_question or "Analyze the screen. Identify and answer any questions or problems shown."
    parts.append(types.Part(text=question_text))

    return [types.Content(role="user", parts=parts)]


# --- Streaming analysis (yields tokens in real-time) ---

async def analyze_screenshots_stream(
    context_images: list[str],
    user_question: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream the analysis token-by-token. Yields individual text chunks."""
    if not context_images:
        raise ValueError("No screenshots provided")
    if client is None:
        raise RuntimeError("Gemini API key not configured")

    contents = build_contents(context_images, user_question)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        max_output_tokens=4096,
        temperature=0.2,
    )

    stream = await client.aio.models.generate_content_stream(
        model=MODEL,
        contents=contents,
        config=config,
    )
    async for chunk in stream:
        if chunk.text:
            yield chunk.text


# --- Non-streaming fallback ---

async def analyze_screenshots(
    context_images: list[str],
    user_question: str | None = None,
) -> dict:
    """Non-streaming version (kept for backward compat)."""
    if not context_images:
        raise ValueError("No screenshots provided for analysis")
    if client is None:
        raise RuntimeError("Gemini API key not configured. Set GEMINI_API_KEY in backend/.env")

    contents = build_contents(context_images, user_question)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        max_output_tokens=4096,
        temperature=0.2,
    )

    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=contents,
        config=config,
    )

    usage_meta = response.usage_metadata
    usage = {
        "prompt_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
        "completion_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
        "total_tokens": getattr(usage_meta, "total_token_count", 0) or 0,
    }
    return {"answer": response.text, "model": MODEL, "usage": usage}
