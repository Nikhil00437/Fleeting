"""Tests for the notes table column allowlist in Database.update_note."""

from __future__ import annotations

import pytest

from fleeting.db import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
def note(db):
    return db.insert_note({"title": "original", "raw_text": "body", "tags": ["a"]})


def test_update_note_applies_known_columns(db, note):
    updated = db.update_note(note["id"], {"title": "renamed", "summary": "s"})
    assert updated["title"] == "renamed"
    assert updated["summary"] == "s"


def test_update_note_ignores_unknown_columns(db, note):
    """Keys are interpolated into the SQL string, so anything off-schema must be dropped."""
    updated = db.update_note(note["id"], {"title": "kept", "nope": "x"})
    assert updated["title"] == "kept"


def test_update_note_does_not_execute_injected_key(db, note):
    """A key shaped like SQL must be discarded, not spliced into the statement."""
    db.execute("CREATE TABLE canary (id TEXT)")
    db.commit()

    db.update_note(note["id"], {"title": "kept", "id = 'x'; DROP TABLE notes; --": "1"})

    assert db.execute("SELECT COUNT(*) AS c FROM notes").fetchone()["c"] == 1
    assert db.execute("SELECT name FROM sqlite_master WHERE name='canary'").fetchone()


def test_update_note_still_bumps_updated_at(db, note):
    updated = db.update_note(note["id"], {"title": "t"})
    assert updated["updated_at"] >= note["updated_at"]

# ---- 0.4 metadata columns -----------------------------------------------

def test_insert_note_defaults_new_lifecycle_columns(db):
    n = db.insert_note({"raw_text": "hi", "type": "text"})
    assert n["starred"] is False
    assert n["trashed_at"] is None
    assert n["color"] is None
    assert n["fields"] == {}
    assert n["sensitive"] is False
    assert n["review_state"] == "enriched"


def test_new_metadata_columns_round_trip(db, note):
    updated = db.update_note(
        note["id"],
        {
            "starred": True,
            "color": "ember",
            "fields": {"rating": 4, "url": "https://x.dev"},
            "sensitive": True,
            "review_state": "reviewed",
        },
    )
    assert updated["starred"] is True
    assert updated["color"] == "ember"
    assert updated["fields"] == {"rating": 4, "url": "https://x.dev"}
    assert updated["sensitive"] is True
    assert updated["review_state"] == "reviewed"
    # persisted, not just merged in memory
    assert db.get_note(note["id"])["fields"] == {"rating": 4, "url": "https://x.dev"}


def test_trashed_at_round_trip(db, note):
    from fleeting.db import now_iso

    db.update_note(note["id"], {"trashed_at": now_iso()})
    assert db.get_note(note["id"])["trashed_at"] is not None
    db.update_note(note["id"], {"trashed_at": None})
    assert db.get_note(note["id"])["trashed_at"] is None


def test_note_links_table_persists(db, note):
    other = db.insert_note({"raw_text": "target", "type": "text"})
    db.execute(
        "INSERT INTO note_links (src, dst) VALUES (?, ?)", (note["id"], other["id"])
    )
    db.commit()
    rows = db.execute("SELECT src, dst FROM note_links WHERE src = ?", (note["id"],)).fetchall()
    assert [r["dst"] for r in rows] == [other["id"]]
