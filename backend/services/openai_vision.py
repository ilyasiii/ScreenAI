"""
Vision service - screenshot analysis over a streamed chat completion.

Message layout
--------------
The array is deliberately ordered stable-prefix-first:

    [ system ]                          <- fixed for the session
    [ user: every pinned screenshot ]   <- append-only
    [ assistant: acknowledgement ]
    [ ...conversation history... ]      <- append-only
    [ user: current screen + question ] <- the only volatile part

Everything above the last message is byte-identical between consecutive
questions, which is what automatic prompt caching keys on: the provider
matches the longest identical prefix and re-serves it at a fraction of the
input price, with a much shorter time-to-first-token.

The previous layout put the images inside the final user message, after the
conversation history. Because history grew on every turn, the images shifted
position every time and were re-processed in full - the single most expensive
part of the request was the one part that never got cached.
"""

import logging
from typing import AsyncGenerator

from config import settings
from services.credentials import get_openai_client

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a screen-reading assistant. You are shown screenshots of the user's screen and you answer the question that is on it.

READING THE SCREEN
- Read every visible element before answering: the problem statement, the constraints, the worked examples, any error message, the code already present in the editor, and the language the editor is set to.
- Constraints and examples are part of the question. A solution that ignores the stated input limits is wrong.
- Multiple screenshots are one session in chronological order. Reference screenshots came earlier; the image labelled "Current screen" is what the user is looking at now.
- Where screenshots disagree, the current screen wins.
- Do not guess at text you cannot make out. If something essential is illegible, cropped, or scrolled out of view, say so in one short line and answer using what is visible.

ANSWERING
- Give the answer only. Never restate the question, and do not explain your reasoning unless the user asks for an explanation.
- Coding problems: return one complete, runnable solution. Use the language shown in the editor, defaulting to Python if there is no clue. Match the exact class and method signature visible on screen, including the parameter names. Handle the stated constraints and the edge cases the examples imply. Close with a single line giving time and space complexity.
- Multiple choice: give the option letter and the option text. Nothing else.
- Written or theory questions: answer directly in at most three sentences.
- Use fenced code blocks tagged with the language."""


CANDIDATE_PROMPT = """

--- CANDIDATE CONTEXT ---
The user is a candidate interviewing for the role below. When the screen shows an interview or application question about their experience, motivation, or background, answer in the first person as this candidate, drawing on the CV. Prefer concrete specifics from the CV over generic claims, and never invent experience that is not in it.

This changes the voice of behavioural answers only. Technical questions on screen are still answered as above: the solution, nothing else."""


def _image_part(image_b64: str) -> dict:
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{image_b64}",
            # Always explicit. `auto` decides per-image and is not documented to
            # be stable, which made cost and legibility unpredictable - and for
            # a tool whose entire job is reading small on-screen text, `low`
            # (a single 512px tile) is never the right answer.
            "detail": "high",
        },
    }


def _build_system_prompt(profile: dict | None) -> str:
    system = SYSTEM_PROMPT
    if not profile:
        return system

    job_title = (profile.get("job_title") or "").strip()
    job_description = (profile.get("job_description") or "").strip()
    cv_text = (profile.get("cv_text") or "").strip()

    if not (job_title or job_description or cv_text):
        return system

    system += CANDIDATE_PROMPT
    if job_title:
        system += f"\n\nTarget role: {job_title}"
    if job_description:
        system += f"\n\nJob description:\n{job_description[:3000]}"
    if cv_text:
        system += f"\n\nCandidate CV:\n{cv_text[:6000]}"
    return system


def build_messages(
    context_images: list[str],
    current_image: str | None,
    user_question: str | None = None,
    conversation_history: list[dict] | None = None,
    profile: dict | None = None,
) -> list[dict]:
    """Assemble the request. All images must already be prepared JPEG base64."""
    messages: list[dict] = [{"role": "system", "content": _build_system_prompt(profile)}]

    # -- Stable image block ----------------------------------------------
    if context_images:
        parts: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"{len(context_images)} reference screenshot(s) the user pinned earlier "
                    "in this session, oldest first. Use them for anything scrolled off the "
                    "current screen."
                ),
            }
        ]
        for index, image in enumerate(context_images, start=1):
            # Labelling each image lets the model refer to them unambiguously
            # and stops it conflating a reference frame with the live screen.
            parts.append({"type": "text", "text": f"Reference screenshot {index}:"})
            parts.append(_image_part(image))
        messages.append({"role": "user", "content": parts})
        messages.append(
            {"role": "assistant", "content": "Noted. I will use these as background context."}
        )

    # -- History ----------------------------------------------------------
    if conversation_history:
        messages.extend(
            {"role": turn["role"], "content": turn["content"]} for turn in conversation_history
        )

    # -- Volatile tail ----------------------------------------------------
    tail: list[dict] = []
    if current_image:
        tail.append({"type": "text", "text": "Current screen:"})
        tail.append(_image_part(current_image))

    if user_question:
        tail.append({"type": "text", "text": user_question})
    else:
        tail.append(
            {
                "type": "text",
                "text": (
                    "Answer the question shown on the current screen. If there are several, "
                    "answer the one that is focused or highlighted."
                ),
            }
        )

    messages.append({"role": "user", "content": tail})
    return messages


async def analyze_screenshots_stream(
    context_images: list[str],
    current_image: str | None,
    user_question: str | None = None,
    conversation_history: list[dict] | None = None,
    profile: dict | None = None,
    api_key: str = "",
) -> AsyncGenerator[str | dict, None]:
    """Stream the answer token by token.

    `api_key` is resolved by the caller: the server's key when one is
    configured, otherwise the key the user supplied in the browser.

    Yields `str` for content and exactly one `{"__usage__": {...}}` dict at the
    end, if the provider reported usage.
    """
    if not context_images and not current_image:
        raise ValueError("No screenshots provided")
    if not api_key:
        raise RuntimeError("No OpenAI API key available")

    client = get_openai_client(api_key)
    messages = build_messages(
        context_images, current_image, user_question, conversation_history, profile
    )

    stream = await client.chat.completions.create(
        model=settings.vision_model,
        messages=messages,
        max_tokens=settings.vision_max_tokens,
        temperature=settings.vision_temperature,
        stream=True,
        stream_options={"include_usage": True},
    )

    usage_data: dict | None = None
    try:
        async for chunk in stream:
            if chunk.usage:
                usage_data = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                }
                cached = getattr(
                    getattr(chunk.usage, "prompt_tokens_details", None), "cached_tokens", None
                )
                if cached:
                    usage_data["cached_tokens"] = cached
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content
    finally:
        # Whether we finished, errored, or the client hung up mid-answer, close
        # the upstream connection rather than leaving it running and billing
        # for tokens nobody will read.
        await stream.close()

    if usage_data:
        yield {"__usage__": usage_data}
