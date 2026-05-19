"""OpenAI Vision Service - FAST edition
- Async OpenAI client for non-blocking calls
- Streaming support (yields tokens as they arrive)
- Image compression (JPEG, resized) to slash payload size + token cost
- Low-detail mode for context images, high-detail only for current screen
"""

import os
import io
import asyncio
import base64
from pathlib import Path
from openai import AsyncOpenAI
from dotenv import load_dotenv
from PIL import Image
from typing import AsyncGenerator

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

_api_key = os.getenv("OPENAI_API_KEY", "")
if _api_key and _api_key != "sk-your-api-key-here":
    client = AsyncOpenAI(api_key=_api_key)
else:
    client = None
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")

# --- Image compression settings ---
MAX_DIMENSION = 1280        # max px for current screenshot
CTX_MAX_DIMENSION = 800     # smaller for older context images
JPEG_QUALITY = 60           # lower = smaller = faster upload & processing


def compress_image(image_b64: str, max_dim: int = MAX_DIMENSION, quality: int = JPEG_QUALITY) -> str:
    """Compress a base64 image to a smaller JPEG. Returns raw base64 (no prefix)."""
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
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# --- System prompt (shorter = fewer prompt tokens = faster) ---
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


def build_messages(
    context_images: list[str],
    current_image: str | None,
    user_question: str | None = None,
    conversation_history: list[dict] | None = None,
) -> list[dict]:
    """Assemble the OpenAI message array. All images must be pre-compressed base64 JPEGs."""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Inject previous Q&A turns as plain text so the AI has conversation memory
    if conversation_history:
        for turn in conversation_history:
            messages.append({"role": turn["role"], "content": turn["content"]})

    content_parts: list[dict] = []

    total_images = len(context_images) + (1 if current_image else 0)
    if total_images > 1:
        content_parts.append({
            "type": "text",
            "text": f"{total_images} screenshots. Last one is current screen.",
        })

    # Context screenshots — pre-compressed at storage time, auto detail
    for img_b64 in context_images:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}", "detail": "auto"},
        })

    # Current screenshot — pre-compressed in stream function, high detail
    if current_image:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{current_image}", "detail": "high"},
        })

    if user_question:
        content_parts.append({"type": "text", "text": user_question})
    else:
        content_parts.append({
            "type": "text",
            "text": "Analyze the screen. Identify and answer any questions or problems shown.",
        })

    messages.append({"role": "user", "content": content_parts})
    return messages


# --- Streaming analysis (yields tokens in real-time) ---

async def analyze_screenshots_stream(
    context_images: list[str],
    current_image: str | None,
    user_question: str | None = None,
    conversation_history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream analysis token-by-token.
    Context images must be pre-compressed (stored that way in SessionContext).
    Current image is compressed here in a thread pool so PIL never blocks the event loop.
    """
    if not context_images and not current_image:
        raise ValueError("No screenshots provided")
    if client is None:
        raise RuntimeError("OpenAI API key not configured")

    # Compress current screenshot off the event loop (CPU-bound PIL work)
    current_compressed: str | None = None
    if current_image:
        loop = asyncio.get_running_loop()
        current_compressed = await loop.run_in_executor(
            None, compress_image, current_image, MAX_DIMENSION, JPEG_QUALITY
        )

    messages = build_messages(context_images, current_compressed, user_question, conversation_history)

    stream = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=4096,
        temperature=0.2,
        stream=True,
        stream_options={"include_usage": True},
    )

    usage_data = None
    async for chunk in stream:
        if chunk.usage:
            usage_data = {
                "prompt_tokens": chunk.usage.prompt_tokens,
                "completion_tokens": chunk.usage.completion_tokens,
                "total_tokens": chunk.usage.total_tokens,
            }
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content

    if usage_data:
        yield {"__usage__": usage_data}
