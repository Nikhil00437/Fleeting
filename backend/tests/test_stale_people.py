"""#416: who you have not talked to in a while — opt-in, like the idea says.

Stale-contact lists are only useful if you asked for them. The window is a
setting, and zero means off, so the feature costs nothing until it is wanted.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.entities import stale_people


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _note_on(db: Database, name: str, day: str) -> str:
    return db.insert_note({
        "title": name,
        "raw_text": f"{name} called.",
        "type": "text",
        "created_at": f"{day}T09:00:00+00:00",
    })["id"]


def test_nothing_is_stale_when_the_window_is_off(db: Database) -> None:
    _note_on(db, "Priya", "2020-01-01")
    assert stale_people(db, 0) == []


def test_a_long_absent_contact_is_stale(db: Database) -> None:
    _note_on(db, "Priya", "2020-01-01")
    stale = stale_people(db, 90, today=date(2026, 10, 9))
    assert [p["name"] for p in stale] == ["Priya"]


def test_a_recent_contact_is_not_stale(db: Database) -> None:
    _note_on(db, "Priya", "2026-10-01")
    assert stale_people(db, 90, today=date(2026, 10, 9)) == []


def test_the_boundary_day_is_not_stale(db: Database) -> None:
    """Exactly N days ago is still inside the window, not outside it."""
    _note_on(db, "Priya", (date(2026, 10, 9) - timedelta(days=90)).isoformat())
    assert stale_people(db, 90, today=date(2026, 10, 9)) == []


def test_only_the_oldest_are_listed(db: Database) -> None:
    _note_on(db, "Priya", "2026-10-05")
    _note_on(db, "Tom", "2026-10-01")
    _note_on(db, "Ada", "2026-01-01")
    stale = stale_people(db, 90, today=date(2026, 10, 9))
    assert [p["name"] for p in stale] == ["Ada"]


def test_stale_list_is_ordered_by_how_long_ago(db: Database) -> None:
    """The longest silence is the one worth acting on."""
    _note_on(db, "Tom", "2026-06-01")
    _note_on(db, "Ada", "2026-01-01")
    stale = stale_people(db, 90, today=date(2026, 10, 9))
    assert [p["name"] for p in stale] == ["Ada", "Tom"]


def test_a_contact_with_no_last_seen_is_skipped(db: Database) -> None:
    """A row without a date cannot be judged stale or fresh."""
    db.insert_note({"title": "x", "raw_text": "Priya called.", "type": "text", "created_at": ""})
    assert stale_people(db, 90, today=date(2026, 10, 9)) == []


@pytest.mark.anyio
async def test_endpoint_is_empty_when_the_setting_is_off(client) -> None:
    client.post("/api/capture/text", json={"text": "Priya reviewed the router change."})
    assert client.get("/api/entities/stale").json() == []


@pytest.mark.anyio
async def test_endpoint_honours_the_configured_window(client) -> None:
    """The window comes from config when the request does not supply one."""
    st = client.app.state.st
    st.db.insert_note({
        "title": "old", "raw_text": "Priya called.", "type": "text",
        "created_at": "2020-01-01T09:00:00+00:00",
    })

    assert client.get("/api/entities/stale").json() == [], "off by default"

    st.cfg.entities.stale_days = 90
    try:
        r = client.get("/api/entities/stale")
        assert r.status_code == 200
        assert "Priya" in [p["name"] for p in r.json()]
    finally:
        st.cfg.entities.stale_days = 0


@pytest.mark.anyio
async def test_a_contact_seen_today_is_never_stale(client) -> None:
    client.post("/api/capture/text", json={"text": "Priya reviewed the router change."})
    assert client.get("/api/entities/stale", params={"days": 1}).json() == []
