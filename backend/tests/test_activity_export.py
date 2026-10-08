"""#342 activity export: session CSV and a project timesheet."""

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


def _session(db, *, day="2026-10-08", start="09:00:00", end="09:30:00", seconds=1800,
             app="kitty", project="fleeting", title="vim notes.md", note=None, branch=None,
             workspace=None) -> None:
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project,"
        " note, branch, workspace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (app, title, f"{day}T{start}", f"{day}T{end}", seconds, day, project, note, branch, workspace),
    )
    db.commit()


def test_sessions_csv_has_one_row_per_session(db) -> None:
    from fleeting.services.activity_export import render_sessions_csv

    _session(db)
    _session(db, app="firefox", project=None, title="docs", start="13:00:00", end="13:10:00", seconds=600)
    from fleeting.services.activity_export import sessions_in_range

    lines = render_sessions_csv(sessions_in_range(db)).strip().splitlines()
    assert lines[0] == "date,start,end,minutes,app,project,branch,workspace,title,note"
    assert lines[1].startswith("2026-10-08,09:00:00,09:30:00,30,kitty,fleeting")
    assert lines[2].split(",")[4] == "firefox"
    assert lines[2].split(",")[5] == ""  # unprojected, not "None"


def test_a_comma_in_a_window_title_is_quoted(db) -> None:
    from fleeting.services.activity_export import render_sessions_csv, sessions_in_range

    _session(db, title="README, notes.md — vim")
    row = render_sessions_csv(sessions_in_range(db)).strip().splitlines()[1]
    assert '"README, notes.md — vim"' in row


def test_a_quote_in_a_title_is_doubled(db) -> None:
    from fleeting.services.activity_export import render_sessions_csv, sessions_in_range

    _session(db, title='say "hi" in code')
    row = render_sessions_csv(sessions_in_range(db)).strip().splitlines()[1]
    assert '"say ""hi"" in code"' in row


def test_the_annotation_and_git_columns_come_through(db) -> None:
    from fleeting.services.activity_export import render_sessions_csv, sessions_in_range

    _session(db, note="paired with Maya", branch="feat/search", workspace="3")
    row = render_sessions_csv(sessions_in_range(db)).strip().splitlines()[1]
    assert row.endswith("feat/search,3,vim notes.md,paired with Maya")


def test_the_range_filter_is_inclusive_on_both_ends(db) -> None:
    from fleeting.services.activity_export import sessions_in_range

    _session(db, day="2026-10-07")
    _session(db, day="2026-10-08")
    _session(db, day="2026-10-09")
    assert {s["day"] for s in sessions_in_range(db, "2026-10-08", "2026-10-09")} == {
        "2026-10-08",
        "2026-10-09",
    }


def test_zero_second_sessions_are_left_out(db) -> None:
    from fleeting.services.activity_export import sessions_in_range

    _session(db, seconds=0, start="11:00:00", end="11:00:00")
    assert sessions_in_range(db) == []


def test_the_timesheet_groups_by_day_and_project(db) -> None:
    from fleeting.services.activity_export import render_timesheet_csv, sessions_in_range

    _session(db)
    _session(db, start="10:00:00", end="10:30:00", app="firefox")
    _session(db, app="kitty", project="taxes", start="15:00:00", end="15:30:00")
    rows = render_timesheet_csv(sessions_in_range(db)).strip().splitlines()
    assert rows[0] == "date,project,minutes,sessions,apps"
    # the apps cell holds a comma, so it is quoted like any other value
    assert '2026-10-08,fleeting,60,2,"firefox, kitty"' in rows
    assert "2026-10-08,taxes,30,1,kitty" in rows
    assert "2026-10-08,all,90,," in rows


def test_the_timesheet_calls_unprojected_work_unassigned(db) -> None:
    from fleeting.services.activity_export import render_timesheet_csv, sessions_in_range

    _session(db, project=None)
    assert "2026-10-08,unassigned,30,1,kitty" in render_timesheet_csv(sessions_in_range(db))


def test_an_empty_range_exports_headers_only(db) -> None:
    from fleeting.services.activity_export import render_sessions_csv, render_timesheet_csv

    assert render_sessions_csv([]).strip() == "date,start,end,minutes,app,project,branch,workspace,title,note"
    assert render_timesheet_csv([]).strip() == "date,project,minutes,sessions,apps"


def test_the_export_endpoint_serves_csv_with_a_filename(client) -> None:
    db = client.app.state.st.db
    _session(db)

    res = client.get("/api/activity/export?format=csv&day=2026-10-08")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert "fleeting" in res.text


def test_the_timesheet_endpoint_and_range_validation(client) -> None:
    db = client.app.state.st.db
    _session(db)

    res = client.get("/api/activity/export?format=timesheet&day_from=2026-10-01&day_to=2026-10-08")
    assert "2026-10-08,all,30,," in res.text
    assert "timesheet" in res.headers["content-disposition"]
    assert client.get("/api/activity/export?format=pdf").status_code == 422
    assert client.get("/api/activity/export?format=csv&day=nope").status_code == 422