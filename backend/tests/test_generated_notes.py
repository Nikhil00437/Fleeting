"""#258 marking the notes the app wrote.

Digests are mirrored into the vault and imported straight back as notes, so a
heavy inbox is mostly LLM-written prose. Every text heuristic that reads a note
is wrong on that prose: it capitalises for sentence boundaries, not for names,
so "Moreover" and "Addressed" come out of the entity extractor as people, and
"an urgent fix" in a digest about urgent fixes reads as an urgent note.

One column fixes all four at once — but only if everything that reads note
text actually honours it, which is what these tests are for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.entities import people_index
from fleeting.services.vault_watcher import _is_generated_path


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "generated.db"))
    database.migrate()
    return database


def _note(db: Database, text: str, **kw) -> str:
    return db.insert_note({"title": "t", "raw_text": text, "status": "done", **kw})["id"]


# ---- the column ----------------------------------------------------------


def test_a_generated_note_is_marked(db: Database) -> None:
    nid = _note(db, "Daily Digest — 2026-10-10")
    db.update_note(nid, {"generated": 1})
    assert db.get_note(nid)["generated"] == 1


def test_a_capture_is_not_generated(db: Database) -> None:
    nid = _note(db, "call the dentist")
    assert int(db.get_note(nid)["generated"] or 0) == 0


# ---- which files count ---------------------------------------------------


def test_a_digest_file_is_generated() -> None:
    assert _is_generated_path("/home/u/Vault/Daily/2026-10-10.md") is True


def test_a_written_note_is_not_generated() -> None:
    assert _is_generated_path("/home/u/Vault/Notes/call-the-dentist.md") is False


def test_the_check_does_not_depend_on_the_host_name() -> None:
    """A user with a folder called 'daily' in their home must not be caught."""
    assert _is_generated_path("/home/daily/Vault/Notes/x.md") is False


# ---- the heuristics honour it --------------------------------------------


def test_generated_notes_leave_the_entity_index(db: Database) -> None:
    _note(db, "Also worth noting the deploy went fine", generated=1)
    _note(db, "Priya reviewed the router plan")

    names = {p["name"] for p in people_index(db)}

    assert "Priya" in names
    assert "Also" not in names


def test_generated_notes_leave_the_benchmark_sample(db: Database) -> None:
    from fleeting.services.benchmark import sample_notes

    _note(db, "digest body", generated=1)
    _note(db, "real capture body")

    rows = sample_notes(db, limit=10)

    assert [r["raw_text"] for r in rows] == ["real capture body"]


@pytest.mark.anyio
async def test_generated_notes_are_never_held_for_a_clarifying_question(db: Database) -> None:
    """A digest the app wrote is not under-specified by the user."""
    from types import SimpleNamespace

    from fleeting.config import LLMConfig
    from fleeting.services import clarify

    nid = _note(db, "call john about the thing", generated=1)
    cfg = SimpleNamespace(llm=LLMConfig(provider="none"), writing_style_guide="")

    assert await clarify.step(db, cfg, _note_id=nid) is None
    assert db.get_note(nid)["review_state"] == "enriched"