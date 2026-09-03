"""
Tests for the pure logic the rest of the app leans on.

Run from the backend directory:

    pip install pytest
    python -m pytest

No network, no API keys, no audio device required.
"""

import base64
import io
import random
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from services import image_utils  # noqa: E402
from services.audio_processing import _normalise, _resample, _to_mono  # noqa: E402
from services.context_manager import ContextManager  # noqa: E402
from services.openai_vision import build_messages  # noqa: E402
from services.voice_transcription import build_asr_prompt  # noqa: E402


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
    rng = np.random.default_rng(1234 if not noise else 9999)
    array = rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="PNG")
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


# --- audio -----------------------------------------------------------------


class TestAudio:
    def test_stereo_downmix(self):
        interleaved = np.array([1.0, 3.0, 2.0, 4.0], dtype=np.float32)  # L,R,L,R
        assert np.allclose(_to_mono(interleaved, 2), [2.0, 3.0])

    def test_mono_passthrough(self):
        mono = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        assert np.allclose(_to_mono(mono, 1), mono)

    def test_ragged_stereo_frame_does_not_crash(self):
        # A truncated final chunk must not raise on reshape.
        ragged = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert len(_to_mono(ragged, 2)) == 1

    @pytest.mark.parametrize("src_rate", [44100, 48000, 16000, 22050])
    def test_resample_hits_the_target_length(self, src_rate):
        one_second = np.zeros(src_rate, dtype=np.float32)
        out = _resample(one_second, src_rate)
        assert abs(len(out) - 16000) <= 2

    def test_resample_preserves_a_tone(self):
        # A 440 Hz sine at 48k, downsampled, should still be a 440 Hz sine.
        t = np.arange(48000) / 48000
        tone = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        out = _resample(tone, 48000)
        peak_bin = int(np.argmax(np.abs(np.fft.rfft(out))))
        assert abs(peak_bin - 440) <= 2

    def test_normalise_reaches_the_target_rms(self):
        quiet = (np.random.default_rng(0).standard_normal(16000) * 0.005).astype(np.float32)
        out = _normalise(quiet)
        assert 0.01 < float(np.sqrt(np.mean(out**2))) <= 0.06

    def test_normalise_does_not_amplify_silence_into_noise(self):
        near_silence = np.full(1000, 1e-7, dtype=np.float32)
        out = _normalise(near_silence)
        assert float(np.max(np.abs(out))) < 0.01

    def test_normalise_never_clips(self):
        loud = np.ones(1000, dtype=np.float32) * 0.9
        assert float(np.max(np.abs(_normalise(loud)))) <= 1.0

    def test_normalise_handles_empty_input(self):
        assert len(_normalise(np.zeros(0, dtype=np.float32))) == 0


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
