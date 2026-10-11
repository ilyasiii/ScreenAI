"""
Request authentication against Supabase.

The browser sends its Supabase access token as `Authorization: Bearer <jwt>`.
It is verified locally, with no network round trip per request:

  * Asymmetric tokens (ES256/RS256, the default for current Supabase projects)
    are checked against the project's public JWKS, fetched once and cached.
  * Legacy HS256 tokens are checked against SUPABASE_JWT_SECRET.

Either way the issuer, audience and expiry are enforced, so a token from a
different Supabase project, or an expired one, is refused.
"""

import logging
import threading
import time
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException

from config import settings

logger = logging.getLogger(__name__)

_ASYMMETRIC_ALGS = ["ES256", "RS256", "EdDSA"]
_jwks_client: jwt.PyJWKClient | None = None

# After the JWKS endpoint fails, answer 503 straight away for this long rather
# than letting every request wait out its own fetch timeout in turn.
_JWKS_BACKOFF_SECONDS = 15
_jwks_failed_at = 0.0
_jwks_lock = threading.Lock()


@dataclass(frozen=True)
class AuthUser:
    id: str


# Used when REQUIRE_AUTH is off (offline local development only).
_ANONYMOUS = AuthUser(id="local-dev")


def auth_configured() -> bool:
    return bool(settings.supabase_url)


def _jwks() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(
            f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
            # The key *set* is cached for `lifespan` and refreshed after it.
            # Deliberately no per-key cache (cache_keys): that one never
            # expires, so a signing key revoked in Supabase would stay trusted
            # until the process restarted.
            lifespan=600,
            timeout=10,
        )
    return _jwks_client


def _auth_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "auth_unavailable", "message": "Sign-in check failed. Try again."},
        headers={"Retry-After": str(_JWKS_BACKOFF_SECONDS)},
    )


def _signing_key(token: str, alg: str):
    """The project's public key for this token, with the outage backoff."""
    global _jwks_failed_at
    with _jwks_lock:
        if time.monotonic() - _jwks_failed_at < _JWKS_BACKOFF_SECONDS:
            raise _auth_unavailable()
    try:
        jwk = _jwks().get_signing_key_from_jwt(token)
    except jwt.PyJWKClientError as exc:
        # A key id the project never published means a forged token or one
        # from another project: the caller's problem, not an outage. PyJWT
        # only re-fetches the key set for unknown ids after a cooldown, so
        # these cannot be used to hammer the JWKS endpoint.
        if not isinstance(exc, jwt.PyJWKClientConnectionError) and str(exc).startswith(
            "Unable to find a signing key"
        ):
            logger.info("Rejected token with unknown key id.")
            raise _unauthorized() from exc
        with _jwks_lock:
            _jwks_failed_at = time.monotonic()
        logger.error("Could not fetch Supabase signing keys: %s", exc)
        raise _auth_unavailable() from exc

    # The token names its algorithm; the key decides it. A token claiming
    # RS256 while pointing at an EC key is forged, and passing that pair to
    # decode() would raise a TypeError (a 500) instead of a clean refusal.
    if jwk.algorithm_name != alg:
        raise _unauthorized()
    return jwk.key


def _unauthorized(message: str = "Sign in again to continue.") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "unauthorized", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token: str) -> AuthUser:
    """Validate a Supabase access token and return its user."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc

    alg = header.get("alg", "")
    options = {"require": ["exp", "sub", "aud", "iss"]}
    issuer = f"{settings.supabase_url}/auth/v1"

    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                logger.error(
                    "Received an HS256 token but SUPABASE_JWT_SECRET is not set; "
                    "this project uses legacy JWT secrets."
                )
                raise _unauthorized()
            key = settings.supabase_jwt_secret
            algorithms = ["HS256"]
        elif alg in _ASYMMETRIC_ALGS:
            key = _signing_key(token, alg)
            algorithms = [alg]
        else:
            # Includes "none". Never let the token pick an algorithm we did not
            # explicitly allow.
            raise _unauthorized()

        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience="authenticated",
            issuer=issuer,
            options=options,
            leeway=30,
        )
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Your session expired. Sign in again.") from exc
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        # TypeError/ValueError: malformed input that slips past PyJWT's own
        # checks (key and token shapes that do not fit). Always a refusal,
        # never a 500 with a traceback anyone can trigger.
        logger.info("Rejected token: %s", exc.__class__.__name__)
        raise _unauthorized() from exc

    if claims.get("role") != "authenticated":
        raise _unauthorized()
    # Supabase "anonymous sign-ins" also carry role=authenticated. This app
    # never uses them, so if the feature is ever switched on in the dashboard
    # it must not hand out API access to anyone who asks.
    if claims.get("is_anonymous") is True:
        raise _unauthorized()
    return AuthUser(id=str(claims["sub"]))


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    """FastAPI dependency: the signed-in caller, or 401.

    Deliberately sync: FastAPI runs it in the threadpool, so the occasional
    JWKS fetch (blocking urllib) never stalls the event loop.
    """
    if not settings.require_auth:
        return _ANONYMOUS
    if not auth_configured():
        # Fail closed. A misconfigured server must not quietly become public.
        raise HTTPException(
            status_code=503,
            detail={"code": "auth_not_configured", "message": "Server sign-in is not configured."},
        )
    token = _bearer(authorization)
    if not token:
        raise _unauthorized()
    return verify_token(token)
