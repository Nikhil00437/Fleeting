"""#54 manual session editing: relabel, split, merge, delete."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from fleeting.services.session_edit import (
    delete_session,
    merge_sessions,
    relabel_session,
    session_edits,
    split_session,
)


@pytest.fixture
def db(tmp_path: Path):
    from fleeting.db import Database

    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _session(db, *, app="kitty", title="vim", start="2026-10-08T09:00:00", end="2026-10-08T09:30:00",
             seconds=1800, day="2026-10-08") -> int:
    cur = db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (app, title, start, end, seconds, day),
    )
    db.commit()
    return int(cur.lastrowid)


def _get(db, session_id: int) -> dict:
    return db.execute("SELECT * FROM activity WHERE id = ?", (session_id,)).fetchone()


def test_relabelling_changes_the_title_only(db) -> None:
    sid = _session(db)
    relabel_session(db, sid, "reading hyprland docs")
    row = _get(db, sid)
    assert row["title"] == "reading hyprland docs"
    assert row["seconds"] == 1800


def test_relabelling_strips_newlines(db) -> None:
    """A newline in a title breaks the session list's layout."""
    sid = _session(db)
    relabel_session(db, sid, "two\nlines")
    assert _get(db, sid)["title"] == "two lines"


def test_relabelling_a_missing_session_is_an_error(db) -> None:
    with pytest.raises(KeyError):
        relabel_session(db, 999, "nope")


def test_deleting_removes_the_row(db) -> None:
    sid = _session(db)
    assert delete_session(db, sid) is True
    assert _get(db, sid) is None
    assert delete_session(db, sid) is False


def test_splitting_produces_two_sessions_sharing_the_total_time(db) -> None:
    sid = _session(db)
    first, second = split_session(db, sid, "2026-10-08T09:10:00")
    a, b = _get(db, first), _get(db, second)
    assert (a["first_seen"], a["last_seen"]) == ("2026-10-08T09:00:00", "2026-10-08T09:10:00")
    assert (b["first_seen"], b["last_seen"]) == ("2026-10-08T09:10:00", "2026-10-08T09:30:00")
    assert a["seconds"] + b["seconds"] == 1800


def test_splitting_keeps_app_and_title(db) -> None:
    sid = _session(db)
    _, second = split_session(db, sid, "2026-10-08T09:10:00")
    assert _get(db, second)["app_class"] == "kitty"
    assert _get(db, second)["title"] == "vim"


def test_splitting_outside_the_session_is_refused(db) -> None:
    sid = _session(db)
    with pytest.raises(ValueError):
        split_session(db, sid, "2026-10-08T08:00:00")
    with pytest.raises(ValueError):
        split_session(db, sid, "2026-10-08T10:00:00")
    assert _get(db, sid)["seconds"] == 1800


def test_splitting_on_the_exact_boundary_is_refused(db) -> None:
    sid = _session(db)
    with pytest.raises(ValueError):
        split_session(db, sid, "2026-10-08T09:00:00")


def test_splitting_a_sub_two_second_session_is_refused(db) -> None:
    sid = _session(db, start="2026-10-08T09:00:00", end="2026-10-08T09:00:01", seconds=1)
    with pytest.raises(ValueError):
        split_session(db, sid, "2026-10-08T09:00:01")


def test_merging_folds_seconds_and_span(db) -> None:
    a = _session(db, title="vim", start="2026-10-08T09:00:00", end="2026-10-08T09:10:00", seconds=600)
    b = _session(db, title="docs", start="2026-10-08T09:20:00", end="2026-10-08T09:30:00", seconds=400)
    merged = merge_sessions(db, [a, b])
    row = _get(db, merged)
    assert row["seconds"] == 1000
    assert row["first_seen"] == "2026-10-08T09:00:00"
    assert row["last_seen"] == "2026-10-08T09:30:00"
    assert row["title"] == "vim"  # the earlier session keeps its label
    assert _get(db, b) is None


def test_merging_across_days_is_refused(db) -> None:
    a = _session(db, day="2026-10-08")
    b = _session(db, day="2026-10-07")
    with pytest.raises(ValueError):
        merge_sessions(db, [a, b])


def test_merging_one_session_is_refused(db) -> None:
    a = _session(db)
    with pytest.raises(ValueError):
        merge_sessions(db, [a])


def test_each_edited_session_remembers_its_last_edit(db) -> None:
    """One row per session, as the schema says: enough to answer "what did I
    change here?", without growing a second log."""
    sid = _session(db)
    relabel_session(db, sid, "renamed")
    assert session_edits(db)[0]["note"].startswith("relabelled")

    second = _session(db, start="2026-10-08T11:00:00", end="2026-10-08T11:30:00")
    _, tail = split_session(db, sid, "2026-10-08T09:10:00")
    notes = {e["session_key"]: e["note"] for e in session_edits(db)}
    assert notes[str(sid)].startswith("split")
    assert notes[str(second)] == "" if str(second) in notes else True  # untouched

    delete_session(db, tail)
    assert {e["session_key"]: e["note"] for e in session_edits(db)}[str(tail)] == "deleted"


# --- HTTP surface -----------------------------------------------------------


def test_session_edit_endpoints(client) -> None:
    db = client.app.state.st.db
    sid = _session(db)

    assert client.patch(f"/api/activity/sessions/{sid}", json={"title": "renamed"}).json()["title"] == "renamed"
    body = client.post(f"/api/activity/sessions/{sid}/split", json={"at": "2026-10-08T09:10:00"}).json()
    assert len(body) == 2
    merged = client.post("/api/activity/sessions/merge", json={"ids": [row["id"] for row in body]}).json()
    assert merged["seconds"] == 1800

    trail = client.get("/api/activity/sessions/edits").json()
    # one row per session, holding that session's most recent edit
    assert [t["note"].split()[0] for t in trail] == ["merged"]
    assert trail[0]["session_key"] == str(merged["id"])

    assert client.delete(f"/api/activity/sessions/{merged['id']}").status_code == 204
    assert client.delete(f"/api/activity/sessions/{merged['id']}").status_code == 404
    assert client.get("/api/activity/sessions/edits").json()[0]["note"] == "deleted"


def test_bad_edits_are_422_not_500(client) -> None:
    db = client.app.state.st.db
    sid = _session(db)
    assert client.post(f"/api/activity/sessions/{sid}/split", json={"at": "07:00"}).status_code == 422
    assert client.post("/api/activity/sessions/merge", json={"ids": [sid]}).status_code == 422
    assert client.patch("/api/activity/sessions/999", json={"title": "x"}).status_code == 404