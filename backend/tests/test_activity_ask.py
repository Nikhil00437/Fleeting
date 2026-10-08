"""#63 ask about a stretch of the timeline."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path: Path):
    from fleeting.db import Database

    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
def cfg(tmp_path: Path):
    from fleeting.config import Config

    c = Config()
    c.llm.provider = "none"  # the extractive path is what most tests want
    return c


def _s(db, start, end, app="kitty", title="vim", project=None, note=None, seconds=1800) -> None:
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day,"
        " project, note) VALUES (?, ?, ?, ?, ?, '2026-10-08', ?, ?)",
        (app, title, f"2026-10-08T{start}", f"2026-10-08T{end}", seconds, project, note),
    )
    db.commit()


def test_the_window_keeps_only_overlapping_sessions(db) -> None:  # noqa: D103
    from fleeting.services.activity_ask import sessions_in_window

    _s(db, "09:00:00", "09:30:00")
    _s(db, "10:00:00", "10:30:00")
    _s(db, "11:00:00", "11:30:00")
    inside = sessions_in_window(db, "2026-10-08", "2026-10-08T09:45:00", "2026-10-08T10:15:00")
    assert [s["first_seen"] for s in inside] == ["2026-10-08T10:00:00"]


def test_the_extractive_answer_reports_apps_and_notes(db) -> None:
    from fleeting.services.activity_ask import describe_window

    _s(db, "09:00:00", "10:00:00", app="kitty", seconds=3600, project="fleeting")
    _s(db, "10:00:00", "10:30:00", app="firefox", seconds=1800, note="reading docs")
    text = describe_window(
        [dict(r) for r in db.execute("SELECT * FROM activity ORDER BY first_seen")]
    )
    assert "2 sessions" in text
    assert "kitty: 1h" in text
    assert "firefox: 30m" in text
    assert "projects: fleeting" in text
    assert "reading docs" in text


def test_an_empty_window_says_so(db) -> None:
    from fleeting.services.activity_ask import describe_window

    assert "Nothing was tracked" in describe_window([])


def test_a_reversed_or_out_of_day_range_is_refused(db) -> None:
    from fleeting.services.activity_ask import validate_window

    with pytest.raises(ValueError):
        validate_window("2026-10-08", "2026-10-08T12:00:00", "2026-10-08T09:00:00")
    with pytest.raises(ValueError):
        validate_window("2026-10-08", "2026-10-07T23:00:00", "2026-10-08T01:00:00")
    with pytest.raises(ValueError):
        validate_window("2026-10-08", "09:00", "10:00")


def test_the_endpoint_answers_without_an_llm(db, client) -> None:
    app_db = client.app.state.st.db
    app_db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)"
        " VALUES ('kitty', 'vim', '2026-10-08T09:00:00', '2026-10-08T09:30:00', 1800, '2026-10-08')"
    )
    app_db.commit()

    body = client.post(
        "/api/activity/ask",
        json={"day": "2026-10-08", "start": "2026-10-08T09:00:00", "end": "2026-10-08T10:00:00"},
    ).json()
    assert body["answer"].startswith("1 sessions")
    assert body["used_llm"] is False
    assert body["sessions"][0]["app_class"] == "kitty"


def test_the_endpoint_validates_the_range(client) -> None:
    assert client.post(
        "/api/activity/ask",
        json={"day": "2026-10-08", "start": "2026-10-08T10:00:00", "end": "2026-10-08T09:00:00"},
    ).status_code == 422
    assert client.post(
        "/api/activity/ask",
        json={"day": "nope", "start": "2026-10-08T09:00:00", "end": "2026-10-08T10:00:00"},
    ).status_code == 422


def test_an_empty_window_answers_without_sessions(client) -> None:
    body = client.post(
        "/api/activity/ask",
        json={"day": "2026-10-08", "start": "2026-10-08T09:00:00", "end": "2026-10-08T10:00:00"},
    ).json()
    assert body["sessions"] == []
    assert "Nothing was tracked" in body["answer"]


def test_an_llm_failure_falls_back_to_the_record(db, cfg, monkeypatch) -> None:
    from fleeting.services import activity_ask

    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)"
        " VALUES ('kitty', 'vim', '2026-10-08T09:00:00', '2026-10-08T09:30:00', 1800, '2026-10-08')"
    )
    db.commit()

    async def boom(*args, **kwargs):
        raise RuntimeError("ollama is not running")

    monkeypatch.setattr(activity_ask, "_ask_llm", boom)
    result = asyncio.run(
        activity_ask.answer_window(db, cfg, "2026-10-08", "2026-10-08T09:00:00", "2026-10-08T10:00:00")
    )
    assert result["used_llm"] is False
    assert "1 sessions" in result["answer"]


def test_the_question_is_echoed_back(db, cfg) -> None:
    from fleeting.services import activity_ask

    result = asyncio.run(
        activity_ask.answer_window(
            db, cfg, "2026-10-08", "2026-10-08T09:00:00", "2026-10-08T10:00:00", "was I reading?"
        )
    )
    assert result["question"] == "was I reading?"


def test_a_successful_llm_answer_is_used(db, cfg, monkeypatch) -> None:
    from fleeting.services import activity_ask

    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)"
        " VALUES ('kitty', 'vim', '2026-10-08T09:00:00', '2026-10-08T09:30:00', 1800, '2026-10-08')"
    )
    db.commit()

    async def fake(*args, **kwargs):
        return "You were editing the router config."

    cfg.llm.provider = "ollama"  # otherwise the extractive path is all there is
    monkeypatch.setattr(activity_ask, "_ask_llm", fake)
    result = asyncio.run(
        activity_ask.answer_window(db, cfg, "2026-10-08", "2026-10-08T09:00:00", "2026-10-08T10:00:00")
    )
    assert result["used_llm"] is True
    assert "router config" in result["answer"]
