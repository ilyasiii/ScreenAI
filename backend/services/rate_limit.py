"""
Per-user request limits.

A sliding one-minute window per (user, bucket), held in memory. That is
correct for the single-process deployment this app ships with (sessions are
in memory too); running several workers would give each its own counters.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException

from services.auth import AuthUser, current_user

WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(self):
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, user_id: str, bucket: str, limit: int) -> float | None:
        """Record a request. Returns seconds to wait if over the limit."""
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        with self._lock:
            hits = self._hits[(user_id, bucket)]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(hits[0] + WINDOW_SECONDS - now, 1.0)
            hits.append(now)
            return None

    def prune(self) -> None:
        """Drop empty windows so idle users do not accumulate."""
        cutoff = time.monotonic() - WINDOW_SECONDS
        with self._lock:
            for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
                del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limited(bucket: str, limit_getter):
    """Dependency factory: authenticate, then count against `bucket`.

    `limit_getter` is read per request so tests and config can change it.
    """

    async def dependency(user: AuthUser = Depends(current_user)) -> AuthUser:
        # A limit of 0 (or less) from the environment would otherwise index an
        # empty window and crash every request; treat it as 1.
        retry_after = limiter.hit(user.id, bucket, max(1, limit_getter()))
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "rate_limited",
                    "message": "Too many requests. Wait a moment and try again.",
                },
                headers={"Retry-After": str(int(retry_after))},
            )
        return user

    return dependency
