"""Weekly digest over HTTP: read it, generate it, and know it's scheduled."""

from __future__ import annotations

import pytest


def test_get_weekly_log_defaults_to_last_week(client) -> None:
    r = client.get("/api/activity/weekly-log")
    assert r.status_code == 200
    body = r.json()
    # Last week is finished; this week is still accumulating.
    assert body["week"] < body["this_week"]
    assert body["report"] is None


def test_get_weekly_log_accepts_an_explicit_week(client) -> None:
    r = client.get("/api/activity/weekly-log", params={"week": "2026-10-05"})
    assert r.status_code == 200
    assert r.json()["week"] == "2026-10-05"


def test_get_weekly_log_returns_the_stored_report(client) -> None:
    client.app.state.st.db.upsert_weekly_log("2026-10-05", "# Weekly\n\nbody", "m")
    body = client.get("/api/activity/weekly-log", params={"week": "2026-10-05"}).json()
    assert "body" in body["report"]["summary_md"]
    assert body["report"]["model"] == "m"


def test_get_weekly_log_includes_the_week_shape(client) -> None:
    """The summary numbers come with the report, not only when generating."""
    body = client.get("/api/activity/weekly-log", params={"week": "2026-10-05"}).json()
    assert "summary" in body
    assert len(body["summary"]["days"]) == 7
    assert body["summary"]["week_start"] == "2026-10-05"
    assert body["summary"]["week_end"] == "2026-10-11"


def test_generate_weekly_log_stores_and_returns_it(client, monkeypatch) -> None:
    st = client.app.state.st
    st.db.upsert_activity(
        {
            "app_class": "code",
            "title": "work",
            "first_seen": "2026-10-05T10:00:00+00:00",
            "last_seen": "2026-10-05T11:00:00+00:00",
            "seconds": 3600,
            "day": "2026-10-05",
        }
    )
    st.cfg.activity.watch_dirs = ""

    import fleeting.services.weeklylog as mod

    async def fake(transcript: str, week: str, cfg):
        return "# Weekly Digest\n\nvia llm", "m"

    monkeypatch.setattr(mod, "generate_with_llm", fake)

    r = client.post("/api/activity/weekly-log/generate", json={"week": "2026-10-05"})

    assert r.status_code == 200
    assert "via llm" in r.json()["report"]["summary_md"]
    assert st.db.get_weekly_log("2026-10-05") is not None


def test_generate_weekly_log_rejects_an_empty_week(client) -> None:
    client.app.state.st.cfg.activity.watch_dirs = ""
    r = client.post("/api/activity/weekly-log/generate", json={"week": "2026-10-05"})
    assert r.status_code == 400
    assert "no tracked activity" in r.json()["detail"].lower()


def test_generate_weekly_log_falls_back_without_an_llm(client) -> None:
    """Provider=none must still produce a report, not an error."""
    st = client.app.state.st
    st.cfg.llm.provider = "none"
    st.cfg.activity.watch_dirs = ""
    st.db.upsert_activity(
        {
            "app_class": "code",
            "title": "work",
            "first_seen": "2026-10-05T10:00:00+00:00",
            "last_seen": "2026-10-05T11:00:00+00:00",
            "seconds": 3600,
            "day": "2026-10-05",
        }
    )
    r = client.post("/api/activity/weekly-log/generate", json={"week": "2026-10-05"})
    assert r.status_code == 200
    assert "Weekly" in r.json()["report"]["summary_md"]
    assert r.json()["report"]["model"] == "fallback"


def test_generate_publishes_an_sse_event(client, monkeypatch) -> None:
    st = client.app.state.st
    st.cfg.activity.watch_dirs = ""
    st.db.upsert_activity(
        {
            "app_class": "code",
            "title": "w",
            "first_seen": "2026-10-05T10:00:00+00:00",
            "last_seen": "2026-10-05T11:00:00+00:00",
            "seconds": 3600,
            "day": "2026-10-05",
        }
    )
    import fleeting.services.weeklylog as mod

    async def fake(transcript: str, week: str, cfg):
        return "# Weekly Digest\n\nx", "m"

    monkeypatch.setattr(mod, "generate_with_llm", fake)

    q = st.bus.subscribe()
    client.post("/api/activity/weekly-log/generate", json={"week": "2026-10-05"})
    payload = q.get_nowait()
    assert "weekly.updated" in payload


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def test_auto_weekly_log_setting_round_trips(client) -> None:
    body = client.put("/api/settings", json={"activity_auto_weekly_log": False}).json()
    assert body["activity_auto_weekly_log"] is False
    assert client.get("/api/settings").json()["activity_auto_weekly_log"] is False


def test_auto_weekly_log_defaults_on() -> None:
    from fleeting.config import Config

    assert Config().activity.auto_weekly_log is True


def test_config_file_preserves_the_new_key(tmp_path, monkeypatch) -> None:
    import tomllib

    import fleeting.config as fcfg

    monkeypatch.setattr(fcfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    fcfg.save_config(fcfg.Config())
    raw = tomllib.loads((tmp_path / "config.toml").read_text())
    assert raw["activity"]["auto_weekly_log"] is True
