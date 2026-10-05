"""#428 per-app dictation profiles."""

from __future__ import annotations

import asyncio

import pytest

import fleeting.services.profiles as prof


def test_match_profile_substring_case_insensitive(tmp_path, monkeypatch):
    p = tmp_path / "profiles.json"
    monkeypatch.setattr(prof, "PROFILES_PATH", p)
    prof.save_profiles({"firefox": {"language": "en", "mode": "cleaned"}, "Code": {"template": "dev"}})
    assert prof.match_profile("Mozilla Firefox")["mode"] == "cleaned"
    assert prof.match_profile("code.exe")["template"] == "dev"
    assert prof.match_profile("term") is None
    assert prof.match_profile(None) is None


def test_profiles_api(client, tmp_path, monkeypatch):
    import fleeting.services.profiles as p

    monkeypatch.setattr(p, "PROFILES_PATH", tmp_path / "profiles.json")
    r = client.put("/api/profiles", json={"slack": {"language": "en", "template": "meeting"}})
    assert r.status_code == 200
    assert client.get("/api/profiles").json()["slack"]["language"] == "en"


@pytest.mark.anyio
async def test_language_form_field_flows_to_transcriber(tmp_path, monkeypatch):
    """source.language on the note is passed into transcribe_file."""
    import fleeting.config as fcfg
    from fleeting.db import Database
    from fleeting.events import EventBus
    from fleeting.process import Processor

    db = Database(tmp_path / "p.db")
    db.migrate()
    cfg = fcfg.Config()
    cfg.llm.provider = "none"

    seen: dict = {}

    class FakeT:
        loaded_model_size = "base"

        def is_ready(self):
            return True

        def transcribe_file(self, path, language=None):
            seen["language"] = language
            return {"text": "hallo welt", "duration": 1.0, "language": "de", "words": []}

    ft = FakeT()
    ft.cfg = cfg.transcribe
    p = Processor(db, cfg, EventBus(), ft)  # type: ignore[arg-type]
    audio = tmp_path / "m.wav"
    audio.write_bytes(b"RIFF")
    note = db.insert_note({"raw_text": "", "type": "voice", "audio_path": str(audio), "source": {"language": "de"}})

    p.start()
    p.enqueue(note["id"])
    try:
        for _ in range(100):
            done = db.get_note(note["id"])
            if done and done["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.05)
        assert db.get_note(note["id"])["status"] == "done"
        assert seen["language"] == "de"
    finally:
        p.stop()
