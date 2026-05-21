"""
Voice LLM Service — Streaming Interview Assistant
Consumes transcript strings from LLM queue.
Maintains rolling conversation memory.
Streams tokens via callbacks.
Supports: openai | groq | anthropic
"""

import queue
import threading
import logging
import os
from collections import deque

logger = logging.getLogger(__name__)

LLM_MEMORY_TURNS = 10
LLM_MAX_TOKENS = 1024
LLM_TEMPERATURE = 0.4

LLM_SYSTEM_PROMPT_BASE = (
    "You are an expert interview assistant. "
    "When given a question or statement from an interviewer, "
    "respond with a clear, concise, structured answer. "
    "Use the STAR method for behavioural questions. "
    "Keep answers under 150 words unless the question demands more detail. "
    "Do NOT mention that you are an AI or that you are assisting anyone."
)


def build_system_prompt(profile: dict | None = None) -> str:
    """Build system prompt incorporating optional user profile data."""
    if not profile:
        return LLM_SYSTEM_PROMPT_BASE

    parts = [LLM_SYSTEM_PROMPT_BASE, "\n\n--- CANDIDATE CONTEXT ---"]

    job_title = profile.get("job_title", "").strip()
    job_description = profile.get("job_description", "").strip()
    cv_text = profile.get("cv_text", "").strip()

    if job_title:
        parts.append(f"\nJob Title: {job_title}")
    if job_description:
        parts.append(f"\nJob Description:\n{job_description[:3000]}")
    if cv_text:
        parts.append(f"\nCandidate CV/Resume:\n{cv_text[:4000]}")

    parts.append(
        "\n\n--- INSTRUCTIONS ---\n"
        "Use the candidate context above to tailor your answers. "
        "Match your responses to the job requirements and highlight relevant experience from the CV. "
        "If the interviewer asks about specific skills or experience, reference the CV details. "
        "Answer as if YOU are the candidate being interviewed for this role."
    )
    return "".join(parts)


class LLMClient:
    """Unified streaming LLM interface for OpenAI/Groq/Anthropic."""

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "gpt-4.1")

        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in backend .env file.")

        if self.provider == "openai":
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key)
        elif self.provider == "groq":
            from groq import Groq
            self._client = Groq(api_key=api_key)
        elif self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unknown LLM_PROVIDER '{self.provider}'.")

        logger.info("Voice LLM provider: %s | model: %s", self.provider, self.model)

    def stream(self, messages: list[dict]):
        if self.provider in ("openai", "groq"):
            return self._stream_openai_compat(messages)
        elif self.provider == "anthropic":
            return self._stream_anthropic(messages)

    def _stream_openai_compat(self, messages):
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def _stream_anthropic(self, messages):
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        user_msgs = [m for m in messages if m["role"] != "system"]
        with self._client.messages.stream(
            model=self.model,
            max_tokens=LLM_MAX_TOKENS,
            system=system_msg,
            messages=user_msgs,
        ) as stream:
            for text in stream.text_stream:
                yield text


class VoiceLLMResponder:
    """
    Reads transcript strings from llm_queue.
    Manages conversation memory.
    Streams LLM tokens via callbacks.
    """

    def __init__(
        self,
        llm_queue: queue.Queue,
        on_token_cb=None,
        on_answer_start_cb=None,
        on_answer_end_cb=None,
        on_error_cb=None,
        profile: dict | None = None,
    ):
        self.llm_queue = llm_queue
        self.on_token_cb = on_token_cb
        self.on_answer_start_cb = on_answer_start_cb
        self.on_answer_end_cb = on_answer_end_cb
        self.on_error_cb = on_error_cb
        self._profile = profile

        self._system_prompt = build_system_prompt(profile)
        self._memory: deque[dict] = deque()
        self._stop_event = threading.Event()
        self._thread = None
        self._llm = LLMClient()

    def set_profile(self, profile: dict | None):
        """Update profile and rebuild system prompt."""
        self._profile = profile
        self._system_prompt = build_system_prompt(profile)
        logger.info("Voice LLM profile updated.")

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="Thread-VoiceLLM", daemon=True
        )
        self._thread.start()
        logger.info("VoiceLLMResponder thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("VoiceLLMResponder stopped.")

    def clear_memory(self):
        self._memory.clear()
        logger.info("Voice conversation memory cleared.")

    def _build_messages(self, user_text: str) -> list[dict]:
        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(list(self._memory))
        messages.append({"role": "user", "content": user_text})
        return messages

    def _run(self):
        while not self._stop_event.is_set():
            try:
                transcript = self.llm_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            logger.info("Generating answer for: %s", transcript[:80])

            if self.on_answer_start_cb:
                self.on_answer_start_cb()

            messages = self._build_messages(transcript)
            full_answer = []

            try:
                for token in self._llm.stream(messages):
                    full_answer.append(token)
                    if self.on_token_cb:
                        self.on_token_cb(token)

                answer_text = "".join(full_answer)

                self._memory.append({"role": "user", "content": transcript})
                self._memory.append({"role": "assistant", "content": answer_text})

                max_msgs = LLM_MEMORY_TURNS * 2
                while len(self._memory) > max_msgs:
                    self._memory.popleft()

                if self.on_answer_end_cb:
                    self.on_answer_end_cb()

            except Exception as exc:
                logger.error("Voice LLM error: %s", exc, exc_info=True)
                if self.on_error_cb:
                    self.on_error_cb(str(exc))
