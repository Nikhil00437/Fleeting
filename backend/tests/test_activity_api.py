"""API tests for activity tracking + daily log endpoints."""

from __future__ import annotations

import pytest


def test_activity_day_empty(client):
    r = client.get("/api/activity/day")
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is False
    assert body["total_seconds"] == 0
    assert body["apps"] == []
    assert body["collector"]["enabled"] is False


def test_activity_pause_roundtrip(client):
    assert client.get("/api/activity/live").json()["session"] is None
    r = client.post("/api/activity/pause", json={"paused": True})
    assert r.json()["paused"] is True
    assert client.get("/api/activity/day").json()["paused"] is True
    client.post("/api/activity/pause", json={"paused": False})
    assert client.get("/api/activity/live").json()["paused"] is False


def test_activity_day_invalid_date(client):
    assert client.get("/api/activity/day", params={"day": "not-a-date"}).status_code == 422


def test_daily_log_missing(client):
    body = client.get("/api/activity/daily-log").json()
    assert body["summary_md"] is None


def test_daily_log_generate_without_activity(client):
    # a window with no sessions AND no file activity cannot produce a report
    r = client.post("/api/activity/daily-log/generate", json={"day": "2020-01-01"})
    assert r.status_code == 422


def test_daily_log_generate_future_rejected(client):
    r = client.post("/api/activity/daily-log/generate", json={"day": "2099-01-01"})
    assert r.status_code == 422


def test_daily_log_fallback_generated(client, monkeypatch):
    """With LLM disabled, generation produces the deterministic digest."""
    # inject activity directly through the collector's DB path
    st = client.app.state.st
    st.db.upsert_activity({
        "app_class": "code", "title": "fleeting — main.py",
        "first_seen": "2026-09-01T09:00:00", "last_seen": "2026-09-01T10:00:00",
        "seconds": 3600, "day": "2026-09-01",
    })
    st.db.commit()
    r = client.post("/api/activity/daily-log/generate", json={"day": "2026-09-01"})
    assert r.status_code == 200
    row = r.json()
    assert row["model"] == "fallback"
    assert "# Daily Digest — 2026-09-01" in row["summary_md"]
    # second GET returns the stored log
    assert "Daily Digest" in client.get("/api/activity/daily-log", params={"day": "2026-09-01"}).json()["summary_md"]


def test_daily_log_rolling_syncs_screentime_milestone(client):
    from datetime import datetime

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    st = client.app.state.st
    st.db.upsert_activity({
        "app_class": "code", "title": "fleeting — main.py",
        "first_seen": f"{today}T09:00:00", "last_seen": f"{today}T10:15:00",
        "seconds": 4500, "day": today,
    })
    st.db.commit()
    r = client.post("/api/activity/daily-log/generate", json={"rolling": True})
    assert r.status_code == 200
    assert st.db.kv_get(f"digest_screentime_hours_{today}") == "1"


def test_daily_log_generate_acquires_digest_lock(client):
    from unittest.mock import AsyncMock, patch

    st = client.app.state.st
    assert st.digest_lock is not None

    lock_acquired = False
    orig_acquire = st.digest_lock.acquire

    async def tracking_acquire():
        nonlocal lock_acquired
        lock_acquired = True
        return await orig_acquire()

    st.digest_lock.acquire = tracking_acquire

    with patch("fleeting.services.dailylog.generate_daily_log", new=AsyncMock(return_value={"day": "2026-10-01", "summary_md": "log"})):
        r = client.post("/api/activity/daily-log/generate", json={"day": "2026-10-01"})
        assert r.status_code == 200
        assert lock_acquired is True



