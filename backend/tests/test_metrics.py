"""#58 context switches, #62 today vs average, #59 calendar heatmap."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path: Path):
    from fleeting.db import Database

    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _s(db, day, hhmm_start, hhmm_end, app="kitty", project=None, seconds=None) -> None:
    start = datetime.fromisoformat(f"{day}T{hhmm_start}")
    end = datetime.fromisoformat(f"{day}T{hhmm_end}")
    secs = seconds if seconds is not None else int((end - start).total_seconds())
    db.execute(
        "INSERT INTO activity (app_class, project, first_seen, last_seen, seconds, day)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (app, project, start.isoformat(), end.isoformat(), secs, day),
    )
    db.commit()


# --- #58 context switches ----------------------------------------------------


def test_an_app_change_is_a_switch(db) -> None:
    from fleeting.services.metrics import context_switches

    _s(db, "2026-10-08", "09:00:00", "09:30:00", app="kitty")
    _s(db, "2026-10-08", "09:30:00", "10:00:00", app="firefox")
    result = context_switches(db, "2026-10-08")
    assert result["switches"] == 1
    assert result["reasons"]["app"] == 1
    assert result["sessions"] == 2


def test_a_project_change_inside_one_app_is_a_switch(db) -> None:
    from fleeting.services.metrics import context_switches

    _s(db, "2026-10-08", "09:00:00", "09:30:00", app="kitty", project="fleeting")
    _s(db, "2026-10-08", "09:30:00", "10:00:00", app="kitty", project="taxes")
    result = context_switches(db, "2026-10-08")
    assert result["switches"] == 1
    assert result["reasons"]["project"] == 1


def test_a_long_gap_in_one_app_is_a_switch(db) -> None:
    from fleeting.services.metrics import context_switches

    _s(db, "2026-10-08", "09:00:00", "09:30:00")
    _s(db, "2026-10-08", "12:00:00", "12:30:00")
    result = context_switches(db, "2026-10-08")
    assert result["reasons"]["gap"] == 1


def test_a_short_gap_is_reading_not_switching(db) -> None:
    from fleeting.services.metrics import context_switches

    _s(db, "2026-10-08", "09:00:00", "09:30:00")
    _s(db, "2026-10-08", "09:32:00", "10:00:00")
    assert context_switches(db, "2026-10-08")["switches"] == 0


def test_one_session_has_no_switches_and_no_seconds_per_switch(db) -> None:
    from fleeting.services.metrics import context_switches

    _s(db, "2026-10-08", "09:00:00", "09:30:00")
    result = context_switches(db, "2026-10-08")
    assert result["switches"] == 0
    assert result["seconds_per_switch"] is None


def test_seconds_per_switch_is_the_average_stretch(db) -> None:
    from fleeting.services.metrics import context_switches

    _s(db, "2026-10-08", "09:00:00", "10:00:00", app="kitty")  # 3600s
    _s(db, "2026-10-08", "10:00:00", "10:30:00", app="firefox")  # 1800s
    # 5400s over one switch
    assert context_switches(db, "2026-10-08")["seconds_per_switch"] == 5400


def test_an_empty_day_reports_zero(db) -> None:
    from fleeting.services.metrics import context_switches

    assert context_switches(db, "2026-10-08")["switches"] == 0


# --- #62 today vs average ----------------------------------------------------


def test_the_average_excludes_today(db) -> None:
    from fleeting.services.metrics import today_vs_average

    _s(db, "2026-10-07", "09:00:00", "11:00:00")  # 2h
    _s(db, "2026-10-06", "09:00:00", "10:00:00")  # 1h
    _s(db, "2026-10-08", "09:00:00", "12:00:00")  # 3h today
    result = today_vs_average(db, "2026-10-08", window=2)
    assert result["average_seconds"] == 5400  # (7200 + 3600) / 2
    assert result["seconds"] == 10800
    assert result["delta_seconds"] == 5400
    assert result["pct"] == 100


def test_a_quiet_day_reports_a_negative_delta(db) -> None:
    from fleeting.services.metrics import today_vs_average

    _s(db, "2026-10-07", "09:00:00", "13:00:00")  # 4h yesterday
    _s(db, "2026-10-08", "09:00:00", "10:00:00")  # 1h today
    result = today_vs_average(db, "2026-10-08", window=1)
    assert result["delta_seconds"] == -10800
    assert result["pct"] == -75


def test_with_no_history_there_is_no_percentage(db) -> None:
    from fleeting.services.metrics import today_vs_average

    _s(db, "2026-10-08", "09:00:00", "10:00:00")
    result = today_vs_average(db, "2026-10-08", window=7)
    assert result["average_seconds"] == 0
    assert result["pct"] is None
    assert result["days_tracked"] == 0


def test_the_window_only_counts_days_inside_it(db) -> None:
    from fleeting.services.metrics import today_vs_average

    _s(db, "2026-01-01", "09:00:00", "18:00:00")  # ancient, ignored
    _s(db, "2026-10-07", "09:00:00", "10:00:00")
    _s(db, "2026-10-08", "09:00:00", "10:00:00")
    result = today_vs_average(db, "2026-10-08", window=1)
    assert result["average_seconds"] == 3600


# --- #59 heatmap -------------------------------------------------------------


def test_the_heatmap_returns_one_cell_per_tracked_day(db) -> None:
    from fleeting.services.metrics import heatmap

    _s(db, "2026-10-07", "09:00:00", "10:30:00")
    _s(db, "2026-10-08", "09:00:00", "10:00:00")
    grid = heatmap(db, weeks=2, end="2026-10-08")
    assert [c["day"] for c in grid["cells"]] == ["2026-10-07", "2026-10-08"]
    assert [c["minutes"] for c in grid["cells"]] == [90, 60]
    assert grid["peak_minutes"] == 90
    assert grid["from"] == "2026-09-25"  # two weeks, ending on the 8th
    assert grid["to"] == "2026-10-08"


def test_the_heatmap_spans_the_asked_weeks(db) -> None:
    from fleeting.services.metrics import heatmap

    grid = heatmap(db, weeks=12, end="2026-10-08")
    assert (datetime.fromisoformat(grid["to"]) - datetime.fromisoformat(grid["from"])).days == 83


def test_an_empty_range_is_an_empty_heatmap(db) -> None:
    from fleeting.services.metrics import heatmap

    grid = heatmap(db, weeks=4, end="2026-10-08")
    assert grid["cells"] == []
    assert grid["peak_minutes"] == 0


# --- HTTP surface ------------------------------------------------------------


def test_metrics_endpoints(client) -> None:
    db = client.app.state.st.db
    _s(db, "2026-10-08", "09:00:00", "09:30:00", app="kitty")
    _s(db, "2026-10-08", "09:30:00", "10:00:00", app="firefox")

    assert client.get("/api/activity/metrics/switches?day=2026-10-08").json()["switches"] == 1
    assert client.get("/api/activity/metrics/compare?day=2026-10-08").json()["seconds"] == 3600
    grid = client.get("/api/activity/metrics/heatmap?weeks=4&end=2026-10-08").json()
    assert grid["cells"][0]["minutes"] == 60

    assert client.get("/api/activity/metrics/switches?day=nope").status_code == 422
    assert client.get("/api/activity/metrics/compare?day=2026-10-08&window=0").status_code == 422
    assert client.get("/api/activity/metrics/heatmap?weeks=0").status_code == 422