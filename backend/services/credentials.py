"""
Credential resolution.

A key can come from two places:

  1. `backend/.env` — the operator's key, used for everybody.
  2. The browser — the user's own key, typed into the app.

The server key always wins. A client key is only ever consulted when the server
has none, so enabling this cannot cause a request to silently bill somebody
else's account, and an operator who has configured a key never has users
prompted for one.

Client keys are used for the one request that carried them: never stored,
never written to disk, never logged, and never returned to any client.
"""

import logging

from groq import AsyncGroq
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from config import settings

logger = logging.getLogger(__name__)

# One connection pool for every key. Each user's key gets a lightweight client
# view over it (`with_options`), so there is nothing per key to cache, evict or
# close. The previous per-key cache closed an evicted client even while another
# user's answer was still streaming through it, which cut that answer off as
# soon as more than a handful of users were active at once.
_base_client: AsyncOpenAI | None = None
_base_groq: AsyncGroq | None = None


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
    """Key for whichever provider answers spoken questions.

    `client_keys` maps `openai_key` / `groq_key` / `anthropic_key` to whatever
    the browser sent; only the configured provider's entry is consulted.
    """
    server_key = settings.voice_llm_key()
    if server_key:
        return server_key

    candidate = (client_keys or {}).get(f"{settings.llm_provider}_key")
    if settings.allow_client_keys and looks_like_key(candidate):
        return candidate.strip()
    raise MissingCredentialError(settings.llm_provider, settings.allow_client_keys)


def get_openai_client(api_key: str) -> AsyncOpenAI:
    """An async client for this key, sharing the process-wide connection pool."""
    global _base_client
    if _base_client is None:
        _base_client = AsyncOpenAI(
            # Placeholder only: every call goes through with_options(api_key=...).
            api_key="unused",
            http_client=DefaultAsyncHttpxClient(),
            max_retries=1,
        )
    return _base_client.with_options(api_key=api_key)


def get_groq_client(api_key: str) -> AsyncGroq:
    """An async Groq client for this key, over one shared connection pool."""
    global _base_groq
    if _base_groq is None:
        _base_groq = AsyncGroq(api_key="unused", max_retries=1)
    return _base_groq.with_options(api_key=api_key)


def credential_status() -> dict:
    """What /health reports, so the browser knows whether to ask for a key."""
    return {
        "openai_configured": bool(settings.openai_api_key),
        "groq_configured": bool(settings.groq_api_key),
        "anthropic_configured": bool(settings.anthropic_api_key),
        "allows_client_keys": settings.allow_client_keys,
    }
