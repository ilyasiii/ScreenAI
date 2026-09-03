"""
Voice answer generation.

Consumes transcripts, keeps a rolling conversation memory, streams tokens back
through callbacks. Supports openai | groq | anthropic.

Each provider now reads its own API key. The previous build read
OPENAI_API_KEY regardless of `LLM_PROVIDER`, so selecting groq or anthropic
meant putting that provider's key in the OpenAI variable - which then broke
screenshot analysis, since vision reads the same variable.
"""

import logging
import queue
import threading
from collections import deque

from config import settings

logger = logging.getLogger(__name__)

LLM_MEMORY_TURNS = 10
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


class LLMClient:
    """Unified streaming interface across the three supported providers."""

    def __init__(self, api_key: str):
        self.provider = settings.llm_provider
        self.model = settings.llm_model

        if self.provider not in ("openai", "groq", "anthropic"):
            raise ValueError(
                f"Unknown LLM_PROVIDER '{self.provider}'. "
                "Expected one of: openai, groq, anthropic."
            )
        if not api_key:
            raise ValueError(f"No API key available for LLM_PROVIDER '{self.provider}'.")

        if self.provider == "openai":
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key)
        elif self.provider == "groq":
            from groq import Groq

            self._client = Groq(api_key=api_key)
        elif self.provider == "anthropic":
            try:
                import anthropic
            except ImportError as exc:
                raise ValueError(
                    "LLM_PROVIDER=anthropic requires the anthropic package: pip install anthropic"
                ) from exc
            self._client = anthropic.Anthropic(api_key=api_key)
        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{self.provider}'. Expected one of: openai, groq, anthropic."
            )

        logger.info("Voice LLM provider: %s | model: %s", self.provider, self.model)

    def stream(self, messages: list[dict]):
        if self.provider == "anthropic":
            return self._stream_anthropic(messages)
        return self._stream_openai_compat(messages)

    def _stream_openai_compat(self, messages):
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            stream=True,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def _stream_anthropic(self, messages):
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        with self._client.messages.stream(
            model=self.model,
            max_tokens=LLM_MAX_TOKENS,
            system=system_msg,
            messages=user_msgs,
        ) as stream:
            yield from stream.text_stream


class VoiceLLMResponder:
    """Worker thread: transcript in, streamed answer out."""

    def __init__(
        self,
        llm_queue: queue.Queue,
        on_token_cb=None,
        on_answer_start_cb=None,
        on_answer_end_cb=None,
        on_error_cb=None,
        profile: dict | None = None,
        api_key: str = "",
    ):
        self.llm_queue = llm_queue
        self.on_token_cb = on_token_cb
        self.on_answer_start_cb = on_answer_start_cb
        self.on_answer_end_cb = on_answer_end_cb
        self.on_error_cb = on_error_cb

        self._profile = profile
        self._system_prompt = build_system_prompt(profile)
        self._memory: deque[dict] = deque(maxlen=LLM_MEMORY_TURNS * 2)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._llm = LLMClient(api_key)

    def set_profile(self, profile: dict | None):
        self._profile = profile
        self._system_prompt = build_system_prompt(profile)
        logger.info("Voice LLM profile updated.")

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="Thread-VoiceLLM", daemon=True)
        self._thread.start()
        logger.info("VoiceLLMResponder thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("VoiceLLMResponder stopped.")

    def clear_memory(self):
        self._memory.clear()
        logger.info("Voice conversation memory cleared.")

    def _build_messages(self, user_text: str) -> list[dict]:
        return [
            {"role": "system", "content": self._system_prompt},
            *self._memory,
            {"role": "user", "content": user_text},
        ]

    def _run(self):
        while not self._stop_event.is_set():
            try:
                transcript = self.llm_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            logger.info("Generating answer for: %s", transcript[:80])
            if self.on_answer_start_cb:
                self.on_answer_start_cb()

            parts: list[str] = []
            try:
                for token in self._llm.stream(self._build_messages(transcript)):
                    parts.append(token)
                    if self.on_token_cb:
                        self.on_token_cb(token)

                answer = "".join(parts)
                if answer.strip():
                    # deque(maxlen=...) evicts oldest-first on append, so the
                    # window trims itself without a manual popleft loop.
                    self._memory.append({"role": "user", "content": transcript})
                    self._memory.append({"role": "assistant", "content": answer})

                if self.on_answer_end_cb:
                    self.on_answer_end_cb()
            except Exception as exc:  # noqa: BLE001
                logger.error("Voice LLM error: %s", exc, exc_info=True)
                if self.on_error_cb:
                    self.on_error_cb("Could not generate an answer. Check the backend log.")
