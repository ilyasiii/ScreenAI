"""
Transcription - Groq-hosted whisper-large-v3.

The browser records each push-to-talk utterance itself (WebM/Opus in Chrome
and Firefox, MP4/AAC in Safari) and uploads the clip. Whisper accepts those
containers directly, so the server does no decoding or resampling of its own.

Accuracy note: Whisper accepts a `prompt` that biases decoding toward a
vocabulary. Feeding it the target job title and a handful of terms lifted from
the job description is what makes it write "Kubernetes" and "PostgreSQL"
instead of "Cubernetties" and "post-gress" - which matters, because the LLM
downstream only ever sees the transcript.
"""

import logging
import re

from config import settings
from services.credentials import get_groq_client

logger = logging.getLogger(__name__)

# Whisper's prompt window is small; overrunning it silently truncates.
MAX_PROMPT_CHARS = 800

# Containers MediaRecorder produces across browsers, mapped to the extension
# Whisper uses to pick a demuxer.
AUDIO_TYPES = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}

# Whisper's well-known output on near-silent clips. Answering "Thank you." as
# if the interviewer had asked something is worse than answering nothing.
_SILENCE_HALLUCINATIONS = {
    "",
    "you",
    "thank you",
    "thank you.",
    "thanks for watching!",
    "thanks for watching.",
    ".",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{2,}")
_STOPWORDS = {
    "and", "the", "for", "with", "you", "your", "our", "are", "will", "have",
    "has", "this", "that", "from", "they", "their", "who", "what", "which",
    "role", "team", "work", "working", "years", "experience", "ability",
    "strong", "including", "such", "help", "must", "should", "would", "can",
    "job", "candidate", "position", "company", "about", "requirements",
}


def audio_extension(content_type: str | None) -> str | None:
    """File extension for an allowed audio MIME type, else None."""
    base = (content_type or "").split(";", 1)[0].strip().lower()
    return AUDIO_TYPES.get(base)


def build_asr_prompt(profile: dict | None) -> str:
    """A short vocabulary hint for Whisper, derived from the user's profile."""
    if not profile:
        return ""

    fragments: list[str] = []
    job_title = (profile.get("job_title") or "").strip()
    if job_title:
        fragments.append(f"A technical interview for a {job_title} position.")

    # Distinctive terms from the job description: capitalised names and
    # tech-shaped tokens are the ones Whisper is most likely to mangle.
    source = f"{profile.get('job_description') or ''} {profile.get('cv_text') or ''}"
    seen: dict[str, None] = {}
    for match in _WORD_RE.findall(source):
        if match.lower() in _STOPWORDS:
            continue
        # Keep things that look like proper nouns or tech tokens.
        if match[0].isupper() or any(c in match for c in "+#./-"):
            seen.setdefault(match, None)
        if len(seen) >= 40:
            break

    if seen:
        fragments.append("Terms that may come up: " + ", ".join(seen) + ".")

    return " ".join(fragments)[:MAX_PROMPT_CHARS]


def is_silence(transcript: str) -> bool:
    return transcript.strip().lower() in _SILENCE_HALLUCINATIONS


async def transcribe(
    audio: bytes,
    extension: str,
    api_key: str,
    profile: dict | None = None,
) -> str:
    """Transcribe one recorded utterance. Returns the stripped text."""
    kwargs = {
        "file": (f"audio.{extension}", audio),
        "model": settings.asr_model,
        # "json", not "text": the SDK runs a plain-text reply through a JSON
        # decoder, so a transcript like "42" or "null" came back as a number
        # or None instead of a string.
        "response_format": "json",
        # Greedy decoding. Whisper's default samples, which on short
        # utterances is where its hallucinated filler comes from.
        "temperature": 0.0,
    }
    if settings.asr_language:
        kwargs["language"] = settings.asr_language
    prompt = build_asr_prompt(profile)
    if prompt:
        kwargs["prompt"] = prompt

    response = await get_groq_client(api_key).audio.transcriptions.create(**kwargs)
    return (getattr(response, "text", None) or "").strip()
