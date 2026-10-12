"""#393: the transcription pipeline, end to end, with no whisper download.

`_to_wav`, `_load_wav16k` and `transcribe_file` guard the boundary between
"some audio arrived" and "something can actually be transcribed from it", and
that boundary is where the real failures live: a truncated upload, a stereo
file, a video with no audio track, a file ffmpeg refuses. None of it needs a
model, so none of it should have been paying for one.

Every assertion here is about the code under test, not about what a model
would say. `audio_fixtures.FakeWhisper` records the kwargs it is handed so the
pipeline's configuration of the model — `vad_filter`, `initial_prompt`,
`task="translate"` for translate mode — is checked rather than merely read.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from audio_fixtures import (
    FakeSegment,
    FakeWhisper,
    FakeWord,
    attach,
    ffmpeg_available,
    write_empty,
    write_video,
    write_wav,
)
from fleeting.config import TranscribeConfig
from fleeting.services.transcribe import Transcriber, TranscriptionError

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg is required by the transcription pipeline"
)


def make(cfg: TranscribeConfig | None = None) -> Transcriber:
    return Transcriber(cfg or TranscribeConfig())


# ---- the guards -----------------------------------------------------------


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TranscriptionError, match="missing or empty"):
        make().transcribe_file(tmp_path / "nope.webm")


def test_an_empty_file_is_refused(tmp_path: Path) -> None:
    # A client that finishes uploading an empty body still POSTs. Handing that
    # to ffmpeg produces a baffling exit-code error instead of a clear one.
    with pytest.raises(TranscriptionError, match="missing or empty"):
        make().transcribe_file(write_empty(tmp_path / "empty.webm"))


# ---- the decoder's own contract -------------------------------------------


def test_stereo_is_rejected_with_a_message_naming_the_expectation(tmp_path: Path) -> None:
    """`_load_wav16k` only accepts what ffmpeg emits.

    Reading a stereo file as mono does not fail — it halves the speed and
    shifts every word timestamp, which is worse than refusing it.
    """
    path = write_wav(tmp_path / "stereo.wav", channels=2)
    with pytest.raises(TranscriptionError, match="16 kHz mono"):
        make()._load_wav16k(path)


def test_the_wrong_sample_rate_is_rejected(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "8k.wav", rate=8_000)
    with pytest.raises(TranscriptionError, match="16 kHz mono"):
        make()._load_wav16k(path)


def test_a_mono_16k_wav_decodes_to_normalised_floats(tmp_path: Path) -> None:
    samples = make()._load_wav16k(write_wav(tmp_path / "ok.wav", seconds=0.1))
    assert samples.dtype.name == "float32"
    assert abs(float(samples.max())) <= 1.0
    assert abs(float(samples.min())) <= 1.0
    # 0.1s at 16 kHz. One sample off would mean a frame count bug.
    assert len(samples) == pytest.approx(1600, abs=2)


@needs_ffmpeg
def test_ffmpeg_converts_to_exactly_what_the_decoder_expects(tmp_path: Path) -> None:
    """The two halves have to agree, and only a real transcode proves it."""
    src = write_wav(tmp_path / "in.wav", rate=44_100)
    out = make()._to_wav(src)
    try:
        with wave.open(str(out), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 16_000
    finally:
        out.unlink(missing_ok=True)


@needs_ffmpeg
def test_a_file_ffmpeg_cannot_read_raises_transcription_error(tmp_path: Path) -> None:
    bad = tmp_path / "not-media.txt"
    bad.write_text("this is not audio at all")
    with pytest.raises(TranscriptionError):
        make()._to_wav(bad)


# ---- the whole path, with a fake model ------------------------------------


def test_transcribe_file_returns_text_duration_and_language(tmp_path: Path) -> None:
    """16 kHz mono, so `_to_wav` is skipped's worth of conversion already done."""
    t = make()
    attach(t)
    path = write_wav(tmp_path / "ok.wav")
    out = t.transcribe_file(path)
    assert "hello" in out["text"]
    assert out["language"] == "en"
    assert out["duration"] >= 0


def test_word_timestamps_are_carried_through(tmp_path: Path) -> None:
    """#88: per-word timings drive the transcript's click-to-seek."""
    t2 = make()
    attach(t2, FakeWhisper([FakeSegment(" hi ", 0, 1, [FakeWord(" hi", 0.1, 0.4)])]))
    result = t2.transcribe_file(write_wav(tmp_path / "ok2.wav"))
    assert result["words"][0]["w"].strip() == "hi"
    assert result["words"][0]["s"] == pytest.approx(0.1, abs=0.01)
    assert result["words"][0]["e"] == pytest.approx(0.4, abs=0.01)


def test_empty_segments_produce_empty_text_not_an_error(tmp_path: Path) -> None:
    t = make()
    attach(t, FakeWhisper([]))
    assert t.transcribe_file(write_wav(tmp_path / "silent.wav"))["text"] == ""


def test_the_pipeline_configures_whisper_as_configured(tmp_path: Path) -> None:
    cfg = TranscribeConfig(vocabulary="OpenWrt, fleeting")
    t = make(cfg)
    fake = attach(t)
    t.transcribe_file(write_wav(tmp_path / "ok.wav"))
    call = fake.calls[0]
    assert call["vad_filter"] is True
    assert call["word_timestamps"] is True
    assert call["initial_prompt"] == "OpenWrt, fleeting"
    assert call["task"] == "transcribe"


def test_translate_mode_asks_whisper_to_translate(tmp_path: Path) -> None:
    t = make(TranscribeConfig(translate=True))
    fake = attach(t)
    t.transcribe_file(write_wav(tmp_path / "ok.wav"))
    assert fake.calls[0]["task"] == "translate"


def test_an_explicit_language_overrides_the_configured_one(tmp_path: Path) -> None:
    t = make(TranscribeConfig(language="es"))
    fake = attach(t)
    t.transcribe_file(write_wav(tmp_path / "ok.wav"), language="fr")
    assert fake.calls[0]["language"] == "fr"


def test_auto_language_passes_none(tmp_path: Path) -> None:
    # "auto" and "" both mean let whisper decide; an empty string would be
    # forwarded as a literal language tag.
    t = make(TranscribeConfig(language="auto"))
    fake = attach(t)
    t.transcribe_file(write_wav(tmp_path / "ok.wav"))
    assert fake.calls[0]["language"] is None


def test_a_model_failure_becomes_a_transcription_error(tmp_path: Path) -> None:
    """Not a raw exception: the capture must show a reason, not a traceback."""

    class Exploding(FakeWhisper):
        def transcribe(self, audio, **kwargs):
            raise RuntimeError("cuda out of memory")

    t = make()
    attach(t, Exploding([]))
    with pytest.raises(TranscriptionError, match="whisper failed"):
        t.transcribe_file(write_wav(tmp_path / "ok.wav"))


@needs_ffmpeg
def test_a_video_file_transcribes_through_the_same_path(tmp_path: Path) -> None:
    """`transcribe_file` says "audio/video"; only a video proves the ffmpeg hop."""
    clip = write_video(tmp_path / "clip.mp4")
    assert clip is not None and clip.stat().st_size > 0
    t = make()
    attach(t)
    assert "hello" in t.transcribe_file(clip)["text"]


@needs_ffmpeg
def test_the_converted_wav_is_cleaned_up_even_when_transcription_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """Otherwise every failed capture leaves a file behind in the audio dir.

    `tempfile.tempdir` is redirected rather than globbing the real temp
    directory: a running app or a parallel test leaving a `fleeting-*.wav`
    there would make this flaky, and it did — the first version globbed for
    `fleeting_*.wav` while `_to_wav` writes `fleeting-`, so it matched nothing
    and passed with the cleanup deleted.
    """
    import tempfile

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    t = make()

    class Exploding(FakeWhisper):
        def transcribe(self, audio, **kwargs):
            raise RuntimeError("boom")

    attach(t, Exploding([]))
    with pytest.raises(TranscriptionError):
        t.transcribe_file(write_wav(tmp_path / "ok.wav"))

    assert list(scratch.glob("*.wav")) == []