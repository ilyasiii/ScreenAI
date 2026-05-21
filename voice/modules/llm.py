"""
modules/llm.py
Thread 4 — LLM Response Generation

Consumes transcript strings from LLM_QUEUE.
Maintains a rolling conversation memory (last N turns).
Calls the configured LLM API with streaming enabled.
Fires token-by-token callbacks so the UI can render answers as they arrive.

Supports providers: openai | groq | anthropic
"""

import queue
import threading
import logging
import os
from collections import deque
from dotenv import load_dotenv

import config

load_dotenv()
logger = logging.getLogger(__name__)


class LLMClient:
    """
    Wraps OpenAI / Groq / Anthropic in a unified streaming interface.
    Returns an iterator of token strings.
    """

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        api_key       = os.getenv("LLM_API_KEY", "")
        self.model    = os.getenv("LLM_MODEL", config.__dict__.get("LLM_MODEL", "gpt-4o"))

        if not api_key:
            raise ValueError("LLM_API_KEY not set in .env file.")

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
            raise ValueError(
                f"Unknown LLM_PROVIDER '{self.provider}'. "
                "Choose: openai | groq | anthropic"
            )

        logger.info("LLM provider: %s | model: %s", self.provider, self.model)

    def stream(self, messages: list[dict]) -> "Iterator[str]":
        """Stream tokens from the LLM. Yields one string token at a time."""
        if self.provider in ("openai", "groq"):
            return self._stream_openai_compat(messages)
        elif self.provider == "anthropic":
            return self._stream_anthropic(messages)

    def _stream_openai_compat(self, messages):
        response = self._client.chat.completions.create(
            model       = self.model,
            messages    = messages,
            max_tokens  = config.LLM_MAX_TOKENS,
            temperature = config.LLM_TEMPERATURE,
            stream      = True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def _stream_anthropic(self, messages):
        # Anthropic uses a separate system message
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        user_msgs = [m for m in messages if m["role"] != "system"]

        with self._client.messages.stream(
            model      = self.model,
            max_tokens = config.LLM_MAX_TOKENS,
            system     = system_msg,
            messages   = user_msgs,
        ) as stream:
            for text in stream.text_stream:
                yield text


class LLMResponder:
    """
    Reads transcript strings from llm_queue.
    Manages conversation memory.
    Streams LLM tokens via callbacks to the UI.
    """

    def __init__(
        self,
        llm_queue:       queue.Queue,
        on_token_cb      = None,   # called with (token: str) for each streamed token
        on_answer_start_cb = None, # called when generation begins
        on_answer_end_cb   = None, # called when generation completes
        on_error_cb        = None, # called with (error: str)
    ):
        self.llm_queue          = llm_queue
        self.on_token_cb        = on_token_cb
        self.on_answer_start_cb = on_answer_start_cb
        self.on_answer_end_cb   = on_answer_end_cb
        self.on_error_cb        = on_error_cb

        self._memory     : deque[dict] = deque()   # user+assistant turns only
        self._stop_event = threading.Event()
        self._thread     = threading.Thread(
            target=self._run, name="Thread-LLM", daemon=True
        )
        self._llm = LLMClient()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self._thread.start()
        logger.info("LLMResponder thread started.")

    def stop(self):
        self._stop_event.set()
        logger.info("LLMResponder stopped.")

    def clear_memory(self):
        """Reset conversation history (e.g. new interview session)."""
        self._memory.clear()
        logger.info("Conversation memory cleared.")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_messages(self, user_text: str) -> list[dict]:
        """Combine system prompt + rolling memory + new user message."""
        messages = [{"role": "system", "content": config.LLM_SYSTEM_PROMPT}]
        messages.extend(list(self._memory))
        messages.append({"role": "user", "content": user_text})
        return messages

    def _run(self):
        logger.info("LLMResponder waiting for transcripts…")
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
                logger.info(
                    "Answer complete (%d chars).", len(answer_text)
                )

                # Store in rolling memory
                self._memory.append(
                    {"role": "user", "content": transcript}
                )
                self._memory.append(
                    {"role": "assistant", "content": answer_text}
                )

                # Keep only last N turns (each turn = 2 messages)
                max_msgs = config.LLM_MEMORY_TURNS * 2
                while len(self._memory) > max_msgs:
                    self._memory.popleft()

                if self.on_answer_end_cb:
                    self.on_answer_end_cb()

            except Exception as exc:
                logger.error("LLM error: %s", exc, exc_info=True)
                if self.on_error_cb:
                    self.on_error_cb(str(exc))

        logger.info("LLMResponder thread exiting.")
