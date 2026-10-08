"""The notes FTS index stays in step with the notes table.

Nothing covered this until an audit of a real database turned up five index
rows whose notes no longer existed. The search query joins `notes` on rowid, so those ghosts were invisible to a
user — but an index that no longer mirrors its table is a trap for the next
person who trusts it, so the triggers are pinned here instead of by hope. How
the drift originally happened could not be reproduced with the current code
(every write path goes through the triggers); the repair, when it does happen,
is the documented `INSERT INTO notes_fts(notes_fts) VALUES('rebuild')`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "fts.db")
    database.migrate()
    return database


def _indexed(db: Database) -> set[int]:
    """Rowids held by the index — notes_fts is external content, so it is keyed
    by `notes.rowid`, not by the note id."""
    return {r["rowid"] for r in db.execute("SELECT rowid FROM notes_fts")}


def _rowid(db: Database, note_id: str) -> int:
    return db.execute("SELECT rowid FROM notes WHERE id = ?", (note_id,)).fetchone()["rowid"]


def test_a_new_note_is_searchable(db: Database) -> None:
    note = db.insert_note({"title": "hyprland cookbook", "raw_text": "wayland recipes"})
    hits = db.search("hyprland", limit=10)
    assert [n["id"] for n in hits] == [note["id"]]


def test_a_deleted_note_leaves_no_index_row(db: Database) -> None:
    keep = db.insert_note({"title": "keep me", "raw_text": "keeper"})
    drop = db.insert_note({"title": "delete me", "raw_text": "goner"})
    db.delete_note(drop["id"])

    assert db.search("goner", limit=10) == []
    assert _indexed(db) == {_rowid(db, keep["id"])}


def test_editing_a_note_drops_its_old_words(db: Database) -> None:
    """The update trigger deletes the old row before indexing the new one;
    without it the previous wording stays findable forever."""
    note = db.insert_note({"title": "draft title", "raw_text": "placeholder text"})
    db.update_note(note["id"], {"title": "final title", "raw_text": "settled wording"})

    assert db.search("placeholder", limit=10) == []
    assert [n["id"] for n in db.search("settled", limit=10)] == [note["id"]]
    assert _indexed(db) == {_rowid(db, note["id"])}
