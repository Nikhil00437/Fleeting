"""#46 random old note, #47 this-day-last-year, #297 weekly time capsule."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.recall import (
    recall_random_old,
    recall_this_day,
    recall_time_capsule,
    week_seed,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _note(db: Database, title: str, created: datetime) -> str:
    row = db.insert_note({
        "title": title,
        "type": "text",
        "summary": title,
        "raw_text": title,
        "tags": [],
    })
    db.execute(
        "UPDATE notes SET created_at = ? WHERE id = ?",
        (created.strftime("%Y-%m-%dT%H:%M:%SZ"), row["id"]),
    )
    db.commit()
    return row["id"]


def test_random_old_note_skips_recent_captures(db: Database) -> None:
    """#46: the card exists to resurface what has fallen out of the inbox."""
    _note(db, "fresh thought", datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc))
    old_id = _note(db, "ancient idea", datetime(2025, 8, 1, 9, 0, tzinfo=timezone.utc))

    hits = recall_random_old(db, older_than_days=90)
    assert [n["id"] for n in hits] == [old_id]


def test_random_old_note_is_empty_when_everything_is_fresh(db: Database) -> None:
    _note(db, "fresh thought", datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc))
    assert recall_random_old(db, older_than_days=90) == []


def test_random_old_note_seed_is_reproducible(db: Database) -> None:
    """A re-render must not reshuffle the card under the reader."""
    for i in range(5):
        _note(db, f"old {i}", datetime(2025, 1, 1 + i, 9, 0, tzinfo=timezone.utc))

    seeded = [n["id"] for n in recall_random_old(db, older_than_days=90, seed=42)]
    assert seeded == [n["id"] for n in recall_random_old(db, older_than_days=90, seed=42)]
    assert len(seeded) == 5
    assert len({n["id"] for n in recall_random_old(db, older_than_days=90)}) == 5


def test_this_day_matches_the_same_month_and_day_in_earlier_years(db: Database) -> None:
    """#47: 'this day last year' is a calendar match, not 365 days ago."""
    last_year = _note(db, "kota factory visit", datetime(2025, 10, 8, 9, 0, tzinfo=timezone.utc))
    two_years = _note(db, "old standup note", datetime(2024, 10, 8, 9, 0, tzinfo=timezone.utc))
    _note(db, "unrelated", datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc))

    today = datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)
    hits = recall_this_day(db, today=today)
    assert [n["id"] for n in hits] == [last_year, two_years]


def test_this_day_excludes_the_current_year(db: Database) -> None:
    """Today's own captures are not a memory — they are still in the inbox."""
    today_id = _note(db, "logged just now", datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))
    hits = recall_this_day(db, today=datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc))
    assert today_id not in {n["id"] for n in hits}


def test_this_day_ignores_leap_day_when_today_is_not_feb_29(db: Database) -> None:
    """29 Feb has no counterpart on 1 Mar — substring matching must not lie."""
    leap = _note(db, "leap day plan", datetime(2024, 2, 29, 9, 0, tzinfo=timezone.utc))
    hits = recall_this_day(db, today=datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc))
    assert leap not in {n["id"] for n in hits}


def test_time_capsule_is_older_than_a_year_and_stable_within_a_week(db: Database) -> None:
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    recent_id = _note(db, "recent", datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc))
    old_ids = {_note(db, f"old {i}", datetime(2025, 1, 1 + i, 9, 0, tzinfo=timezone.utc)) for i in range(6)}

    first = recall_time_capsule(db, now=now)
    assert first is not None
    assert first["id"] in old_ids
    assert first["id"] != recent_id
    # Same ISO week → same capsule; the pick only advances weekly.
    assert recall_time_capsule(db, now=now + timedelta(days=2))["id"] == first["id"]
    assert week_seed(now) == week_seed(now + timedelta(days=2))


def test_time_capsule_returns_none_without_old_notes(db: Database) -> None:
    _note(db, "recent", datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc))
    assert recall_time_capsule(db, now=datetime(2026, 10, 8, tzinfo=timezone.utc)) is None

def test_recall_endpoint_returns_each_kind(client) -> None:
    """The endpoint is the only surface the UI needs."""
    _seed(client)
    assert isinstance(client.get("/api/recall?kind=random").json(), list)
    assert isinstance(client.get("/api/recall?kind=this_day").json(), list)
    capsule = client.get("/api/recall?kind=capsule").json()
    assert isinstance(capsule, list) and len(capsule) <= 1
    assert client.get("/api/recall?kind=bogus").status_code == 422


def _seed(client) -> None:
    import sqlite3

    db_path = client.app.state.st.db.path
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO notes (id, type, title, summary, raw_text, tags, created_at, "
            "updated_at) VALUES ('old-1', 'text', 'from the archive', 'archive', "
            "'archive', '[]', '2024-01-05T09:00:00Z', '2024-01-05T09:00:00Z')"
        )
        con.commit()
