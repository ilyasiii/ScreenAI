"""
Session state: the screenshots a session has pinned as context, plus a rolling
window of conversation history.

Three deliberate changes from the previous implementation:

  * Sessions are created explicitly. The old store was a `defaultdict`, so any
    unrecognised UUID silently minted a session — which meant a guessed ID
    returned somebody else's screenshots instead of an error.
  * Screenshots are bounded. The old list grew forever, so a long session got
    progressively slower and more expensive with every frame pinned.
  * Near-identical frames are rejected. Pinning the same static page twice used
    to store and bill it twice, and gave the model two copies to reconcile.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field

from config import settings
from services.image_utils import is_duplicate


@dataclass
class Screenshot:
    """A context frame, already resized and encoded for the vision API."""

    image_b64: str
    phash: int
    estimated_tokens: int = 0
    added_at: float = field(default_factory=time.time)


class SessionContext:
    """Screenshot context and conversation history for one session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.screenshots: list[Screenshot] = []
        self.conversation: list[dict] = []
        self.last_activity: float = time.time()
        self._lock = threading.Lock()

    # ── Screenshots ──────────────────────────────────────────────────────

    def add_screenshot(self, image_b64: str, phash: int, estimated_tokens: int = 0) -> dict:
        """Pin a frame as context.

        Returns a result dict describing what happened, so the caller can tell
        the user their capture was a duplicate rather than silently doing
        nothing.
        """
        with self._lock:
            self.last_activity = time.time()

            for existing in self.screenshots:
                if is_duplicate(existing.phash, phash):
                    return {
                        "added": False,
                        "reason": "duplicate",
                        "count": len(self.screenshots),
                    }

            self.screenshots.append(
                Screenshot(image_b64=image_b64, phash=phash, estimated_tokens=estimated_tokens)
            )

            evicted = 0
            while len(self.screenshots) > settings.max_context_images:
                self.screenshots.pop(0)
                evicted += 1

            return {
                "added": True,
                "reason": "evicted_oldest" if evicted else None,
                "count": len(self.screenshots),
            }

    def context_images(self) -> list[str]:
        with self._lock:
            self.last_activity = time.time()
            return [s.image_b64 for s in self.screenshots]

    def context_hashes(self) -> list[int]:
        with self._lock:
            return [s.phash for s in self.screenshots]

    def context_tokens(self) -> int:
        with self._lock:
            return sum(s.estimated_tokens for s in self.screenshots)

    def clear_screenshots(self) -> None:
        """Drop pinned frames. Conversation history survives, so follow-up
        questions still resolve pronouns from earlier answers."""
        with self._lock:
            self.screenshots = []
            self.last_activity = time.time()

    # ── Conversation ─────────────────────────────────────────────────────

    def add_exchange(self, question: str, answer: str) -> None:
        """Record one completed Q&A turn."""
        with self._lock:
            self.last_activity = time.time()
            self.conversation.append({"role": "user", "content": question})
            self.conversation.append({"role": "assistant", "content": answer})
            excess = len(self.conversation) - settings.max_conversation_messages
            if excess > 0:
                # Drop whole pairs so the transcript never starts mid-exchange
                # with an assistant reply to a question the model cannot see.
                self.conversation = self.conversation[excess + (excess % 2):]

    def conversation_history(self) -> list[dict]:
        with self._lock:
            self.last_activity = time.time()
            return list(self.conversation)

    def touch(self) -> None:
        with self._lock:
            self.last_activity = time.time()


class ContextManager:
    """Owns every live session."""

    def __init__(self):
        self._sessions: dict[str, SessionContext] = {}
        self._lock = threading.Lock()

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        with self._lock:
            self._sessions[session_id] = SessionContext(session_id)
        return session_id

    def get(self, session_id: str) -> SessionContext | None:
        """Look up a session. Returns None for unknown IDs — it never creates
        one, so callers can 404 instead of leaking a fresh empty session."""
        with self._lock:
            return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def cleanup_old_sessions(self, max_age_seconds: int | None = None) -> int:
        """Evict sessions idle past the TTL. Returns how many went."""
        max_age = max_age_seconds or settings.session_ttl_seconds
        cutoff = time.time() - max_age
        with self._lock:
            stale = [sid for sid, ctx in self._sessions.items() if ctx.last_activity < cutoff]
            for sid in stale:
                del self._sessions[sid]
        return len(stale)

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)


context_manager = ContextManager()
