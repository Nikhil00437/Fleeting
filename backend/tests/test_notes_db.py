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