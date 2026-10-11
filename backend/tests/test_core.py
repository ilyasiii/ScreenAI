"""
Tests for the pure logic the rest of the app leans on.

Run from the backend directory:

    pip install pytest
    python -m pytest

No network and no API keys required.
"""

import base64
import io
import random
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from services import image_utils  # noqa: E402
from services.context_manager import ContextManager, SessionLimitError  # noqa: E402
from services.openai_vision import build_messages  # noqa: E402
from services.voice_transcription import (  # noqa: E402
    audio_extension,
    build_asr_prompt,
    is_silence,
)


# --- helpers ---------------------------------------------------------------


def distinct_hashes(count: int) -> list[int]:
    """Fingerprints guaranteed to be far apart in Hamming distance.

    Naively spacing them (i << 20) produces values one bit apart, which the
    deduplicator correctly rejects as identical.
    """
    rng = random.Random(20240101)
    hashes: list[int] = []
    while len(hashes) < count:
        candidate = rng.getrandbits(64)
        if all(not image_utils.is_duplicate(candidate, h) for h in hashes):
            hashes.append(candidate)
    return hashes


def make_image_b64(width: int, height: int, noise: bool = False) -> str:
    """A deterministic test image with enough structure to hash meaningfully."""
    rng = random.Random(1234 if not noise else 9999)
    image = Image.frombytes("RGB", (width, height), rng.randbytes(width * height * 3))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


# --- image sizing ----------------------------------------------------------


class TestTargetSize:
    def test_landscape_lands_on_the_short_side_target(self):
        assert image_utils.target_size(1920, 1080) == (1365, 768)

    def test_portrait_is_symmetric(self):
        assert image_utils.target_size(1080, 1920) == (768, 1365)

    def test_never_upscales(self):
        # A small window must be left alone: inventing pixels costs the same
        # tokens and adds no information.
        assert image_utils.target_size(640, 400) == (640, 400)

    def test_ultrawide_is_capped_on_the_long_side(self):
        width, height = image_utils.target_size(5120, 1440)
        assert max(width, height) <= settings.image_max_long_side

    def test_square(self):
        assert image_utils.target_size(2000, 2000) == (768, 768)


class TestPrepareImage:
    def test_resizes_and_reports_metadata(self):
        prepared, meta = image_utils.prepare_image(make_image_b64(1920, 1080))
        assert (meta["width"], meta["height"]) == (1365, 768)
        assert meta["original"] == (1920, 1080)
        assert meta["estimated_tokens"] > 0
        # Output must be decodable JPEG.
        decoded = Image.open(io.BytesIO(base64.b64decode(prepared)))
        assert decoded.format == "JPEG"
        assert decoded.size == (1365, 768)

    def test_accepts_a_data_url_prefix(self):
        raw = make_image_b64(800, 600)
        _, meta_plain = image_utils.prepare_image(raw)
        _, meta_prefixed = image_utils.prepare_image(f"data:image/png;base64,{raw}")
        assert meta_plain["hash"] == meta_prefixed["hash"]

    def test_high_entropy_frame_still_encodes(self):
        """Regression: `optimize=True` alongside 4:4:4 chroma needs the whole
        encoded frame to fit one Pillow MAXBLOCK buffer. A screenshot with a
        photo or video on it overflowed it and raised "broken data stream",
        failing exactly the frames that are hardest to compress."""
        prepared, meta = image_utils.prepare_image(make_image_b64(1920, 1080))
        assert base64.b64decode(prepared)
        assert meta["bytes"] > 0

    def test_estimated_tokens_matches_the_tile_formula(self):
        # 1365x768 -> 3x2 tiles -> 6 * 170 + 85
        assert image_utils.estimate_tokens(1365, 768) == 6 * 170 + 85


class TestImageSafety:
    def test_oversized_dimensions_are_refused_before_decoding(self, monkeypatch):
        monkeypatch.setattr(image_utils, "MAX_IMAGE_PIXELS", 100 * 100)
        with pytest.raises(ValueError):
            image_utils.prepare_image(make_image_b64(200, 200))

    def test_photo_like_frames_are_recompressed_to_a_bounded_size(self):
        # Random noise is the worst case for JPEG: it stands in for a full-screen
        # photo or video frame.
        prepared, _ = image_utils.prepare_image(make_image_b64(2048, 768, noise=True))
        assert len(prepared) <= image_utils.MAX_FRAME_B64_BYTES

    def test_unexpected_formats_are_refused(self):
        buf = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="BMP")
        with pytest.raises(Exception):
            image_utils.prepare_image(base64.b64encode(buf.getvalue()).decode("ascii"))


class TestDuplicateDetection:
    def test_recompression_does_not_change_the_fingerprint(self):
        source = make_image_b64(1200, 800)
        _, first = image_utils.prepare_image(source)
        _, second = image_utils.prepare_image(source)
        assert image_utils.is_duplicate(first["hash"], second["hash"])

    def test_different_screens_are_not_duplicates(self):
        _, a = image_utils.prepare_image(make_image_b64(1200, 800))
        _, b = image_utils.prepare_image(make_image_b64(1200, 800, noise=True))
        assert not image_utils.is_duplicate(a["hash"], b["hash"])

    def test_hamming_is_symmetric_and_zero_on_self(self):
        assert image_utils.hamming(0b1011, 0b1011) == 0
        assert image_utils.hamming(0b1011, 0b1001) == 1


# --- session state ---------------------------------------------------------


class TestContextManager:
    def test_unknown_ids_do_not_create_sessions(self):
        manager = ContextManager()
        assert manager.get("not-a-real-session") is None
        assert manager.session_count() == 0

    def test_create_then_get(self):
        manager = ContextManager()
        session_id = manager.create_session()
        assert manager.get(session_id) is not None
        assert manager.session_count() == 1

    def test_screenshots_are_capped(self):
        manager = ContextManager()
        session = manager.get(manager.create_session())
        hashes = distinct_hashes(settings.max_context_images + 3)
        for i, phash in enumerate(hashes):
            session.add_screenshot(f"img{i}", phash=phash)

        assert len(session.screenshots) == settings.max_context_images
        # Oldest go first, so the most recent frames are the ones retained.
        assert session.context_images()[-1] == f"img{len(hashes) - 1}"

    def test_duplicates_are_rejected(self):
        manager = ContextManager()
        session = manager.get(manager.create_session())
        first = session.add_screenshot("a", phash=0b1010)
        second = session.add_screenshot("b", phash=0b1010)
        assert first["added"] is True
        assert second["added"] is False
        assert second["reason"] == "duplicate"
        assert session.context_images() == ["a"]

    def test_clearing_screenshots_keeps_conversation(self):
        manager = ContextManager()
        session = manager.get(manager.create_session())
        session.add_screenshot("a", phash=1)
        session.add_exchange("q", "a")
        session.clear_screenshots()
        assert session.context_images() == []
        assert len(session.conversation_history()) == 2

    def test_conversation_window_stays_paired(self):
        manager = ContextManager()
        session = manager.get(manager.create_session())
        for i in range(20):
            session.add_exchange(f"q{i}", f"a{i}")

        history = session.conversation_history()
        assert len(history) <= settings.max_conversation_messages
        # Never start mid-exchange with a reply to an invisible question.
        assert history[0]["role"] == "user"
        assert [m["role"] for m in history] == ["user", "assistant"] * (len(history) // 2)

    def test_idle_sessions_are_evicted(self):
        manager = ContextManager()
        session_id = manager.create_session()
        manager.get(session_id).last_activity = 0  # ancient
        assert manager.cleanup_old_sessions(max_age_seconds=60) == 1
        assert manager.get(session_id) is None

    def test_active_sessions_survive_cleanup(self):
        manager = ContextManager()
        session_id = manager.create_session()
        assert manager.cleanup_old_sessions(max_age_seconds=3600) == 0
        assert manager.get(session_id) is not None

    def test_other_users_cannot_see_a_session(self):
        manager = ContextManager()
        session_id = manager.create_session(owner_id="alice")
        assert manager.get(session_id, owner_id="alice") is not None
        assert manager.get(session_id, owner_id="mallory") is None
        assert manager.delete_session(session_id, owner_id="mallory") is False
        assert manager.get(session_id, owner_id="alice") is not None

    def test_per_user_cap_evicts_least_recent(self, monkeypatch):
        monkeypatch.setattr(settings, "max_sessions_per_user", 2, raising=False)
        manager = ContextManager()
        first = manager.create_session(owner_id="alice")
        manager.get(first).last_activity = 0
        second = manager.create_session(owner_id="alice")
        third = manager.create_session(owner_id="alice")
        assert manager.get(first) is None
        assert manager.get(second) is not None and manager.get(third) is not None
        # Another user's sessions are untouched by alice's cap.
        assert manager.get(manager.create_session(owner_id="bob")) is not None

    def test_global_cap_refuses_new_sessions(self, monkeypatch):
        monkeypatch.setattr(settings, "max_sessions_total", 2, raising=False)
        manager = ContextManager()
        manager.create_session(owner_id="a")
        manager.create_session(owner_id="b")
        with pytest.raises(SessionLimitError):
            manager.create_session(owner_id="c")


# --- prompt assembly -------------------------------------------------------


class TestBuildMessages:
    def test_images_precede_history_so_the_prefix_stays_cacheable(self):
        messages = build_messages(
            context_images=["ctx1", "ctx2"],
            current_image="live",
            user_question="What is this?",
            conversation_history=[
                {"role": "user", "content": "earlier"},
                {"role": "assistant", "content": "reply"},
            ],
        )
        roles = [m["role"] for m in messages]
        assert roles[0] == "system"
        # system, image block, ack, history pair, current turn
        assert roles == ["system", "user", "assistant", "user", "assistant", "user"]

        image_block = messages[1]["content"]
        assert sum(1 for part in image_block if part["type"] == "image_url") == 2

    def test_prefix_is_stable_when_history_grows(self):
        """The whole point of the ordering: a new turn must not disturb what
        came before it, or the cache misses every time."""
        base = build_messages(["ctx"], "live", "q1", [])
        grown = build_messages(
            ["ctx"],
            "live2",
            "q2",
            [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}],
        )
        # Everything up to the volatile tail is identical.
        assert base[:3] == grown[:3]

    def test_every_image_is_explicitly_high_detail(self):
        messages = build_messages(["a", "b"], "c", None, None)
        details = [
            part["image_url"]["detail"]
            for message in messages
            if isinstance(message["content"], list)
            for part in message["content"]
            if part["type"] == "image_url"
        ]
        assert details == ["high", "high", "high"]

    def test_profile_extends_the_system_prompt(self):
        plain = build_messages(["a"], None, "q", None, None)
        tailored = build_messages(["a"], None, "q", None, {"job_title": "SRE"})
        assert "SRE" in tailored[0]["content"]
        assert len(tailored[0]["content"]) > len(plain[0]["content"])

    def test_empty_profile_is_ignored(self):
        plain = build_messages(["a"], None, "q", None, None)
        empty = build_messages(["a"], None, "q", None, {"job_title": "  ", "cv_text": ""})
        assert plain[0]["content"] == empty[0]["content"]

    def test_no_question_falls_back_to_an_instruction(self):
        messages = build_messages([], "live", None, None)
        tail = messages[-1]["content"]
        assert tail[-1]["type"] == "text"
        assert tail[-1]["text"].strip() != ""


# --- voice uploads ---------------------------------------------------------


class TestVoiceUpload:
    @pytest.mark.parametrize(
        "content_type, expected",
        [
            ("audio/webm;codecs=opus", "webm"),
            ("audio/webm", "webm"),
            ("audio/mp4", "mp4"),
            ("audio/ogg; codecs=opus", "ogg"),
            ("AUDIO/WEBM", "webm"),
        ],
    )
    def test_browser_recording_types_are_accepted(self, content_type, expected):
        assert audio_extension(content_type) == expected

    @pytest.mark.parametrize("content_type", [None, "", "text/html", "application/pdf", "video/webm"])
    def test_other_types_are_refused(self, content_type):
        assert audio_extension(content_type) is None

    @pytest.mark.parametrize("text", ["", "  ", "Thank you.", "you", "Thanks for watching!"])
    def test_whisper_silence_artefacts_are_detected(self, text):
        assert is_silence(text)

    def test_real_questions_are_not_silence(self):
        assert not is_silence("Tell me about a time you disagreed with your manager.")


# --- ASR vocabulary hint ---------------------------------------------------


class TestAsrPrompt:
    def test_no_profile_gives_no_prompt(self):
        assert build_asr_prompt(None) == ""
        assert build_asr_prompt({}) == ""

    def test_job_title_is_included(self):
        assert "Site Reliability Engineer" in build_asr_prompt(
            {"job_title": "Site Reliability Engineer"}
        )

    def test_technical_terms_are_lifted_from_the_description(self):
        prompt = build_asr_prompt(
            {
                "job_title": "Backend Engineer",
                "job_description": "You will work with Kubernetes, PostgreSQL and gRPC.",
            }
        )
        assert "Kubernetes" in prompt
        assert "PostgreSQL" in prompt

    def test_filler_words_are_excluded(self):
        prompt = build_asr_prompt({"job_description": "You will have experience with the team."})
        assert "experience" not in prompt.lower().replace("terms that may come up", "")

    def test_prompt_is_bounded(self):
        prompt = build_asr_prompt({"job_description": "Kubernetes " * 5000})
        assert len(prompt) <= 800
