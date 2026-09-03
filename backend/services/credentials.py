"""
Credential resolution.

A key can come from two places:

  1. `backend/.env` — the operator's key, used for everybody.
  2. The browser — the user's own key, typed into the app.

The server key always wins. A client key is only ever consulted when the server
has none, so enabling this cannot cause a request to silently bill somebody
else's account, and an operator who has configured a key never has users
prompted for one.

Client keys are held in memory for the life of the process, never written to
disk, never logged, and never returned to any client.
"""

import asyncio
import logging
from collections import OrderedDict

from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

# One OpenAI client per distinct key. Each holds an HTTP connection pool, so
# building a fresh one per request would leak sockets under any real load.
_MAX_CACHED_CLIENTS = 8
_clients: "OrderedDict[str, AsyncOpenAI]" = OrderedDict()


class MissingCredentialError(Exception):
    """No usable key for a provider, from either source."""

    def __init__(self, provider: str, client_keys_allowed: bool):
        self.provider = provider
        self.client_keys_allowed = client_keys_allowed
        super().__init__(f"No API key available for {provider}.")


def fingerprint(api_key: str) -> str:
    """A safe-to-log identifier. Never log the key itself."""
    return f"...{api_key[-4:]}" if len(api_key) >= 8 else "(short)"


def looks_like_key(api_key: str | None) -> bool:
    """Catch obvious paste errors before spending a round trip on them."""
    if not api_key:
        return False
    api_key = api_key.strip()
    return len(api_key) >= 20 and not any(c.isspace() for c in api_key)


def resolve_openai_key(client_key: str | None) -> str:
    """Server key, else the caller's key when that is permitted."""
    if settings.openai_api_key:
        return settings.openai_api_key
    if settings.allow_client_keys and looks_like_key(client_key):
        return client_key.strip()
    raise MissingCredentialError("openai", settings.allow_client_keys)


def resolve_groq_key(client_key: str | None) -> str:
    if settings.groq_api_key:
        return settings.groq_api_key
    if settings.allow_client_keys and looks_like_key(client_key):
        return client_key.strip()
    raise MissingCredentialError("groq", settings.allow_client_keys)


def resolve_voice_llm_key(client_keys: dict | None) -> str:
    """Key for whichever provider answers spoken questions."""
    server_key = settings.voice_llm_key()
    if server_key:
        return server_key

    candidate = (client_keys or {}).get(
        {"openai": "openai_key", "groq": "groq_key", "anthropic": "anthropic_key"}.get(
            settings.llm_provider, ""
        )
    )
    if settings.allow_client_keys and looks_like_key(candidate):
        return candidate.strip()
    raise MissingCredentialError(settings.llm_provider, settings.allow_client_keys)


def get_openai_client(api_key: str) -> AsyncOpenAI:
    """A pooled async client for this key."""
    existing = _clients.get(api_key)
    if existing is not None:
        _clients.move_to_end(api_key)
        return existing

    client = AsyncOpenAI(api_key=api_key)
    _clients[api_key] = client

    while len(_clients) > _MAX_CACHED_CLIENTS:
        _, evicted = _clients.popitem(last=False)
        _schedule_close(evicted)

    logger.debug("Created OpenAI client for key %s", fingerprint(api_key))
    return client


def _schedule_close(client: AsyncOpenAI) -> None:
    """Close an evicted client without blocking, if a loop is running."""
    try:
        asyncio.get_running_loop().create_task(client.close())
    except RuntimeError:
        # No running loop (e.g. during interpreter shutdown). The pool will be
        # reclaimed with the object.
        pass


def credential_status() -> dict:
    """What /health reports, so the browser knows whether to ask for a key."""
    return {
        "openai_configured": bool(settings.openai_api_key),
        "groq_configured": bool(settings.groq_api_key),
        "anthropic_configured": bool(settings.anthropic_api_key),
        "allows_client_keys": settings.allow_client_keys,
    }
