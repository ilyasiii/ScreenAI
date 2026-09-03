"""
Tests for credential resolution.

The invariant that matters: a key supplied by the browser is only ever used
when the server has none of its own. Getting that backwards would silently
redirect billing.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from services import credentials  # noqa: E402
from services.credentials import (  # noqa: E402
    MissingCredentialError,
    fingerprint,
    looks_like_key,
    resolve_groq_key,
    resolve_openai_key,
    resolve_voice_llm_key,
)

CLIENT_KEY = "sk-client-" + "a" * 30
SERVER_KEY = "sk-server-" + "b" * 30


@pytest.fixture
def no_server_keys(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(settings, "groq_api_key", "", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(settings, "allow_client_keys", True, raising=False)


class TestLooksLikeKey:
    @pytest.mark.parametrize("value", [None, "", "   ", "short", "sk-abc"])
    def test_rejects_obvious_junk(self, value):
        assert not looks_like_key(value)

    def test_rejects_whitespace_inside(self):
        # The classic bad paste: a key split across two lines.
        assert not looks_like_key("sk-aaaaaaaaaaaaaaa bbbbbbbbbbbbbbbb")

    def test_accepts_a_plausible_key(self):
        assert looks_like_key(CLIENT_KEY)

    def test_tolerates_surrounding_whitespace(self):
        assert looks_like_key(f"  {CLIENT_KEY}  ")


class TestPrecedence:
    def test_server_key_wins_over_the_client(self, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", SERVER_KEY, raising=False)
        assert resolve_openai_key(CLIENT_KEY) == SERVER_KEY

    def test_client_key_used_only_when_the_server_has_none(self, no_server_keys):
        assert resolve_openai_key(CLIENT_KEY) == CLIENT_KEY

    def test_client_key_is_trimmed(self, no_server_keys):
        assert resolve_openai_key(f"  {CLIENT_KEY}\n") == CLIENT_KEY

    def test_no_key_anywhere_raises(self, no_server_keys):
        with pytest.raises(MissingCredentialError) as excinfo:
            resolve_openai_key(None)
        assert excinfo.value.provider == "openai"
        assert excinfo.value.client_keys_allowed is True

    def test_malformed_client_key_is_refused_before_any_request(self, no_server_keys):
        with pytest.raises(MissingCredentialError):
            resolve_openai_key("nope")

    def test_client_keys_can_be_disabled(self, no_server_keys, monkeypatch):
        monkeypatch.setattr(settings, "allow_client_keys", False, raising=False)
        with pytest.raises(MissingCredentialError) as excinfo:
            resolve_openai_key(CLIENT_KEY)
        # The browser uses this to decide there is no point prompting.
        assert excinfo.value.client_keys_allowed is False

    def test_groq_follows_the_same_rules(self, no_server_keys, monkeypatch):
        assert resolve_groq_key(CLIENT_KEY) == CLIENT_KEY
        monkeypatch.setattr(settings, "groq_api_key", SERVER_KEY, raising=False)
        assert resolve_groq_key(CLIENT_KEY) == SERVER_KEY


class TestVoiceProviderKey:
    def test_picks_the_field_matching_the_provider(self, no_server_keys, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "anthropic", raising=False)
        resolved = resolve_voice_llm_key(
            {"openai_key": "sk-wrong-" + "c" * 30, "anthropic_key": CLIENT_KEY}
        )
        assert resolved == CLIENT_KEY

    def test_missing_field_for_the_provider_raises(self, no_server_keys, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "groq", raising=False)
        with pytest.raises(MissingCredentialError) as excinfo:
            resolve_voice_llm_key({"openai_key": CLIENT_KEY})
        assert excinfo.value.provider == "groq"

    def test_no_credentials_at_all(self, no_server_keys):
        with pytest.raises(MissingCredentialError):
            resolve_voice_llm_key(None)


class TestClientCache:
    def test_same_key_reuses_one_client(self):
        first = credentials.get_openai_client(CLIENT_KEY)
        second = credentials.get_openai_client(CLIENT_KEY)
        # A fresh client per request would leak a connection pool each time.
        assert first is second

    def test_distinct_keys_get_distinct_clients(self):
        assert credentials.get_openai_client("sk-one-" + "d" * 30) is not (
            credentials.get_openai_client("sk-two-" + "e" * 30)
        )

    def test_cache_is_bounded(self):
        for i in range(credentials._MAX_CACHED_CLIENTS + 5):
            credentials.get_openai_client(f"sk-bound-{i}-" + "f" * 30)
        assert len(credentials._clients) <= credentials._MAX_CACHED_CLIENTS


class TestFingerprint:
    def test_reveals_only_the_last_four_characters(self):
        printed = fingerprint(CLIENT_KEY)
        assert printed == "...aaaa"
        assert CLIENT_KEY[:-4] not in printed

    def test_short_values_reveal_nothing(self):
        assert fingerprint("abc") == "(short)"


class TestCredentialStatus:
    def test_reports_presence_never_values(self, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", SERVER_KEY, raising=False)
        status = credentials.credential_status()
        assert status["openai_configured"] is True
        assert SERVER_KEY not in str(status)

    def test_absent_keys_report_false(self, no_server_keys):
        status = credentials.credential_status()
        assert status["openai_configured"] is False
        assert status["allows_client_keys"] is True
