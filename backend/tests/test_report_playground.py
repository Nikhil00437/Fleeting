"""#349 Report playground: test prompt changes against telemetry without persisting."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services import dailylog


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "playground.db")
    database.migrate()
    return database


@pytest.fixture
def sample_activity(db: Database) -> None:
    db.execute(
        """INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)
        VALUES ('cursor', 'fleeting/services/dailylog.py', '2026-10-08T10:00:00', '2026-10-08T12:00:00', 7200, '2026-10-08')"""
    )
    db.execute(
        """INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)
        VALUES ('firefox', 'GitHub Pull Request', '2026-10-08T14:00:00', '2026-10-08T15:30:00', 5400, '2026-10-08')"""
    )
    db.commit()


@pytest.mark.anyio
async def test_playground_does_not_persist_or_overwrite_daily_log(
    db: Database, sample_activity: None
) -> None:
    cfg = Config()
    cfg.llm.provider = "none"

    # Precondition: no stored daily log
    assert db.get_daily_log("2026-10-08") is None

    result = await dailylog.preview_daily_log_playground(
        db, cfg, "2026-10-08", prompt_override="Focus strictly on Python architecture."
    )

    assert result is not None
    assert "preview_md" in result
    assert "transcript" in result
    assert "system_prompt" in result
    assert "Focus strictly on Python architecture." in result["system_prompt"]
    assert "cursor" in result["transcript"]

    # Postcondition: Still no stored daily log in DB!
    assert db.get_daily_log("2026-10-08") is None


@pytest.mark.anyio
async def test_playground_preserves_existing_stored_log(
    db: Database, sample_activity: None
) -> None:
    cfg = Config()
    cfg.llm.provider = "none"

    # Store an existing daily log
    db.upsert_daily_log("2026-10-08", "# Stored Original Digest", "ollama")
    original = db.get_daily_log("2026-10-08")
    assert original["summary_md"] == "# Stored Original Digest"

    # Run playground with changes
    result = await dailylog.preview_daily_log_playground(
        db, cfg, "2026-10-08", tone="terse", highlights_only=True
    )
    assert result["preview_md"]

    # Stored daily log in DB is intact and untouched
    after = db.get_daily_log("2026-10-08")
    assert after["summary_md"] == "# Stored Original Digest"


def test_playground_api_endpoint(client) -> None:
    st = client.app.state.st
    st.db.execute(
        """INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)
        VALUES ('terminal', 'pytest suite', '2026-10-08T10:00:00', '2026-10-08T11:00:00', 3600, '2026-10-08')"""
    )
    st.db.commit()

    resp = client.post(
        "/api/activity/daily-log/playground",
        json={
            "day": "2026-10-08",
            "prompt_override": "Summarize in bullet points only",
            "tone": "balanced",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["day"] == "2026-10-08"
    assert "Summarize in bullet points only" in data["system_prompt"]
    assert data["preview_md"]

    # Ensure daily_logs is not persisted
    assert st.db.get_daily_log("2026-10-08") is None
