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
