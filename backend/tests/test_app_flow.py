"""#246 app-to-app switching Sankey or flow chart."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import pytest
from fleeting.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _s(db: Database, day: str, start_time: str, end_time: str, app: str, seconds: int = 300) -> None:
    s = datetime.fromisoformat(f"{day}T{start_time}")
    e = datetime.fromisoformat(f"{day}T{end_time}")
    db.execute(
        "INSERT INTO activity (app_class, first_seen, last_seen, seconds, day)"
        " VALUES (?, ?, ?, ?, ?)",
        (app, s.isoformat(), e.isoformat(), seconds, day),
    )
    db.commit()


def test_empty_activity_returns_zero_switches(db: Database) -> None:
    from fleeting.services.metrics import app_switching_flow

    res = app_switching_flow(db, "2026-10-09")
    assert res["total_switches"] == 0
    assert res["nodes"] == []
    assert res["links"] == []
    assert res["top_loops"] == []


def test_sequential_switches_create_links_and_nodes(db: Database) -> None:
    from fleeting.services.metrics import app_switching_flow

    day = "2026-10-09"
    # User works in code -> chrome -> code -> terminal -> chrome
    _s(db, day, "09:00:00", "09:20:00", "code", seconds=1200)
    _s(db, day, "09:20:00", "09:35:00", "chrome", seconds=900)
    _s(db, day, "09:35:00", "10:00:00", "code", seconds=1500)
    _s(db, day, "10:00:00", "10:10:00", "terminal", seconds=600)
    _s(db, day, "10:10:00", "10:25:00", "chrome", seconds=900)

    res = app_switching_flow(db, day)
    assert res["total_switches"] == 4

    # Nodes
    node_ids = {n["id"] for n in res["nodes"]}
    assert node_ids == {"code", "chrome", "terminal"}

    # Links: code->chrome (1), chrome->code (1), code->terminal (1), terminal->chrome (1)
    links = {(l["source"], l["target"]): l["value"] for l in res["links"]}
    assert links[("code", "chrome")] == 1
    assert links[("chrome", "code")] == 1
    assert links[("code", "terminal")] == 1
    assert links[("terminal", "chrome")] == 1

    # Top loop: code <-> chrome (2 switches together)
    assert len(res["top_loops"]) > 0
    loop = res["top_loops"][0]
    assert {loop["app_a"], loop["app_b"]} == {"code", "chrome"}
    assert loop["count"] == 2


def test_window_days_aggregates_across_days(db: Database) -> None:
    from fleeting.services.metrics import app_switching_flow

    # Day 1
    _s(db, "2026-10-08", "09:00:00", "09:30:00", "code")
    _s(db, "2026-10-08", "09:30:00", "10:00:00", "slack")
    # Day 2
    _s(db, "2026-10-09", "10:00:00", "10:30:00", "code")
    _s(db, "2026-10-09", "10:30:00", "11:00:00", "slack")

    res = app_switching_flow(db, "2026-10-09", days=2)
    assert res["total_switches"] == 2
    links = {(l["source"], l["target"]): l["value"] for l in res["links"]}
    assert links[("code", "slack")] == 2


def test_api_metric_flow(client) -> None:
    resp = client.get("/api/activity/metrics/flow?day=2026-10-09&days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_switches" in data
    assert "nodes" in data
    assert "links" in data
    assert "top_loops" in data
