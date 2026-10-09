"""#251 project time treemap tests."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services.treemap import get_project_treemap


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_treemap.db")
    database.migrate()
    return database


def test_treemap_empty(db: Database) -> None:
    cfg = Config()
    res = get_project_treemap(db, cfg, days=7)
    assert res["total_seconds"] == 0
    assert res["project_count"] == 0
    assert res["projects"] == []


def test_treemap_with_activity(db: Database) -> None:
    cfg = Config()
    # Insert 2 sessions for Fleeting (Code: 3600, Terminal: 1800 -> 5400)
    db.upsert_activity({
        "app_class": "Code",
        "title": "main.py",
        "project": "Fleeting",
        "day": "2026-10-08",
        "first_seen": "2026-10-08T10:00:00",
        "last_seen": "2026-10-08T11:00:00",
        "seconds": 3600,
        "idle_secs": 0,
    })
    db.upsert_activity({
        "app_class": "Alacritty",
        "title": "zsh",
        "project": "Fleeting",
        "day": "2026-10-08",
        "first_seen": "2026-10-08T11:00:00",
        "last_seen": "2026-10-08T11:30:00",
        "seconds": 1800,
        "idle_secs": 0,
    })

    # Insert 1 session for Docs (Firefox: 1800 -> 1800)
    db.upsert_activity({
        "app_class": "Firefox",
        "title": "Documentation",
        "project": "Docs",
        "day": "2026-10-08",
        "first_seen": "2026-10-08T12:00:00",
        "last_seen": "2026-10-08T12:30:00",
        "seconds": 1800,
        "idle_secs": 0,
    })

    res = get_project_treemap(db, cfg, days=7, day="2026-10-08")
    assert res["total_seconds"] == 7200
    assert res["project_count"] == 2

    p0 = res["projects"][0]
    assert p0["name"] == "Fleeting"
    assert p0["seconds"] == 5400
    assert p0["pct"] == 75.0
    assert len(p0["apps"]) == 2
    assert p0["apps"][0]["name"] == "Code"
    assert p0["apps"][0]["seconds"] == 3600
    assert p0["apps"][0]["pct_of_project"] == 66.7

    p1 = res["projects"][1]
    assert p1["name"] == "Docs"
    assert p1["seconds"] == 1800
    assert p1["pct"] == 25.0


def test_treemap_api(client) -> None:
    resp = client.get("/api/activity/treemap?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_seconds" in data
    assert "projects" in data
