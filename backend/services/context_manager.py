"""
Context Manager Service
Maintains all screenshots added to context plus a rolling window of
conversation history so the AI has full context across a session.
"""

import time
from collections import defaultdict

# Keep last 10 messages (5 Q&A pairs) of conversation text per session
MAX_CONVERSATION = 10


class SessionContext:
    """Manages screenshot context and conversation history for a single user session."""

    def __init__(self):
        self.screenshots: list[str] = []
        self.last_activity: float = time.time()
        # Stores {"role": "user"|"assistant", "content": "..."} pairs
        self.conversation_history: list[dict] = []

    def add_screenshot(self, image_base64: str) -> int:
        self.last_activity = time.time()
        self.screenshots.append(image_base64)
        return len(self.screenshots)

    def get_context_images(self) -> list[str]:
        self.last_activity = time.time()
        return list(self.screenshots)

    def add_message(self, role: str, content: str):
        """Append a Q&A turn. Keeps only the last MAX_CONVERSATION messages."""
        self.last_activity = time.time()
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > MAX_CONVERSATION:
            self.conversation_history = self.conversation_history[-MAX_CONVERSATION:]

    def get_conversation_history(self) -> list[dict]:
        return list(self.conversation_history)

    def clear_screenshots(self):
        """Clear only stored screenshots. Conversation history is preserved."""
        self.screenshots = []


class ContextManager:
    """Manages contexts for multiple sessions."""

    def __init__(self):
        self._sessions: dict[str, SessionContext] = defaultdict(SessionContext)

    def get_session(self, session_id: str) -> SessionContext:
        return self._sessions[session_id]

    def add_screenshot(self, session_id: str, image_base64: str) -> int:
        return self._sessions[session_id].add_screenshot(image_base64)

    def get_context_images(self, session_id: str) -> list[str]:
        return self._sessions[session_id].get_context_images()

    def add_message(self, session_id: str, role: str, content: str):
        self._sessions[session_id].add_message(role, content)

    def get_conversation_history(self, session_id: str) -> list[dict]:
        return self._sessions[session_id].get_conversation_history()

    def clear_session(self, session_id: str):
        """Clear saved screenshots only. Conversation history is kept."""
        if session_id in self._sessions:
            self._sessions[session_id].clear_screenshots()

    def delete_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def cleanup_old_sessions(self, max_age_seconds: int = 3600) -> int:
        """Remove sessions idle for longer than max_age_seconds. Returns count removed."""
        cutoff = time.time() - max_age_seconds
        stale = [sid for sid, ctx in self._sessions.items() if ctx.last_activity < cutoff]
        for sid in stale:
            del self._sessions[sid]
        return len(stale)


# Global singleton instance
context_manager = ContextManager()
