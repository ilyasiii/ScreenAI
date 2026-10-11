"""
Voice answer generation.

Takes a transcript plus the session's conversation memory and streams the
answer. Supports openai | groq | anthropic.

Each provider now reads its own API key. The previous build read
OPENAI_API_KEY regardless of `LLM_PROVIDER`, so selecting groq or anthropic
meant putting that provider's key in the OpenAI variable - which then broke
screenshot analysis, since vision reads the same variable.
"""

import logging
from typing import AsyncIterator

from config import settings
from services.credentials import get_groq_client, get_openai_client

logger = logging.getLogger(__name__)

LLM_MAX_TOKENS = 1024
LLM_TEMPERATURE = 0.4

SYSTEM_PROMPT_BASE = (
    "You are helping a candidate answer questions in a live interview.\n\n"
    "The input you receive is an automatic transcript of what the interviewer "
    "just said, so it may contain small recognition errors. Infer the intended "
    "question from context and answer that. If the transcript is too garbled to "
    "be sure what was asked, say so in one short line rather than answering the "
    "wrong question.\n\n"
    "Answer in the first person, as the candidate. Be direct and specific. Use "
    "the STAR structure for behavioural questions, kept tight - situation and "
    "task in one sentence each, then action and result. Keep answers under 150 "
    "words unless the question genuinely needs more. Never mention that you are "
    "an AI or that anyone is being assisted."
)


def build_system_prompt(profile: dict | None = None) -> str:
    if not profile:
        return SYSTEM_PROMPT_BASE

    job_title = (profile.get("job_title") or "").strip()
    job_description = (profile.get("job_description") or "").strip()
    cv_text = (profile.get("cv_text") or "").strip()

    if not (job_title or job_description or cv_text):
        return SYSTEM_PROMPT_BASE

    parts = [SYSTEM_PROMPT_BASE, "\n\n--- CANDIDATE CONTEXT ---"]
    if job_title:
        parts.append(f"\nTarget role: {job_title}")
    if job_description:
        parts.append(f"\n\nJob description:\n{job_description[:3000]}")
    if cv_text:
        parts.append(f"\n\nCandidate CV:\n{cv_text[:4000]}")
    parts.append(
        "\n\n--- INSTRUCTIONS ---\n"
        "Ground every answer in the CV above. When the interviewer asks about a "
        "skill or a project, cite the specific one from the CV rather than "
        "describing it generically, and connect it to what the job description "
        "asks for. Do not invent experience that is not in the CV: if the CV "
        "does not cover what was asked, say what the candidate has done that is "
        "closest and be honest about the gap."
    )
    return "".join(parts)


SUPPORTED_PROVIDERS = ("openai", "groq", "anthropic")


class VoiceConfigError(Exception):
    """The server's voice configuration cannot work. Safe to show users."""


_anthropic_base = None


def _anthropic_client(api_key: str):
    global _anthropic_base
    try:
        import anthropic
    except ImportError as exc:
        raise VoiceConfigError(
            "LLM_PROVIDER=anthropic requires the anthropic package: pip install anthropic"
        ) from exc
    if _anthropic_base is None:
        _anthropic_base = anthropic.AsyncAnthropic(api_key="unused", max_retries=1)
    return _anthropic_base.with_options(api_key=api_key)


def build_messages(
    transcript: str, history: list[dict], profile: dict | None = None
) -> list[dict]:
    return [
        {"role": "system", "content": build_system_prompt(profile)},
        *history,
        {"role": "user", "content": transcript},
    ]


async def stream_answer(messages: list[dict], api_key: str) -> AsyncIterator[str]:
    """Stream answer text from the configured provider."""
    provider = settings.llm_provider
    if provider not in SUPPORTED_PROVIDERS:
        raise VoiceConfigError(
            f"Unknown LLM_PROVIDER '{provider}'. Expected one of: openai, groq, anthropic."
        )
    if not api_key:
        raise VoiceConfigError(f"No API key available for LLM_PROVIDER '{provider}'.")

    if provider == "anthropic":
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        turns = [m for m in messages if m["role"] != "system"]
        async with _anthropic_client(api_key).messages.stream(
            model=settings.llm_model,
            max_tokens=LLM_MAX_TOKENS,
            system=system,
            messages=turns,
        ) as stream:
            async for text in stream.text_stream:
                yield text
        return

    client = get_openai_client(api_key) if provider == "openai" else get_groq_client(api_key)
    stream = await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
        stream=True,
    )
    try:
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
    finally:
        # Stop billing for tokens nobody will read if the client hung up.
        await stream.close()
