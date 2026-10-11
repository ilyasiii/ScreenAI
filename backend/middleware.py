"""
HTTP hardening that applies to every response.

Pure ASGI rather than BaseHTTPMiddleware, so streamed (SSE) responses pass
through untouched instead of being buffered.
"""

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-site"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    # The API never serves HTML, so nothing it returns should be able to run.
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]
_HSTS = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = _SECURITY_HEADERS + ([_HSTS] if self.hsts else [])
                headers.extend(h for h in extra if h[0] not in present)
                if b"cache-control" not in present:
                    # Responses carry user content; keep them out of shared caches.
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Refuse request bodies over `max_bytes`, before they are buffered.

    Checks Content-Length up front, and also counts bytes as they arrive, so a
    chunked upload that lies about (or omits) its length is cut off too.
    """

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    await _reject(send, 400, b'{"detail":"Invalid Content-Length."}')
                    return
                if declared > self.max_bytes:
                    await _reject(send, 413, b'{"detail":"Request body too large."}')
                    return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # An HTTPException specifically: FastAPI re-raises those from
                    # body parsing, where anything else becomes a generic 400.
                    raise HTTPException(status_code=413, detail="Request body too large.")
            return message

        await self.app(scope, counting_receive, send)


async def _reject(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
