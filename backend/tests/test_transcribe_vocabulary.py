"""#89: custom vocabulary reaches whisper as initial_prompt."""

from __future__ import annotations

from fleeting.config import Config
from fleeting.services.transcribe import Transcriber


def test_vocabulary_passed_as_initial_prompt(tmp_path, monkeypatch):
    cfg = Config().transcribe
    cfg.vocabulary = "Nikhil, FastAPI, Omarchy"
    t = Transcriber(cfg)

    captured: dict = {}

    class FakeInfo:
        duration = 1.0
        language = "en"

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return ([type("S", (), {"text": "hello"})()], FakeInfo())

    monkeypatch.setattr(t, "_get_model", lambda: FakeModel())
    monkeypatch.setattr(t, "_load_wav16k", lambda path: b"")

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    out = t.transcribe_wav(wav)
    assert out["text"] == "hello"
    assert captured["initial_prompt"] == "Nikhil, FastAPI, Omarchy"


def test_empty_vocabulary_passes_none(tmp_path, monkeypatch):
    cfg = Config().transcribe
    t = Transcriber(cfg)

    captured: dict = {}

    class FakeInfo:
        duration = 1.0
        language = "en"

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return ([], FakeInfo())

    monkeypatch.setattr(t, "_get_model", lambda: FakeModel())
    monkeypatch.setattr(t, "_load_wav16k", lambda path: b"")

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    t.transcribe_wav(wav)
    assert captured["initial_prompt"] is None


def test_translate_task_passed_through(tmp_path, monkeypatch):
    """#90: translate flag makes whisper emit English text."""
    cfg = Config().transcribe
    cfg.translate = True
    t = Transcriber(cfg)

    captured: dict = {}

    class FakeInfo:
        duration = 1.0
        language = "de"

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return ([type("S", (), {"text": "hello"})()], FakeInfo())

    monkeypatch.setattr(t, "_get_model", lambda: FakeModel())
    monkeypatch.setattr(t, "_load_wav16k", lambda path: b"")

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    t.transcribe_wav(wav)
    assert captured["task"] == "translate"


def test_cleanup_audio_adds_loudnorm(tmp_path, monkeypatch):
    """#91: cleanup flag adds loudnorm to the ffmpeg command line."""
    import fleeting.services.transcribe as tr

    cfg = Config().transcribe
    cfg.cleanup_audio = True
    t = Transcriber(cfg)

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, timeout):
        calls.append(cmd)

        class R:
            returncode = 0
            stderr = b""

        # _to_wav expects the output file to exist afterwards
        import pathlib

        pathlib.Path(cmd[-1]).write_bytes(b"RIFF")
        return R()

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    monkeypatch.setattr(tr.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    src = tmp_path / "in.mp3"
    src.write_bytes(b"x")
    t._to_wav(src)
    assert "-af" in calls[0] and "loudnorm" in calls[0]
