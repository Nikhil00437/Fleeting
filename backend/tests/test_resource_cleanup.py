"""Storage that grew forever: audio files, activity rows, boot-time rescan.

Three verified leaks:
  - `db.delete_note` removed the row and the vault file but never unlinked
    `audio_path`, so `~/.local/share/fleeting/audio/` grew monotonically.
  - Nothing ever deleted from `activity`. A new row is written on every window
    title change, and sub-second rows are filtered out at read time — after
    being stored — so a browser cycling tabs produces thousands of dead rows a
    day, forever.
  - `_migrate_action_items()` full-scanned `notes` with a per-row INSERT on
    *every* boot, outside the migration system.
"""

from __future__ import annotations

import pytest

from fleeting.db import Database


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "r.db")
    d.migrate()
    return d


def _add_note(db: Database, raw: str = "hello") -> dict:
    n = db.insert_note({"raw_text": raw, "type": "text"})
    return n if isinstance(n, dict) else db.get_note(n)


# ---------------------------------------------------------------------------
# audio cleanup
# ---------------------------------------------------------------------------


def test_delete_note_removes_audio_file(tmp_path, db: Database) -> None:
    root = tmp_path / "audio"
    root.mkdir()
    audio = root / "memo.webm"
    audio.write_bytes(b"RIFFfake")
    note = db.insert_note(
        {"raw_text": "", "type": "voice", "audio_path": str(audio), "source": {}}
    )
    nid = note["id"] if isinstance(note, dict) else note
    assert audio.exists()

    db.delete_note(nid, audio_root=str(root))

    assert not audio.exists(), "audio file left behind after deleting the note"


def test_delete_note_is_forgiving_about_a_missing_audio_file(tmp_path, db: Database) -> None:
    """A note whose audio was already cleaned up must still delete."""
    note = db.insert_note(
        {
            "raw_text": "",
            "type": "voice",
            "audio_path": str(tmp_path / "gone.webm"),
            "source": {},
        }
    )
    nid = note["id"] if isinstance(note, dict) else note
    db.delete_note(nid)  # must not raise
    assert db.get_note(nid) is None


def test_delete_note_with_no_audio_path_still_works(db: Database) -> None:
    note = _add_note(db)
    db.delete_note(note["id"])
    assert db.get_note(note["id"]) is None


def test_audio_is_not_removed_when_path_is_outside_the_data_dir(tmp_path, db: Database) -> None:
    """Only unlink inside AUDIO_DIR; a hand-edited row must not delete a system file."""
    outside = tmp_path / "precious.txt"
    outside.write_text("keep me")
    note = db.insert_note(
        {"raw_text": "", "type": "voice", "audio_path": str(outside), "source": {}}
    )
    nid = note["id"] if isinstance(note, dict) else note

    db.delete_note(nid, audio_root=str(tmp_path / "audio"))

    assert outside.exists(), "deleted a file outside the audio directory"


def test_audio_inside_root_is_removed(tmp_path, db: Database) -> None:
    root = tmp_path / "audio"
    root.mkdir()
    f = root / "memo.webm"
    f.write_bytes(b"x")
    note = db.insert_note({"raw_text": "", "type": "voice", "audio_path": str(f), "source": {}})
    nid = note["id"] if isinstance(note, dict) else note
    db.delete_note(nid, audio_root=str(root))
    assert not f.exists()


# ---------------------------------------------------------------------------
# activity pruning
# ---------------------------------------------------------------------------


def test_prune_activity_keeps_recent_rows(db: Database) -> None:
    db.upsert_activity(
        {
            "app_class": "zen",
            "title": "old",
            "first_seen": "2020-01-01T00:00:00+00:00",
            "last_seen": "2020-01-01T00:10:00+00:00",
            "seconds": 600,
            "day": "2020-01-01",
        }
    )
    db.upsert_activity(
        {
            "app_class": "code",
            "title": "new",
            "first_seen": "2026-10-04T10:00:00+00:00",
            "last_seen": "2026-10-04T10:10:00+00:00",
            "seconds": 600,
            "day": "2026-10-04",
        }
    )
    removed = db.prune_activity(before_day="2026-01-01")
    assert removed == 1
    apps = {r["app_class"] for r in db.known_apps()}
    assert apps == {"code"}


def test_prune_activity_is_idempotent(db: Database) -> None:
    for i in range(3):
        db.upsert_activity(
            {
                "app_class": f"a{i}",
                "title": "t",
                "first_seen": "2020-01-01T00:00:00+00:00",
                "last_seen": "2020-01-01T00:01:00+00:00",
                "seconds": 60,
                "day": "2020-01-01",
            }
        )
    assert db.prune_activity(before_day="2026-01-01") == 3
    assert db.prune_activity(before_day="2026-01-01") == 0


def test_prune_activity_drops_empty_sessions(db: Database) -> None:
    """Sub-second rows are hidden at read time but still occupy the table."""
    db.upsert_activity(
        {
            "app_class": "zen",
            "title": "tab",
            "first_seen": "2026-10-04T10:00:00+00:00",
            "last_seen": "2026-10-04T10:00:00+00:00",
            "seconds": 0,
            "day": "2026-10-04",
        }
    )
    assert db.prune_activity(before_day="2027-01-01", min_seconds=1) >= 1
    assert db.execute("SELECT COUNT(*) AS c FROM activity").fetchone()["c"] == 0


def test_prune_keeps_sessions_that_clear_the_threshold(db: Database) -> None:
    db.upsert_activity(
        {
            "app_class": "zen",
            "title": "tab",
            "first_seen": "2026-10-04T10:00:00+00:00",
            "last_seen": "2026-10-04T10:05:00+00:00",
            "seconds": 300,
            "day": "2026-10-04",
        }
    )
    # cutoff before the session's day, and it clears min_seconds
    db.prune_activity(before_day="2026-01-01", min_seconds=1)
    assert db.execute("SELECT COUNT(*) AS c FROM activity").fetchone()["c"] == 1


# ---------------------------------------------------------------------------
# boot-time rescan
# ---------------------------------------------------------------------------


def test_constructing_database_does_not_rescan_notes(tmp_path, monkeypatch) -> None:
    """`Database()` ran a full notes scan with per-row INSERTs on every boot."""
    path = tmp_path / "boot.db"
    first = Database(path)
    first.migrate()
    for i in range(20):
        first.insert_note({"raw_text": f"n{i}", "type": "text"})

    def boom(*a, **kw):
        raise AssertionError("_migrate_action_items ran outside migrate()")

    monkeypatch.setattr(Database, "_migrate_action_items", boom)
    Database(path)  # must not touch notes


def test_reopening_database_preserves_notes(tmp_path) -> None:
    path = tmp_path / "again.db"
    d = Database(path)
    d.migrate()
    n = d.insert_note({"raw_text": "durable", "type": "text"})
    nid = n["id"] if isinstance(n, dict) else n

    reopened = Database(path)
    reopened.migrate()
    assert reopened.get_note(nid) is not None