"""#396: the chaos switch's own contract.

Not what it is *for* — the failure behaviour it exercises is covered
deterministically in `test_processor_failures.py`, and that is the half which
has to keep working. This covers the switch itself: that it is off by default,
that it cannot be turned on by accident, and that a seeded run is
reproducible. A debugging tool that misfires is worse than no tool.
"""

from __future__ import annotations

import pytest

from fleeting import chaos
from fleeting.services.llm import LLMUnavailable
from fleeting.services.transcribe import TranscriptionError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Every test starts from a known state.

    Also resets the module RNG: it is cached on first use, so without this a
    seeded test would be order-dependent.
    """
    monkeypatch.delenv("FLEETING_CHAOS", raising=False)
    monkeypatch.delenv("FLEETING_CHAOS_SEED", raising=False)
    chaos._rng = None
    chaos._seed = None
    yield
    chaos._rng = None
    chaos._seed = None


# ---- off by default --------------------------------------------------------


def test_it_is_off_when_the_variable_is_unset() -> None:
    assert chaos.active("llm") is False
    assert chaos.active("whisper") is False
    assert chaos.describe() == "off"


def test_an_unset_switch_raises_nothing() -> None:
    for _ in range(500):
        chaos.maybe_fail("llm", "x")
        chaos.maybe_fail("whisper", "x")


# ---- the spec -------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("llm=0.5", {"llm": 0.5}),
        ("llm=0.5,whisper=0.2", {"llm": 0.5, "whisper": 0.2}),
        # A target nothing calls is a setting that lies.
        ("embeddings=1", {}),
        ("llm=nonsense", {}),
        ("llm=0", {}),
        # Above 1 is clamped rather than always-fail; a rate is a probability.
        ("llm=5", {"llm": 1.0}),
        ("", {}),
    ],
)
def test_parse(spec: str, expected: dict) -> None:
    assert chaos.parse(spec) == expected


def test_an_unknown_target_arms_nothing(monkeypatch) -> None:
    """`FLEETING_CHAOS=embeddings=1` must not arm anything at all.

    Set through the environment rather than by replacing `chaos._spec`: an
    earlier version monkeypatched that function in place and, unlike
    `monkeypatch.setattr`, nothing undid it — so every test after it ran
    against a permanently broken `_spec` and failed for unrelated reasons.
    """
    monkeypatch.setenv("FLEETING_CHAOS", "embeddings=1")
    chaos._rng = None
    assert chaos._spec() == {}
    assert chaos.active("llm") is False
    assert chaos.active("whisper") is False


# ---- behaviour ------------------------------------------------------------


def test_a_rate_of_one_always_fires(monkeypatch) -> None:
    monkeypatch.setenv("FLEETING_CHAOS", "llm=1")
    chaos._rng = None
    assert all(chaos.active("llm") for _ in range(50))


def test_the_switch_is_read_per_call_not_frozen_at_import(monkeypatch) -> None:
    """A switch frozen at import is a switch you cannot turn on without a restart."""
    assert chaos.active("llm") is False
    monkeypatch.setenv("FLEETING_CHAOS", "llm=1")
    chaos._rng = None
    assert chaos.active("llm") is True


def test_the_failure_carries_the_right_exception_type(monkeypatch) -> None:
    monkeypatch.setenv("FLEETING_CHAOS", "llm=1,whisper=1")
    chaos._rng = None
    with pytest.raises(LLMUnavailable):
        chaos.maybe_fail("llm", "chat")
    with pytest.raises(TranscriptionError):
        chaos.maybe_fail("whisper", "memo.wav")


def test_injected_failures_are_indistinguishable_from_real_ones(monkeypatch) -> None:
    """Downstream code branches on the exception type, not the message.

    If the message said "chaos", a user pasting it into a bug report would be
    debugging the wrong thing, and any `if "chaos" in str(exc)` anywhere would
    take a different path than a real outage does.
    """
    monkeypatch.setenv("FLEETING_CHAOS", "llm=1")
    chaos._rng = None
    with pytest.raises(LLMUnavailable) as injected:
        chaos.maybe_fail("llm", "chat")
    assert "chaos" not in str(injected.value).lower()


# ---- reproducibility ------------------------------------------------------


def test_a_seeded_run_repeats_exactly(monkeypatch) -> None:
    def run() -> list[bool]:
        monkeypatch.setenv("FLEETING_CHAOS", "llm=0.4")
        monkeypatch.setenv("FLEETING_CHAOS_SEED", "1234")
        chaos._rng = None
        return [chaos.active("llm") for _ in range(200)]

    assert run() == run()


def test_an_unseeded_run_logs_its_seed(monkeypatch, caplog) -> None:
    monkeypatch.setenv("FLEETING_CHAOS", "llm=0.5")
    monkeypatch.delenv("FLEETING_CHAOS_SEED", raising=False)
    chaos._rng = None
    with caplog.at_level("WARNING"):
        chaos.active("llm")
    assert any("seed=" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_injections_are_logged_loudly(monkeypatch, caplog) -> None:
    """A chaos run that fails silently teaches nothing.

    The raised exception is deliberately silent about its origin — see
    `chaos.maybe_fail` — so the log is the only place the truth appears.
    """
    monkeypatch.setenv("FLEETING_CHAOS", "llm=1")
    chaos._rng = None
    with caplog.at_level("WARNING"), pytest.raises(LLMUnavailable):
        chaos.maybe_fail("llm", "chat request")
    assert any("CHAOS" in r.getMessage() for r in caplog.records)


# ---- the call sites -------------------------------------------------------

# These two are the whole point of the switch, and neither was covered by the
# tests above: deleting the `maybe_fail` line from `request_chat` or from
# `transcribe_file` left the module's own tests green while the switch quietly
# stopped working. A debugging tool that is not wired up is worse than none,
# because it looks armed.

@pytest.mark.anyio
async def test_an_armed_switch_stops_a_chat_request(monkeypatch, caplog) -> None:
    from fleeting.services.llm import request_chat

    monkeypatch.setenv("FLEETING_CHAOS", "llm=1")
    chaos._rng = None
    # The URL is never dialled: the injection happens before the request, which
    # is what makes this safe to run with no model running.
    with caplog.at_level("WARNING"), pytest.raises(LLMUnavailable):
        await request_chat("http://127.0.0.1:1/v1/chat", {}, 1)
    # The log, not the exception, is what distinguishes an injected failure
    # from a real one: a refused connection raises the same type, so asserting
    # on that alone passed with the call site deleted.
    assert any("CHAOS" in r.getMessage() for r in caplog.records)


def test_an_armed_switch_stops_a_transcription(monkeypatch, tmp_path, caplog) -> None:
    from fleeting.config import TranscribeConfig
    from fleeting.services.transcribe import Transcriber

    monkeypatch.setenv("FLEETING_CHAOS", "whisper=1")
    chaos._rng = None
    # No ffmpeg, no model, no file: the injection happens first. A missing file
    # also raises TranscriptionError, so the log is again the only reliable
    # discriminator.
    with caplog.at_level("WARNING"), pytest.raises(TranscriptionError):
        Transcriber(TranscribeConfig()).transcribe_file(tmp_path / "absent.wav")
    assert any("CHAOS" in r.getMessage() for r in caplog.records)


def test_an_armed_switch_leaves_the_other_target_alone(
    monkeypatch, tmp_path, caplog
) -> None:
    """Arming one target must not disarm — or arm — the other."""
    from fleeting.config import TranscribeConfig
    from fleeting.services.transcribe import Transcriber

    monkeypatch.setenv("FLEETING_CHAOS", "llm=1")
    chaos._rng = None
    # whisper is not armed, so this reaches the ordinary missing-file guard.
    with caplog.at_level("WARNING"), pytest.raises(
        TranscriptionError, match="missing or empty"
    ):
        Transcriber(TranscribeConfig()).transcribe_file(tmp_path / "absent.wav")
    assert not any("CHAOS" in r.getMessage() for r in caplog.records)