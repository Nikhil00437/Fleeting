"""#101 pinned context for the assistant.

The thing being tested is that a pinned note reaches the prompt whether or not
retrieval found it, and that it arrives labelled — so the assistant can say
"you pinned this" instead of citing a note it happened to rank.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.pinned_context import (
    MAX_PINNED,
    pin_note,
    pinned_block,
    pinned_notes,
    unpin_note,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "pinned.db"))
    database.migrate()
    return database


@pytest.fixture
def thread(db: Database) -> str:
    from fleeting.services.chatlog import save_chat

    save_chat(db, "c1", [{"role": "user", "content": "what did we decide"}])
    return "c1"


def _note(db: Database, text: str = "body", **kw) -> str:
    return db.insert_note({"title": "Router plan", "raw_text": text, "status": "done", **kw})[
        "id"
    ]


def test_a_pinned_note_is_remembered(db: Database, thread: str) -> None:
    nid = _note(db)
    assert pin_note(db, thread, nid) == [nid]


def test_pinning_twice_changes_nothing(db: Database, thread: str) -> None:
    nid = _note(db)
    pin_note(db, thread, nid)
    assert pin_note(db, thread, nid) == [nid]


def test_a_note_can_be_unpinned(db: Database, thread: str) -> None:
    nid = _note(db)
    pin_note(db, thread, nid)
    assert unpin_note(db, thread, nid) == []


def test_the_order_pinned_is_the_order_kept(db: Database, thread: str) -> None:
    a, b = _note(db, "first"), _note(db, "second")
    pin_note(db, thread, a)
    pin_note(db, thread, b)
    assert [n["id"] for n in pinned_notes(db, thread)] == [a, b]


def test_the_cap_is_enforced(db: Database, thread: str) -> None:
    """A thread with everything pinned is a thread where nothing is."""
    for i in range(MAX_PINNED):
        pin_note(db, thread, _note(db, f"note {i}"))
    with pytest.raises(ValueError):
        pin_note(db, thread, _note(db, "one too many"))


def test_a_sensitive_note_is_not_pinned_through(db: Database, thread: str) -> None:
    """#26: a note the user hid does not get sent because it was pinned."""
    nid = _note(db, "private")
    db.update_note(nid, {"sensitive": 1})
    pin_note(db, thread, nid)
    assert pinned_notes(db, thread) == []


def test_a_trashed_note_is_not_pinned_through(db: Database, thread: str) -> None:
    nid = _note(db)
    pin_note(db, thread, nid)
    db.execute("UPDATE notes SET trashed_at = '2026-01-01' WHERE id = ?", (nid,))
    db.commit()
    assert pinned_notes(db, thread) == []


def test_no_pinned_notes_is_no_block(db: Database, thread: str) -> None:
    assert pinned_block([]) == ""


def test_the_block_says_the_notes_were_pinned(db: Database, thread: str) -> None:
    """The label is the feature: without it the citation is indistinguishable
    from one retrieval found."""
    nid = _note(db, "we chose Postgres over SQLite")
    pin_note(db, thread, nid)

    block = pinned_block(pinned_notes(db, thread))

    assert "pinned" in block.lower()
    assert "we chose Postgres over SQLite" in block


def test_the_block_carries_the_note_id(db: Database, thread: str) -> None:
    nid = _note(db)
    pin_note(db, thread, nid)
    assert nid in pinned_block(pinned_notes(db, thread))


def test_the_block_is_bounded(db: Database, thread: str) -> None:
    nid = _note(db, "x" * 9000)
    pin_note(db, thread, nid)
    assert len(pinned_block(pinned_notes(db, thread))) < 3000


def test_an_unknown_thread_has_nothing_pinned(db: Database) -> None:
    assert pinned_notes(db, "nope") == []

# ---- it reaches the prompt -----------------------------------------------


@pytest.mark.anyio
async def test_a_pinned_note_reaches_the_context(db: Database, thread: str) -> None:
    """The point of the feature: it is in context even though nothing matched it."""
    from fleeting.services.assistant import build_assistant_context

    from fleeting.config import Config

    nid = _note(db, "we chose Postgres over SQLite because of jsonb")
    pin_note(db, thread, nid)

    context, _sources, used = build_assistant_context(
        "what did we decide", db, Config(), pinned=pinned_notes(db, thread)
    )

    assert "Postgres over SQLite" in context
    assert used["pinned_count"] == 1


@pytest.mark.anyio
async def test_a_question_matching_nothing_still_gets_the_pinned_note(
    db: Database, thread: str
) -> None:
    from fleeting.config import Config

    from fleeting.services.assistant import build_assistant_context

    pin_note(db, thread, _note(db, "the roof quote was 4200 from O'Brien"))

    context, _sources, _used = build_assistant_context(
        "quantum chromodynamics", db, Config(), pinned=pinned_notes(db, thread)
    )

    assert "O'Brien" in context


def test_the_context_is_unchanged_without_pins(db: Database) -> None:
    from fleeting.config import Config

    from fleeting.services.assistant import build_assistant_context

    _note(db, "an ordinary note about routers")
    context, _s, used = build_assistant_context("router", db, Config())

    assert "pinned" not in context.lower()
    assert used["pinned_count"] == 0
