"""Tests for live activity endpoint and today_seconds telemetry."""

from __future__ import annotations

from datetime import datetime


def test_activity_live_returns_today_seconds(client):
    res = client.get("/api/activity/live")
    assert res.status_code == 200
    data = res.json()
    assert "today_seconds" in data
    assert isinstance(data["today_seconds"], int)
    assert data["today_seconds"] == 0


def test_activity_live_reflects_today_screentime(client):
    app = client.app
    st = app.state.st
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    now_iso = datetime.now().astimezone().isoformat()

    st.db.upsert_activity({
        "app_class": "testapp",
        "title": "Working on tests",
        "first_seen": now_iso,
        "last_seen": now_iso,
        "seconds": 120,
        "day": today,
    })

    res = client.get("/api/activity/live")
    assert res.status_code == 200
    data = res.json()
    assert data["today_seconds"] == 120
