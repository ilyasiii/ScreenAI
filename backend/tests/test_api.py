"""
HTTP-level security tests: authentication, session ownership, rate limits,
request size limits and response headers.

Tokens are minted locally with a throwaway ES256 key standing in for the
Supabase JWKS, so no network access is needed.
"""

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from services import auth  # noqa: E402
from services.rate_limit import limiter  # noqa: E402

SUPABASE_URL = "https://example-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
_OTHER_KEY = ec.generate_private_key(ec.SECP256R1())
# What the project's JWKS endpoint would serve for _PRIVATE_KEY.
_PUBLIC_JWK = jwt.PyJWK.from_dict(
    {**json.loads(jwt.algorithms.ECAlgorithm.to_jwk(_PRIVATE_KEY.public_key())), "alg": "ES256"}
)


def make_token(sub="user-a", key=_PRIVATE_KEY, alg="ES256", **overrides) -> str:
    claims = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        **overrides,
    }
    return jwt.encode(claims, key, algorithm=alg)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", SUPABASE_URL, raising=False)
    monkeypatch.setattr(settings, "require_auth", True, raising=False)
    monkeypatch.setattr(settings, "supabase_jwt_secret", "", raising=False)
    # Stand-in for the project's JWKS endpoint.
    fake_jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _token: _PUBLIC_JWK)
    monkeypatch.setattr(auth, "_jwks", lambda: fake_jwks)
    monkeypatch.setattr(auth, "_jwks_failed_at", 0.0)
    limiter.reset()

    from main import app

    with TestClient(app) as test_client:
        yield test_client
    limiter.reset()


def create_session(client, sub="user-a") -> str:
    response = client.post("/api/session/create", headers=bearer(make_token(sub)))
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


# --- authentication ----------------------------------------------------------


class TestAuthentication:
    def test_missing_token_is_refused(self, client):
        assert client.post("/api/session/create").status_code == 401

    def test_valid_token_is_accepted(self, client):
        create_session(client)

    @pytest.mark.parametrize(
        "token",
        [
            make_token(key=_OTHER_KEY),  # signed by somebody else
            make_token(exp=int(time.time()) - 600),  # expired
            make_token(aud="anon"),  # wrong audience
            make_token(iss="https://evil.supabase.co/auth/v1"),  # other project
            make_token(role="anon"),  # the public anon key is not a user
            "not-a-jwt",
        ],
    )
    def test_bad_tokens_are_refused(self, client, token):
        assert client.post("/api/session/create", headers=bearer(token)).status_code == 401

    def test_unsigned_token_is_refused(self, client):
        token = jwt.encode(
            {"sub": "x", "aud": "authenticated", "role": "authenticated", "iss": ISSUER,
             "exp": int(time.time()) + 3600},
            key=None,
            algorithm="none",
        )
        assert client.post("/api/session/create", headers=bearer(token)).status_code == 401

    def test_hs256_needs_the_configured_secret(self, client, monkeypatch):
        secret = "s" * 40
        token = make_token(key=secret, alg="HS256")
        # Not configured: refused rather than trusted.
        assert client.post("/api/session/create", headers=bearer(token)).status_code == 401
        monkeypatch.setattr(settings, "supabase_jwt_secret", secret, raising=False)
        assert client.post("/api/session/create", headers=bearer(token)).status_code == 200

    def test_unknown_key_id_is_unauthorized_not_an_outage(self, client, monkeypatch):
        def no_such_key(_token):
            raise jwt.PyJWKClientError('Unable to find a signing key that matches: "forged"')

        monkeypatch.setattr(auth, "_jwks", lambda: SimpleNamespace(get_signing_key_from_jwt=no_such_key))
        response = client.post("/api/session/create", headers=bearer(make_token()))
        assert response.status_code == 401

    def test_unreachable_jwks_is_reported_as_unavailable(self, client, monkeypatch):
        calls = []

        def offline(_token):
            calls.append(1)
            raise jwt.PyJWKClientConnectionError("Fail to fetch data from the url")

        monkeypatch.setattr(auth, "_jwks", lambda: SimpleNamespace(get_signing_key_from_jwt=offline))
        response = client.post("/api/session/create", headers=bearer(make_token()))
        assert response.status_code == 503
        # During the backoff, requests fail fast instead of each waiting out a
        # fetch timeout.
        again = client.post("/api/session/create", headers=bearer(make_token()))
        assert again.status_code == 503
        assert len(calls) == 1

    def test_algorithm_must_match_the_published_key(self, client):
        # Claims RS256 but names the project's EC key: forged, and must be a
        # clean 401 rather than a crash.
        from cryptography.hazmat.primitives.asymmetric import rsa

        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = make_token(key=rsa_key, alg="RS256")
        assert client.post("/api/session/create", headers=bearer(token)).status_code == 401

    def test_anonymous_sign_ins_are_refused(self, client):
        token = make_token(is_anonymous=True)
        assert client.post("/api/session/create", headers=bearer(token)).status_code == 401

    def test_unconfigured_server_fails_closed(self, client, monkeypatch):
        monkeypatch.setattr(settings, "supabase_url", "", raising=False)
        response = client.post("/api/session/create", headers=bearer(make_token()))
        assert response.status_code == 503

    def test_every_data_endpoint_requires_auth(self, client):
        sid = "00000000-0000-4000-8000-000000000000"
        for method, path in [
            ("post", "/api/session/create"),
            ("post", "/api/screenshot/add"),
            ("post", "/api/analyze/stream"),
            ("post", f"/api/context/clear/{sid}"),
            ("delete", f"/api/session/{sid}"),
            ("post", "/api/parse-pdf"),
            ("post", "/api/voice/answer"),
            ("post", f"/api/voice/reset/{sid}"),
        ]:
            response = getattr(client, method)(path)
            assert response.status_code in (401, 422), (path, response.status_code)
            if response.status_code == 422:
                # Validation ran first; confirm auth is still enforced with a body.
                assert getattr(client, method)(path, json={}).status_code in (401, 422)


# --- session ownership -------------------------------------------------------


class TestOwnership:
    def test_another_user_cannot_use_my_session(self, client):
        sid = create_session(client, "alice")
        mallory = bearer(make_token("mallory"))

        response = client.post(f"/api/context/clear/{sid}", headers=mallory)
        assert response.status_code == 404
        assert client.delete(f"/api/session/{sid}", headers=mallory).status_code == 404
        # Still alive for its owner.
        alice = bearer(make_token("alice"))
        assert client.post(f"/api/context/clear/{sid}", headers=alice).status_code == 200

    def test_malformed_session_ids_are_rejected(self, client):
        response = client.post("/api/context/clear/..%2F..%2Fetc", headers=bearer(make_token()))
        assert response.status_code in (404, 422)


# --- rate limiting -----------------------------------------------------------


class TestRateLimit:
    def test_limit_is_enforced_per_user(self, client, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_session", 3, raising=False)
        for _ in range(3):
            create_session(client, "alice")
        response = client.post("/api/session/create", headers=bearer(make_token("alice")))
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) >= 1
        # Bob has his own budget.
        create_session(client, "bob")


# --- request limits ----------------------------------------------------------


class TestRequestLimits:
    def test_oversized_body_is_refused(self, client, monkeypatch):
        from main import app

        # Rebuild the middleware stack with a tiny limit for this test.
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == "BodySizeLimitMiddleware":
                monkeypatch.setitem(middleware.kwargs, "max_bytes", 1000)
        app.middleware_stack = app.build_middleware_stack()
        try:
            response = client.post(
                "/api/session/create",
                headers={**bearer(make_token()), "Content-Type": "application/json"},
                content=b"x" * 5000,
            )
            assert response.status_code == 413
        finally:
            monkeypatch.undo()
            app.middleware_stack = app.build_middleware_stack()

    def test_body_is_not_parsed_before_authentication(self, client):
        # FastAPI would answer malformed JSON with a 422 *before* running any
        # dependency. A 401 here proves the body was never touched.
        response = client.post(
            "/api/analyze/stream",
            headers={"Content-Type": "application/json"},
            content=b"[{}," * 1000 + b"not json",
        )
        assert response.status_code == 401

    def test_json_bombs_are_refused_without_parsing(self, client):
        response = client.post(
            "/api/analyze/stream",
            headers={**bearer(make_token()), "Content-Type": "application/json"},
            content=b"[" + b"{}," * 50_000 + b"{}]",
        )
        assert response.status_code == 400

    def test_validation_errors_do_not_echo_the_input(self, client):
        secret_looking = "A" * 5000
        response = client.post(
            "/api/screenshot/add",
            headers={**bearer(make_token()), "Content-Type": "application/json"},
            content=json.dumps({"session_id": "nope", "image_base64": secret_looking}).encode(),
        )
        assert response.status_code == 422
        assert secret_looking not in response.text

    def test_screenshot_budget_is_enforced(self, client, monkeypatch):
        from tests.test_core import make_image_b64

        monkeypatch.setattr(settings, "max_context_bytes_total", 10, raising=False)
        sid = create_session(client)
        response = client.post(
            "/api/screenshot/add",
            headers=bearer(make_token()),
            json={"session_id": sid, "image_base64": make_image_b64(64, 64)},
        )
        assert response.status_code == 503

    def test_pdf_parsing_runs_isolated_and_reports_empty_text(self, client):
        # A real child process: proves the isolation path works end to end.
        import io

        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        response = client.post(
            "/api/parse-pdf",
            headers=bearer(make_token()),
            files={"file": ("cv.pdf", buf.getvalue(), "application/pdf")},
        )
        assert response.status_code == 422
        assert "scanned" in response.json()["error"]

    def test_pdf_parsing_is_cut_off_at_the_deadline(self, client, monkeypatch):
        from routers import voice

        monkeypatch.setattr(voice, "PDF_TIMEOUT_SECONDS", 0.01)
        response = client.post(
            "/api/parse-pdf",
            headers=bearer(make_token()),
            files={"file": ("cv.pdf", b"%PDF-1.4\n" + b"0" * 2000, "application/pdf")},
        )
        assert response.status_code == 400
        assert "too long" in response.json()["error"]

    def test_pdf_upload_checks_content_not_filename(self, client):
        response = client.post(
            "/api/parse-pdf",
            headers=bearer(make_token()),
            files={"file": ("cv.pdf", b"<html>not a pdf</html>", "application/pdf")},
        )
        assert response.status_code == 400

    def test_voice_rejects_non_audio_uploads(self, client, monkeypatch):
        monkeypatch.setattr(settings, "groq_api_key", "gsk_" + "x" * 40, raising=False)
        monkeypatch.setattr(settings, "openai_api_key", "sk-" + "x" * 40, raising=False)
        monkeypatch.setattr(settings, "llm_provider", "openai", raising=False)
        sid = create_session(client)
        response = client.post(
            "/api/voice/answer",
            headers=bearer(make_token()),
            data={"session_id": sid},
            files={"audio": ("a.html", b"<script>" * 400, "text/html")},
        )
        assert response.status_code == 415

    def test_voice_names_the_missing_keys(self, client, monkeypatch):
        monkeypatch.setattr(settings, "groq_api_key", "", raising=False)
        monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
        monkeypatch.setattr(settings, "llm_provider", "openai", raising=False)
        monkeypatch.setattr(settings, "allow_client_keys", True, raising=False)
        sid = create_session(client)
        response = client.post(
            "/api/voice/answer",
            headers=bearer(make_token()),
            data={"session_id": sid},
            files={"audio": ("a.webm", b"\x1a\x45\xdf\xa3" * 400, "audio/webm")},
        )
        assert response.status_code == 401
        detail = response.json()["detail"]
        assert detail["code"] == "api_key_required"
        assert detail["needed"] == ["groq_key", "openai_key"]


# --- voice flow --------------------------------------------------------------


class TestVoiceFlow:
    @pytest.fixture
    def voice_client(self, client, monkeypatch):
        from routers import voice

        monkeypatch.setattr(settings, "groq_api_key", "", raising=False)
        monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
        monkeypatch.setattr(settings, "llm_provider", "openai", raising=False)
        monkeypatch.setattr(settings, "allow_client_keys", True, raising=False)
        self.seen_keys = {}
        self.transcript = "Why do you want this role?"

        async def fake_transcribe(clip, extension, api_key, profile=None):
            self.seen_keys["groq"] = api_key
            return self.transcript

        async def fake_stream(messages, api_key):
            self.seen_keys["llm"] = api_key
            self.history_len = len(messages)
            for token in ["Because ", "it fits."]:
                yield token

        monkeypatch.setattr(voice, "transcribe", fake_transcribe)
        monkeypatch.setattr(voice, "stream_answer", fake_stream)
        return client

    def _ask(self, client, sid):
        return client.post(
            "/api/voice/answer",
            headers={
                **bearer(make_token()),
                "X-Groq-Api-Key": "gsk_" + "g" * 40,
                "X-OpenAI-Api-Key": "sk-" + "o" * 40,
            },
            data={"session_id": sid, "profile": '{"job_title": "Engineer"}'},
            files={"audio": ("q.webm", b"\x1a\x45\xdf\xa3" * 400, "audio/webm;codecs=opus")},
        )

    def test_streams_transcript_then_answer_and_remembers(self, voice_client):
        sid = create_session(voice_client)
        response = self._ask(voice_client, sid)
        assert response.status_code == 200
        body = response.text
        order = [body.index(marker) for marker in
                 ['"start"', '"transcription"', '"token"', '"done"']]
        assert order == sorted(order)
        assert self.seen_keys == {"groq": "gsk_" + "g" * 40, "llm": "sk-" + "o" * 40}

        # The follow-up sees the first exchange in its history.
        first_len = self.history_len
        self._ask(voice_client, sid)
        assert self.history_len == first_len + 2

        reset = voice_client.post(f"/api/voice/reset/{sid}", headers=bearer(make_token()))
        assert reset.status_code == 200
        self._ask(voice_client, sid)
        assert self.history_len == first_len

    def test_silence_produces_no_answer(self, voice_client):
        self.transcript = "Thank you."
        sid = create_session(voice_client)
        body = self._ask(voice_client, sid).text
        assert '"no_speech"' in body
        assert '"token"' not in body


# --- headers -----------------------------------------------------------------


class TestHeaders:
    def test_security_headers_are_present(self, client):
        response = client.get("/health")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    def test_health_reveals_no_secrets_or_load(self, client, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-" + "s" * 40, raising=False)
        body = client.get("/health").text
        assert "sssss" not in body
        assert "active_sessions" not in body

    def test_cors_allows_only_configured_origins(self, client):
        allowed = settings.cors_origins[0]
        ok = client.options(
            "/api/session/create",
            headers={"Origin": allowed, "Access-Control-Request-Method": "POST"},
        )
        assert ok.headers.get("access-control-allow-origin") == allowed

        evil = client.options(
            "/api/session/create",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in evil.headers
