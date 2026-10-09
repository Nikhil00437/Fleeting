"""#256: few-shot examples built from enrichments the user corrected.

The thumb from #255 is only useful if something reads it. The signal that a
note was *corrected* is not the thumb alone — it is a note whose stored title
and tags differ from what the model produced, which the version history
already records.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.fewshot import build_few_shot, few_shot_examples


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _corrected(db: Database, text: str, title: str, tags: list[str], verdict: int = 1) -> str:
    note = db.insert_note({
        "title": "model guessed badly",
        "summary": "",
        "raw_text": text,
        "tags": ["guess"],
        "type": "text",
        "status": "done",
        "review_state": "final",
    })
    # A human edit: update_note snapshots the pre-edit title first.
    db.update_note(note["id"], {"title": title, "tags": tags})
    db.update_note(note["id"], {"enrich_feedback": verdict})
    return note["id"]


def test_no_examples_without_any_corrected_notes(db: Database) -> None:
    assert few_shot_examples(db) == []


def test_a_thumbs_up_contributes_its_corrected_title(db: Database) -> None:
    _corrected(db, "the gl-inet router needs a firmware reflash", "Flash the GL.iNet router", ["homelab"])
    examples = few_shot_examples(db)
    assert len(examples) == 1
    assert examples[0]["title"] == "Flash the GL.iNet router"
    assert examples[0]["tags"] == ["homelab"]


def test_the_example_carries_the_note_text_it_was_derived_from(db: Database) -> None:
    """An example without its input teaches the model nothing."""
    _corrected(db, "the gl-inet router needs a firmware reflash", "Flash the GL.iNet router", ["homelab"])
    assert "firmware reflash" in few_shot_examples(db)[0]["excerpt"]


def test_a_thumbs_down_still_contributes_the_human_version(db: Database) -> None:
    """A bad model output is the strongest teaching signal there is."""
    _corrected(db, "some rambling about sourdough", "Sourdough starter log", ["baking"], verdict=-1)
    examples = few_shot_examples(db)
    assert examples[0]["title"] == "Sourdough starter log"


def test_an_unedited_note_is_not_an_example(db: Database) -> None:
    """Thumbs-up on output you never corrected teaches nothing new."""
    note = db.insert_note({
        "title": "Fine as generated",
        "raw_text": "plain text",
        "tags": ["ok"],
        "status": "done",
        "review_state": "enriched",
    })
    db.update_note(note["id"], {"enrich_feedback": 1})
    assert few_shot_examples(db) == []


def test_examples_are_capped(db: Database) -> None:
    """Few-shot is a handful of examples, not a transcript of your inbox."""
    for i in range(12):
        _corrected(db, f"note number {i} about topic {i}", f"Title {i}", [f"tag{i}"])
    assert len(few_shot_examples(db, limit=4)) == 4


def test_excerpts_are_truncated(db: Database) -> None:
    _corrected(db, "x " * 4000, "Long note", ["big"])
    assert len(few_shot_examples(db)[0]["excerpt"]) <= 400


def test_prompt_block_lists_the_examples(db: Database) -> None:
    _corrected(db, "the gl-inet router needs a firmware reflash", "Flash the GL.iNet router", ["homelab"])
    block = build_few_shot(db)
    assert "Flash the GL.iNet router" in block
    assert "homelab" in block


def test_prompt_block_is_empty_without_examples(db: Database) -> None:
    assert build_few_shot(db) == ""


def test_sensitive_notes_never_become_examples(db: Database) -> None:
    """#26: a corrected sensitive note is still a secret."""
    _corrected(db, "the wifi passphrase is swordfish", "Wifi passphrase", ["network"])
    db.execute("UPDATE notes SET sensitive = 1")
    db.commit()
    assert few_shot_examples(db) == []


def test_trashed_notes_never_become_examples(db: Database) -> None:
    _corrected(db, "an idea i threw away", "Discarded idea", ["misc"])
    db.execute("UPDATE notes SET trashed_at = '2026-10-09T00:00:00Z'")
    db.commit()
    assert few_shot_examples(db) == []


@pytest.mark.anyio
async def test_examples_reach_the_model_prompt(db: Database, monkeypatch) -> None:
    """The whole point is that they are sent; assert the wire, not the builder."""
    import httpx

    from fleeting.config import LLMConfig
    from fleeting.services import llm as llm_svc

    _corrected(db, "the gl-inet router needs a firmware reflash", "Flash the GL.iNet router", ["homelab"])
    seen: list[dict] = []

    async def fake_post(url, payload, timeout, headers=None):
        seen.append(payload)
        return '{"title": "t", "summary": "s", "tags": [], "action_items": []}'

    monkeypatch.setattr(llm_svc, "_post_chat", fake_post)

    cfg = LLMConfig(provider="ollama", model="m", timeout_secs=10)
    await llm_svc.enrich_chain("another capture", cfg, few_shot=build_few_shot(db))

    assert "Flash the GL.iNet router" in seen[0]["messages"][0]["content"]


@pytest.mark.anyio
async def test_a_capture_uses_the_corrected_examples(db: Database, client, monkeypatch) -> None:
    """End to end: correcting a note changes how the *next* one is enriched."""
    from fleeting.services import llm as llm_svc

    _corrected(db, "the gl-inet router needs a firmware reflash", "Flash the GL.iNet router", ["homelab"])
    seen: list[dict] = []

    async def fake_chain(text, cfg, prompt=None, few_shot=""):
        seen.append({"text": text, "few_shot": few_shot})
        return {"title": "t", "summary": "s", "tags": [], "action_items": [], "confidence": None}

    monkeypatch.setattr("fleeting.process.llm.enrich_chain", fake_chain)
    monkeypatch.setattr("fleeting.process.build_few_shot", lambda db: build_few_shot(db))

    from tests.conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "a brand new capture"}).json()["id"]
    wait_done(client, note_id)

    assert seen and "Flash the GL.iNet router" in seen[0]["few_shot"]
