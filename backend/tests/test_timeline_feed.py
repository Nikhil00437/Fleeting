"""#339 one chronological feed: sessions, tasks finished, notes captured."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path: Path):
    from fleeting.db import Database

    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _at(db, hour: int, minute: int = 0) -> str:
    return datetime(2026, 10, 8, hour, minute, 0).isoformat(timespec="seconds")


def _session(db, hour: int, app="kitty", title="vim", seconds=600) -> int:
    cur = db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)"
        " VALUES (?, ?, ?, ?, ?, '2026-10-08')",
        (app, title, _at(db, hour), _at(db, hour), seconds),
    )
    db.commit()
    return int(cur.lastrowid)


def _task(db, text: str, done: bool, when: str) -> str:
    # insert_task auto-creates an inbox note; point it at an older one so it
    # does not land in the feed as noise.
    old = db.insert_note({"type": "text", "title": "inbox", "raw_text": "x", "tags": []})
    db.execute("UPDATE notes SET created_at = '2026-10-01T09:00:00Z' WHERE id = ?", (old["id"],))
    db.commit()
    row = db.insert_task({"text": text, "note_id": old["id"]})
    db.update_task(
        row["id"],
        {"done": done, "completed_at": when if done else None, "due_date": "2026-10-08"},
    )
    db.commit()
    return row["id"]


def _note(db, title: str, when: str) -> str:
    row = db.insert_note({"type": "text", "title": title, "raw_text": title, "tags": []})
    db.execute("UPDATE notes SET created_at = ? WHERE id = ?", (when, row["id"]))
    db.commit()
    return row["id"]


def test_the_feed_merges_three_kinds_in_time_order(db) -> None:
    from fleeting.services.timeline import day_events

    _session(db, 9)
    _task(db, "ship the parser", True, _at(db, 11))
    _note(db, "meeting notes", _at(db, 14))
    _task(db, "not this one", False, _at(db, 15))

    kinds = [(e["kind"], e["at"][11:16]) for e in day_events(db, "2026-10-08")]
    assert kinds == [("session", "09:00"), ("task", "11:00"), ("note", "14:00")]


def test_events_carry_enough_to_render_them(db) -> None:
    from fleeting.services.timeline import day_events

    _session(db, 9, app="firefox", title="docs")
    _task(db, "ship it", True, _at(db, 11))
    _note(db, "thought", _at(db, 14))

    session, task, note = day_events(db, "2026-10-08")
    assert session["id"] and session["label"] == "firefox"
    assert task["label"] == "ship it" and task["done"] is True
    assert note["label"] == "thought"


def test_other_days_are_not_included(db) -> None:
    from fleeting.services.timeline import day_events

    _note(db, "yesterday", "2026-10-07T10:00:00")
    _note(db, "today", "2026-10-08T10:00:00")
    assert [e["label"] for e in day_events(db, "2026-10-08")] == ["today"]


def test_an_empty_day_is_an_empty_feed(db) -> None:
    from fleeting.services.timeline import day_events

    assert day_events(db, "2026-10-08") == []


def test_the_feed_can_be_filtered_to_one_kind(db) -> None:
    from fleeting.services.timeline import day_events

    _session(db, 9)
    _note(db, "thought", _at(db, 14))
    assert {e["kind"] for e in day_events(db, "2026-10-08", kinds=("note",))} == {"note"}


def test_the_timeline_endpoint(db, client) -> None:
    _note(db, "from the api", _at(db, 10))
    body = client.get("/api/activity/timeline?day=2026-10-08").json()
    assert body["day"] == "2026-10-08"
    assert body["events"][0]["label"] == "from the api"
    assert client.get("/api/activity/timeline?day=2026-10-08&kinds=task").json()["events"] == []
    assert client.get("/api/activity/timeline?day=nope").status_code == 422