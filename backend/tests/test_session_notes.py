"""#334 annotate a session; #337 fill a gap in the record."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from fleeting.services.gaps import day_gaps
from fleeting.services.session_edit import annotate_session, session_annotations


@pytest.fixture
def db(tmp_path: Path):
    from fleeting.db import Database

    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _session(
    db,
    *,
    start="2026-10-08T09:00:00",
    end="2026-10-08T09:30:00",
    seconds=1800,
    day="2026-10-08",
) -> int:
    cur = db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)"
        " VALUES ('kitty', 'vim', ?, ?, ?, ?)",
        (start, end, seconds, day),
    )
    db.commit()
    return int(cur.lastrowid)


def test_a_session_note_round_trips(db) -> None:
    sid = _session(db)
    assert annotate_session(db, sid, "paired with Maya on the API shape")["note"]
    row = db.execute("SELECT note FROM activity WHERE id = ?", (sid,)).fetchone()
    assert row["note"] == "paired with Maya on the API shape"


def test_clearing_the_note_removes_it(db) -> None:
    sid = _session(db)
    annotate_session(db, sid, "draft")
    assert annotate_session(db, sid, "   ")["note"] == ""


def test_a_newline_in_a_note_is_flattened(db) -> None:
    sid = _session(db)
    annotate_session(db, sid, "two\nlines")
    row = db.execute("SELECT note FROM activity WHERE id = ?", (sid,)).fetchone()
    assert row["note"] == "two lines"


def test_annotations_come_back_newest_first(db) -> None:
    a = _session(db, start="2026-10-08T09:00:00", end="2026-10-08T09:30:00")
    b = _session(db, start="2026-10-08T11:00:00", end="2026-10-08T11:30:00")
    annotate_session(db, a, "older")
    annotate_session(db, b, "newer")
    assert [n["note"] for n in session_annotations(db, "2026-10-08")] == ["newer", "older"]


def test_annotations_reach_the_daily_log_transcript(db) -> None:
    from fleeting.services.dailylog import build_transcript

    sid = _session(db)
    annotate_session(db, sid, "call with the design review")
    sessions = [dict(r) for r in db.execute("SELECT * FROM activity").fetchall()]
    assert "call with the design review" in build_transcript(sessions)


def test_annotate_endpoint(client) -> None:
    db = client.app.state.st.db
    sid = _session(db)
    assert client.patch(f"/api/activity/sessions/{sid}", json={"note": "hello"}).json()["note"] == "hello"
    assert client.get("/api/activity/sessions/annotations?day=2026-10-08").json()[0]["note"] == "hello"
    assert client.patch("/api/activity/sessions/999", json={"note": "x"}).status_code == 404


def test_a_long_stretch_with_no_sessions_is_a_gap(db) -> None:
    _session(db, start="2026-10-08T09:00:00", end="2026-10-08T09:30:00")
    _session(db, start="2026-10-08T13:00:00", end="2026-10-08T13:30:00")
    gaps = day_gaps(db, "2026-10-08", min_minutes=45, day_bounds=("09:00:00", "13:30:00"))
    assert len(gaps) == 1
    assert gaps[0]["start"].endswith("09:30:00")
    assert gaps[0]["end"].endswith("13:00:00")
    assert gaps[0]["minutes"] == 210


def test_short_gaps_are_not_worth_asking_about(db) -> None:
    _session(db, start="2026-10-08T09:00:00", end="2026-10-08T09:30:00")
    _session(db, start="2026-10-08T09:45:00", end="2026-10-08T10:15:00")
    assert day_gaps(db, "2026-10-08", min_minutes=45, day_bounds=("09:00:00", "10:15:00")) == []


def test_gaps_on_a_day_with_no_sessions_are_all_day(db) -> None:
    gaps = day_gaps(db, "2026-10-08", min_minutes=45, day_bounds=("09:00:00", "20:00:00"))
    assert len(gaps) == 1
    assert gaps[0]["minutes"] == 660


def test_a_day_of_sessions_has_no_gaps(db) -> None:
    _session(db, start="2026-10-08T09:00:00", end="2026-10-08T17:00:00")
    assert day_gaps(db, "2026-10-08", min_minutes=45, day_bounds=("09:00:00", "10:15:00")) == []


def test_the_gaps_endpoint_returns_them_with_day_bounds(client) -> None:
    db = client.app.state.st.db
    _session(db, start="2026-10-08T09:00:00", end="2026-10-08T09:30:00")
    _session(db, start="2026-10-08T13:00:00", end="2026-10-08T13:30:00")
    body = client.get("/api/activity/gaps?day=2026-10-08").json()
    assert body["day"] == "2026-10-08"
    # the default window is the whole waking day, so the longest gap leads
    assert body["gaps"][0]["minutes"] == 600
    assert [g["minutes"] for g in body["gaps"]] == [600, 210, 120]
    assert "untracked stretches" in body["summary"]


def test_filling_a_gap_records_a_synthetic_session(client) -> None:
    db = client.app.state.st.db
    _session(db, start="2026-10-08T09:00:00", end="2026-10-08T09:30:00")
    _session(db, start="2026-10-08T13:00:00", end="2026-10-08T13:30:00")
    row = client.post(
        "/api/activity/gaps/fill",
        json={"at": "2026-10-08T11:00:00", "minutes": 45, "note": "offsite interview"},
    ).json()
    assert row["note"] == "offsite interview"
    assert row["first_seen"] == "2026-10-08T11:00:00"
    assert row["last_seen"] == "2026-10-08T11:45:00"


def test_filling_outside_a_gap_is_refused(client) -> None:
    db = client.app.state.st.db
    _session(db, start="2026-10-08T09:00:00", end="2026-10-08T17:00:00")
    assert client.post(
        "/api/activity/gaps/fill",
        json={"at": "2026-10-08T12:00:00", "minutes": 30, "note": "nope"},
    ).status_code == 422