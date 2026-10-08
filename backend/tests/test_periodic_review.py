"""#70, #171, #172: Parameterised periodic review generator (month, quarter, year / Wrapped)."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services.periodic_review import (
    aggregate_review_period,
    fallback_periodic_review,
    generate_periodic_review,
    parse_period,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "review.db")
    database.migrate()
    return database


def test_parse_period_cases() -> None:
    m_start, m_end, m_title = parse_period("month", "2026-10")
    assert m_start == "2026-10-01"
    assert m_end == "2026-10-31"
    assert "Monthly Review" in m_title

    q_start, q_end, q_title = parse_period("quarter", "2026-Q3")
    assert q_start == "2026-07-01"
    assert q_end == "2026-09-30"
    assert "Quarterly Review" in q_title

    y_start, y_end, y_title = parse_period("year", "2026")
    assert y_start == "2026-01-01"
    assert y_end == "2026-12-31"
    assert "Wrapped" in y_title


def test_aggregate_review_period_collects_logs_and_metrics(db: Database) -> None:
    # Insert weekly logs in Oct 2026
    db.upsert_weekly_log("2026-10-05", "# Week 1\n\nDid feature A.", "m")
    db.upsert_weekly_log("2026-10-12", "# Week 2\n\nDid feature B.", "m")
    # Weekly log outside Oct
    db.upsert_weekly_log("2026-11-02", "# Nov Week\n\nNovember work.", "m")

    # Insert daily log
    db.upsert_daily_log("2026-10-08", "# Daily 10-08\n\nGood day.", "m")

    # Insert activity sessions
    db.upsert_activity(
        {
            "app_class": "cursor",
            "title": "coding",
            "first_seen": "2026-10-06T10:00:00+00:00",
            "last_seen": "2026-10-06T12:00:00+00:00",
            "seconds": 7200,
            "day": "2026-10-06",
        }
    )

    # Completed tasks
    db.insert_task(
        {
            "text": "Shipped v0.8 feature",
            "done": True,
            "completed_at": "2026-10-10T14:00:00+00:00",
        }
    )

    cfg = Config()
    cfg.activity.watch_dirs = ""

    agg = aggregate_review_period(db, cfg, "month", "2026-10")
    assert agg["start_date"] == "2026-10-01"
    assert agg["end_date"] == "2026-10-31"
    assert len(agg["weekly_logs"]) == 2
    assert len(agg["daily_logs"]) == 1
    assert agg["total_seconds"] == 7200
    assert len(agg["completed_tasks"]) == 1
    assert agg["completed_tasks"][0]["text"] == "Shipped v0.8 feature"


def test_fallback_periodic_review_renders_month(db: Database) -> None:
    db.upsert_weekly_log("2026-10-05", "# Week 1\n\nShipped authentication.", "m")
    cfg = Config()
    cfg.activity.watch_dirs = ""

    agg = aggregate_review_period(db, cfg, "month", "2026-10")
    md = fallback_periodic_review(agg)

    assert "# Monthly Review — 2026-10" in md
    assert "Shipped authentication" in md


def test_fallback_periodic_review_renders_annual_wrapped(db: Database) -> None:
    db.upsert_activity(
        {
            "app_class": "neovim",
            "title": "editing",
            "first_seen": "2026-05-10T10:00:00+00:00",
            "last_seen": "2026-05-10T12:00:00+00:00",
            "seconds": 18000,
            "day": "2026-05-10",
        }
    )
    db.insert_task(
        {
            "text": "Passed the bar",
            "done": True,
            "completed_at": "2026-08-01T10:00:00+00:00",
        }
    )

    cfg = Config()
    cfg.activity.watch_dirs = ""
    agg = aggregate_review_period(db, cfg, "year", "2026")
    md = fallback_periodic_review(agg)

    assert "Wrapped" in md
    assert "Passed the bar" in md
    assert "neovim" in md


@pytest.mark.anyio
async def test_generate_periodic_review_offline(db: Database) -> None:
    cfg = Config()
    cfg.llm.provider = "none"
    cfg.activity.watch_dirs = ""

    res = await generate_periodic_review(db, cfg, "quarter", "2026-Q3")
    assert res["kind"] == "quarter"
    assert res["period"] == "2026-Q3"
    assert res["model"] == "fallback"
    assert "# Quarterly Review — 2026-Q3" in res["review_md"]


def test_periodic_review_api_endpoints(client) -> None:
    r = client.get("/api/activity/review", params={"kind": "month", "period": "2026-10"})
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "month"
    assert data["period"] == "2026-10"
    assert "review_md" in data

    # Save as note
    r_save = client.post(
        "/api/activity/review/save-as-note",
        json={"kind": "month", "period": "2026-10", "review_md": "# Month Review\n\nGreat month."},
    )
    assert r_save.status_code == 200
    body = r_save.json()
    assert body["ok"] is True
    note = client.app.state.st.db.get_note(body["note"]["id"])
    assert note is not None
    assert "Monthly Review — 2026-10" in note["title"]
    assert "review" in note["tags"]
