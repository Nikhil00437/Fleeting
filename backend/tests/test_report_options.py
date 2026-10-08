"""#68, #67, #343, #344, #345, #348: Report generation options (tone, window, length, highlights, questions, custom sections)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services import dailylog


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "options.db")
    database.migrate()
    return database


@pytest.fixture
def sample_data(db: Database) -> None:
    # 08:30 (before workday)
    db.execute(
        """INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)
        VALUES ('spotify', 'Music', '2026-10-08T08:30:00', '2026-10-08T08:45:00', 900, '2026-10-08')"""
    )
    # 10:00 (workday)
    db.execute(
        """INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)
        VALUES ('cursor', 'fleeting/services/dailylog.py', '2026-10-08T10:00:00', '2026-10-08T12:00:00', 7200, '2026-10-08')"""
    )
    # 14:00 (workday)
    db.execute(
        """INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)
        VALUES ('firefox', 'Pull Request Review', '2026-10-08T14:00:00', '2026-10-08T15:30:00', 5400, '2026-10-08')"""
    )
    # 20:00 (after workday)
    db.execute(
        """INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)
        VALUES ('vlc', 'Movie', '2026-10-08T20:00:00', '2026-10-08T21:00:00', 3600, '2026-10-08')"""
    )
    db.commit()


@pytest.mark.anyio
async def test_generate_with_standup_tone(db: Database, sample_data: None) -> None:
    cfg = Config()
    cfg.llm.provider = "none"

    row = await dailylog.generate_daily_log(db, cfg, "2026-10-08", tone="standup")
    assert row is not None
    md = row["summary_md"]
    assert "Completed" in md or "In Flight" in md or "Blockers" in md


@pytest.mark.anyio
async def test_generate_with_terse_tone(db: Database, sample_data: None) -> None:
    cfg = Config()
    cfg.llm.provider = "none"

    row = await dailylog.generate_daily_log(db, cfg, "2026-10-08", tone="terse")
    assert row is not None
    assert "Daily Digest" in row["summary_md"]


@pytest.mark.anyio
async def test_generate_with_workday_window(db: Database, sample_data: None) -> None:
    cfg = Config()
    cfg.llm.provider = "none"

    # Restrict to 09:30 - 17:00: spotify (08:30) and vlc (20:00) should be excluded
    row = await dailylog.generate_daily_log(
        db, cfg, "2026-10-08", start_time="09:30", end_time="17:00"
    )
    assert row is not None
    md = row["summary_md"]
    assert "vlc" not in md.lower()
    assert "cursor" in md.lower() or "firefox" in md.lower()


@pytest.mark.anyio
async def test_generate_highlights_only_mode(db: Database, sample_data: None) -> None:
    cfg = Config()
    cfg.llm.provider = "none"

    row = await dailylog.generate_daily_log(db, cfg, "2026-10-08", highlights_only=True)
    assert row is not None
    md = row["summary_md"]
    assert "Top Accomplishments" in md or "Highlights" in md


@pytest.mark.anyio
async def test_generate_questions_for_tomorrow(db: Database, sample_data: None) -> None:
    cfg = Config()
    cfg.llm.provider = "none"

    row = await dailylog.generate_daily_log(db, cfg, "2026-10-08", questions_for_tomorrow=True)
    assert row is not None
    md = row["summary_md"]
    assert "Questions for Tomorrow" in md


@pytest.mark.anyio
async def test_generate_custom_sections_and_prompt_override(db: Database, sample_data: None) -> None:
    cfg = Config()
    cfg.llm.provider = "none"

    custom = [{"title": "Code Reviews & PRs", "prompt": "Focus on PR reviews."}]
    row = await dailylog.generate_daily_log(
        db,
        cfg,
        "2026-10-08",
        custom_sections=custom,
        prompt_override="Synthesize deeply",
    )
    assert row is not None
    assert "Code Reviews & PRs" in row["summary_md"]
    assert row.get("prompt_override") == "Synthesize deeply"


def test_api_generate_accepts_options(client) -> None:
    app_db = client.app.state.st.db
    app_db.execute(
        """INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)
        VALUES ('cursor', 'fleeting/services/dailylog.py', '2026-10-08T10:00:00', '2026-10-08T12:00:00', 7200, '2026-10-08')"""
    )
    app_db.commit()

    res = client.post(
        "/api/daily-log/generate",
        json={
            "day": "2026-10-08",
            "tone": "standup",
            "length": "short",
            "start_time": "09:00",
            "end_time": "18:00",
            "highlights_only": True,
            "questions_for_tomorrow": True,
            "custom_sections": [{"title": "Team Coordination"}],
            "prompt_override": "Be brief",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "summary_md" in data
    assert data.get("prompt_override") == "Be brief"
