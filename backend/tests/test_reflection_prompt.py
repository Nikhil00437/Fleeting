"""#347 reflection journaling prompt after the report, saved as a linked note."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services import dailylog


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "reflection.db")
    database.migrate()
    return database


def test_reflection_prompts_are_generated() -> None:
    prompts = dailylog.get_reflection_prompts("2026-10-08", "# Daily Digest\nWorked on fleeting")
    assert len(prompts) >= 3
    assert any("focus" in p.lower() or "problem" in p.lower() or "insight" in p.lower() for p in prompts)


def test_api_get_reflection_prompt(client) -> None:
    res = client.get("/api/daily-log/2026-10-08/reflection")
    assert res.status_code == 200
    data = res.json()
    assert "prompts" in data
    assert len(data["prompts"]) >= 3
    assert data["note"] is None


def test_api_save_reflection_as_linked_note(client) -> None:
    # Save a reflection
    res = client.post(
        "/api/daily-log/2026-10-08/reflection",
        json={
            "prompt": "What gave you momentum today?",
            "text": "Deep focus on rewriting the reports pipeline with zero distractions.",
        },
    )
    assert res.status_code == 200
    note = res.json()
    assert note["id"]
    assert "Daily Reflection — 2026-10-08" in note["title"]
    assert "Deep focus" in note["raw_text"]
    assert "reflection" in note["tags"]
    assert "daily/2026-10-08" in note["tags"]

    # Verify GET now returns the created note
    get_res = client.get("/api/daily-log/2026-10-08/reflection")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["note"] is not None
    assert get_data["note"]["id"] == note["id"]


def test_api_save_empty_reflection_rejects(client) -> None:
    res = client.post(
        "/api/daily-log/2026-10-08/reflection",
        json={"prompt": "prompt", "text": "   "},
    )
    assert res.status_code == 422
