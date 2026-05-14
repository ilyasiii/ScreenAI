"""
Context Manager Service
Maintains a rolling window of previous screenshots so the AI
can understand content that spans multiple screens.

Each session gets its own context history. Screenshots are stored
as base64 strings and the oldest are dropped when the limit is reached.
"""

import time
import os
from collections import defaultdict

MAX_CONTEXT = int(os.getenv("MAX_CONTEXT_SCREENSHOTS", "5"))


class ScreenshotEntry:
    """Single screenshot with metadata."""

    def __init__(self, image_base64: str, timestamp: float = None):
        self.image_base64 = image_base64
        self.timestamp = timestamp or time.time()


class SessionContext:
    """Manages screenshot context for a single user session."""

    def __init__(self, max_screenshots: int = MAX_CONTEXT):
        self.max_screenshots = max_screenshots
        self.screenshots: list[ScreenshotEntry] = []
        self.last_activity = time.time()

    def add_screenshot(self, image_base64: str) -> int:
        """
        Add a new screenshot to the context.
        Returns the current count of screenshots in context.
        """
        entry = ScreenshotEntry(image_base64)
        self.screenshots.append(entry)
        self.last_activity = time.time()

        # Trim old screenshots if over the limit
        if len(self.screenshots) > self.max_screenshots:
            self.screenshots = self.screenshots[-self.max_screenshots :]

        return len(self.screenshots)

    def get_context_images(self) -> list[str]:
        """
        Return all screenshots in context as base64 strings,
        ordered from oldest to newest (chronological).
        """
        return [s.image_base64 for s in self.screenshots]

    def clear(self):
        """Clear all context for this session."""
        self.screenshots = []

    def get_context_count(self) -> int:
        return len(self.screenshots)


class ContextManager:
    """
    Manages contexts for multiple sessions.
    Each session_id maps to its own SessionContext.
    """

    def __init__(self):
        self._sessions: dict[str, SessionContext] = defaultdict(SessionContext)

    def get_session(self, session_id: str) -> SessionContext:
        return self._sessions[session_id]

    def add_screenshot(self, session_id: str, image_base64: str) -> int:
        return self._sessions[session_id].add_screenshot(image_base64)

    def get_context_images(self, session_id: str) -> list[str]:
        return self._sessions[session_id].get_context_images()

    def clear_session(self, session_id: str):
        if session_id in self._sessions:
            self._sessions[session_id].clear()

    def delete_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def cleanup_old_sessions(self, max_age_seconds: int = 3600):
        """Remove sessions inactive for more than max_age_seconds."""
        now = time.time()
        expired = [
            sid
            for sid, ctx in self._sessions.items()
            if now - ctx.last_activity > max_age_seconds
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)


# Global singleton instance
context_manager = ContextManager()
