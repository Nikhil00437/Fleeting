"""#69 Standup generator: yesterday, today, blockers."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services.standup import (
    collect_standup_data,
    fallback_standup,
    generate_standup,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "standup.db")
    database.migrate()
    return database


def test_collect_standup_data_finds_yesterday_work(db: Database) -> None:
    yesterday = "2026-10-07"
    today = "2026-10-08"

    # Completed task yesterday
    db.insert_task(
        {
            "text": "Fix login bug",
            "done": True,
            "completed_at": f"{yesterday}T15:30:00+00:00",
        }
    )
    # Session yesterday
    db.upsert_activity(
        {
            "app_class": "code",
            "title": "editing auth.py",
            "first_seen": f"{yesterday}T10:00:00+00:00",
            "last_seen": f"{yesterday}T12:00:00+00:00",
            "seconds": 7200,
            "day": yesterday,
        }
    )

    cfg = Config()
    cfg.activity.watch_dirs = ""
    data = collect_standup_data(db, cfg, day=today)

    assert data["day"] == today
    assert data["previous_day"] == yesterday
    assert len(data["yesterday_tasks"]) == 1
    assert data["yesterday_tasks"][0]["text"] == "Fix login bug"
    assert data["yesterday_seconds"] == 7200
    assert any(a["app_class"] == "code" for a in data["yesterday_apps"])


def test_collect_standup_data_finds_today_tasks_and_blockers(db: Database) -> None:
    today = "2026-10-08"

    # Open task for today
    t_today = db.insert_task(
        {
            "text": "Deploy to staging",
            "done": False,
            "due_date": today,
            "priority": "P1",
        }
    )
    # Blocked task
    t_blocked = db.insert_task(
        {
            "text": "Database migration",
            "done": False,
            "waiting_for": "Ops approval",
        }
    )

    cfg = Config()
    cfg.activity.watch_dirs = ""
    data = collect_standup_data(db, cfg, day=today)

    today_texts = [t["text"] for t in data["today_tasks"]]
    assert "Deploy to staging" in today_texts

    blocker_texts = [b["text"] for b in data["blockers"]]
    assert "Database migration" in blocker_texts


def test_fallback_standup_renders_yesterday_today_blockers(db: Database) -> None:
    yesterday = "2026-10-07"
    today = "2026-10-08"

    db.insert_task(
        {
            "text": "Shipped feature X",
            "done": True,
            "completed_at": f"{yesterday}T14:00:00+00:00",
        }
    )
    db.insert_task(
        {
            "text": "Ship feature Y",
            "done": False,
            "due_date": today,
        }
    )
    db.insert_task(
        {
            "text": "Review PR Z",
            "done": False,
            "waiting_for": "Alice",
        }
    )

    cfg = Config()
    cfg.activity.watch_dirs = ""
    data = collect_standup_data(db, cfg, day=today)
    md = fallback_standup(data)

    assert "## Yesterday" in md
    assert "Shipped feature X" in md
    assert "## Today" in md
    assert "Ship feature Y" in md
    assert "## Blockers" in md
    assert "Alice" in md or "Review PR Z" in md


def test_fallback_standup_when_clean_and_empty(db: Database) -> None:
    cfg = Config()
    cfg.activity.watch_dirs = ""
    data = collect_standup_data(db, cfg, day="2026-10-08")
    md = fallback_standup(data)

    assert "## Yesterday" in md
    assert "## Today" in md
    assert "## Blockers" in md
    assert "None" in md


@pytest.mark.anyio
async def test_generate_standup_uses_fallback_offline(db: Database) -> None:
    cfg = Config()
    cfg.llm.provider = "none"
    cfg.activity.watch_dirs = ""

    result = await generate_standup(db, cfg, day="2026-10-08")
    assert result["day"] == "2026-10-08"
    assert result["model"] == "fallback"
    assert "## Yesterday" in result["standup_md"]
    assert "## Today" in result["standup_md"]
    assert "## Blockers" in result["standup_md"]


def test_standup_api_get(client) -> None:
    r = client.get("/api/activity/standup", params={"day": "2026-10-08"})
    assert r.status_code == 200
    data = r.json()
    assert data["day"] == "2026-10-08"
    assert "## Yesterday" in data["standup_md"]
    assert "## Today" in data["standup_md"]
    assert "## Blockers" in data["standup_md"]


def test_standup_save_as_note(client) -> None:
    r = client.post(
        "/api/activity/standup/save-as-note",
        json={"day": "2026-10-08", "standup_md": "# Standup\n\n- Did work."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "note" in body
    note_id = body["note"]["id"]
    note = client.app.state.st.db.get_note(note_id)
    assert note is not None
    assert "Daily Standup — 2026-10-08" in note["title"]
    assert "Did work" in note["raw_text"]

