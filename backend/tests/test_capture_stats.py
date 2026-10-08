"""#163 Capture frequency stats: notes per day, top tags over time."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import pytest

from fleeting.db import Database, datetime_now_local
from fleeting.services.capture_stats import get_capture_frequency_stats


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "capture_stats.db")
    database.migrate()
    return database


def test_capture_frequency_empty_db(db: Database) -> None:
    res = get_capture_frequency_stats(db, days=7)
    assert res["days"] == 7
    assert res["total_captures"] == 0
    assert res["avg_per_day"] == 0.0
    assert res["busiest_day"] is None
    assert len(res["notes_per_day"]) == 7
    assert len(res["top_tags_over_time"]) == 0
    assert len(res["by_dow"]) == 7
    assert len(res["by_hour"]) == 24


def test_capture_frequency_with_notes_and_tags(db: Database) -> None:
    now_local = datetime_now_local()
    today_str = now_local.strftime("%Y-%m-%d")

    # Insert note today with tags
    db.insert_note(
        {
            "title": "Architecture decision record",
            "raw_text": "Details on SQLite schema",
            "type": "text",
            "tags": ["arch", "backend"],
        }
    )
    # Insert another note today (voice)
    db.insert_note(
        {
            "title": "Voice memo",
            "raw_text": "Dictated note",
            "type": "voice",
            "tags": ["arch", "ideas"],
        }
    )

    res = get_capture_frequency_stats(db, days=7)
    assert res["total_captures"] == 2
    assert res["avg_per_day"] > 0
    assert res["busiest_day"]["day"] == today_str
    assert res["busiest_day"]["count"] == 2

    # Check daily breakdown
    today_pt = next(p for p in res["notes_per_day"] if p["day"] == today_str)
    assert today_pt["count"] == 2
    assert today_pt["text"] == 1
    assert today_pt["voice"] == 1

    # Check top tags
    tag_names = [t["tag"] for t in res["top_tags_over_time"]]
    assert "arch" in tag_names
    arch_stat = next(t for t in res["top_tags_over_time"] if t["tag"] == "arch")
    assert arch_stat["total"] == 2
    assert len(arch_stat["timeline"]) == 7


def test_capture_frequency_api(client) -> None:
    st = client.app.state.st
    st.db.insert_note(
        {
            "title": "API test note",
            "raw_text": "Testing endpoint",
            "type": "text",
            "tags": ["testing"],
        }
    )

    resp = client.get("/api/stats/capture-frequency?days=14")
    assert resp.status_code == 200
    data = resp.json()
    assert data["days"] == 14
    assert data["total_captures"] >= 1
    assert len(data["notes_per_day"]) == 14
    assert any(t["tag"] == "testing" for t in data["top_tags_over_time"])
