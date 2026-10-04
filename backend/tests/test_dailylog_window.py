"""Daily-log note window must be timezone-correct.

`notes.created_at` is stored in UTC (`db.now_iso`), but the digest window is
built with `datetime.now().astimezone()`. Comparing those two as *strings* is
not chronological: for any timezone with a non-zero offset the hour field
differs, so notes are silently dropped from (or wrongly added to) the digest.

The digest is the app's headline output; a window that is off by your UTC
offset is a correctness bug, not a rounding error.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fleeting.db import Database
from fleeting.services.dailylog import collect_notes_context


def _mk(tmp_path) -> Database:
    db = Database(tmp_path / "d.db")
    db.migrate()
    return db


def _add(db: Database, text: str, when: datetime) -> str:
    """Insert a note with a specific created_at. insert_note returns the row."""
    note = db.insert_note({"raw_text": text, "type": "text"})
    note_id = note["id"] if isinstance(note, dict) else note
    db.execute(
        "UPDATE notes SET created_at = ? WHERE id = ?",
        (when.astimezone(timezone.utc).isoformat(timespec="seconds"), note_id),
    )
    db.commit()
    return note_id


def test_includes_notes_inside_window(tmp_path) -> None:
    db = _mk(tmp_path)
    tz = timezone(timedelta(hours=5, minutes=30))  # IST, the case that breaks
    since = datetime(2026, 3, 10, 9, 0, tzinfo=tz)
    until = since + timedelta(hours=1)
    _add(db, "inside", since + timedelta(minutes=30))

    got = collect_notes_context(db, since, until)
    assert [n["raw_text"] for n in got] == ["inside"]


def test_excludes_notes_outside_window(tmp_path) -> None:
    db = _mk(tmp_path)
    tz = timezone(timedelta(hours=5, minutes=30))
    since = datetime(2026, 3, 10, 9, 0, tzinfo=tz)
    until = since + timedelta(hours=1)
    _add(db, "before", since - timedelta(minutes=5))
    _add(db, "after", until + timedelta(minutes=5))

    assert collect_notes_context(db, since, until) == []


@pytest.mark.parametrize("offset_hours", [-8, -5.5, 0, 5.5, 9, 13])
def test_window_is_correct_in_every_timezone(tmp_path, offset_hours: float) -> None:
    """The bug only shows at non-zero offsets, so sweep several."""
    db = _mk(tmp_path)
    tz = timezone(timedelta(hours=offset_hours))
    since = datetime(2026, 3, 10, 9, 0, tzinfo=tz)
    until = since + timedelta(hours=8)
    _add(db, "inside", since + timedelta(hours=1))

    got = collect_notes_context(db, since, until)
    assert [n["raw_text"] for n in got] == ["inside"], f"broken at UTC{offset_hours:+}"


def test_boundary_is_inclusive(tmp_path) -> None:
    db = _mk(tmp_path)
    tz = timezone(timedelta(hours=5, minutes=30))
    since = datetime(2026, 3, 10, 9, 0, tzinfo=tz)
    until = since + timedelta(hours=1)
    _add(db, "at-start", since)
    _add(db, "at-end", until)

    got = {n["raw_text"] for n in collect_notes_context(db, since, until)}
    assert got == {"at-start", "at-end"}


def test_finds_more_than_100_notes_in_window(tmp_path) -> None:
    """The old query fetched the newest 100 notes globally, so a busy day lost
    everything older — regardless of whether those notes were in the window."""
    db = _mk(tmp_path)
    tz = timezone(timedelta(hours=5, minutes=30))
    since = datetime(2026, 3, 10, 9, 0, tzinfo=tz)
    until = since + timedelta(hours=1)
    for i in range(150):
        _add(db, f"n{i}", since + timedelta(seconds=i))

    got = collect_notes_context(db, since, until)
    assert len(got) == 150


def test_excludes_notes_outside_window_when_table_is_large(tmp_path) -> None:
    """The 150 in-window notes are newest, so old out-of-window notes get cut
    off by a naive `limit=100` — they must not leak in either."""
    db = _mk(tmp_path)
    tz = timezone(timedelta(hours=5, minutes=30))
    since = datetime(2026, 3, 10, 9, 0, tzinfo=tz)
    until = since + timedelta(hours=1)
    _add(db, "old-outside", since - timedelta(days=3))
    for i in range(150):
        _add(db, f"n{i}", since + timedelta(seconds=i))

    got = {n["raw_text"] for n in collect_notes_context(db, since, until)}
    assert "old-outside" not in got
    assert len(got) == 150


def test_naive_timestamps_are_treated_as_utc(tmp_path) -> None:
    """Legacy rows may lack an offset; don't crash, and assume UTC."""
    db = _mk(tmp_path)
    tz = timezone(timedelta(hours=5, minutes=30))
    since = datetime(2026, 3, 10, 9, 0, tzinfo=tz)
    until = since + timedelta(hours=1)
    note = db.insert_note({"raw_text": "naive", "type": "text"})
    note_id = note["id"] if isinstance(note, dict) else note
    naive_utc = (since + timedelta(minutes=30)).astimezone(timezone.utc)
    db.execute(
        "UPDATE notes SET created_at = ? WHERE id = ?",
        (naive_utc.replace(tzinfo=None).isoformat(timespec="seconds"), note_id),
    )
    db.commit()

    assert [n["raw_text"] for n in collect_notes_context(db, since, until)] == ["naive"]


def test_empty_table_returns_empty(tmp_path) -> None:
    db = _mk(tmp_path)
    tz = timezone(timedelta(hours=5, minutes=30))
    since = datetime(2026, 3, 10, 9, 0, tzinfo=tz)
    assert collect_notes_context(db, since, since + timedelta(hours=1)) == []