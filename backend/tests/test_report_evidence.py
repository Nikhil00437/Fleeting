"""#73 & #350: Report sections and sentences linked to underlying sessions and notes (evidence mode)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services import dailylog


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "evidence.db")
    database.migrate()
    return database


def test_build_evidence_links_sections_and_sentences() -> None:
    sessions = [
        {
            "id": 101,
            "app_class": "cursor",
            "title": "fleeting/services/dailylog.py — cursor",
            "first_seen": "2026-10-08T09:30:00",
            "last_seen": "2026-10-08T11:00:00",
            "seconds": 5400,
            "day": "2026-10-08",
        },
        {
            "id": 102,
            "app_class": "firefox",
            "title": "FastAPI documentation — Mozilla Firefox",
            "first_seen": "2026-10-08T11:15:00",
            "last_seen": "2026-10-08T12:00:00",
            "seconds": 2700,
            "day": "2026-10-08",
        },
    ]
    notes = [
        {
            "id": "note-1",
            "title": "Refactor daily digest pipeline",
            "created_at": "2026-10-08T10:15:00Z",
        }
    ]
    git = [{"repo": "fleeting", "subject": "feat(reports): editable reports"}]

    digest_md = (
        "# Daily Digest — 2026-10-08\n\n"
        "## Executive Summary\n"
        "Focused day working on fleeting backend in Cursor and researching FastAPI.\n\n"
        "## Shipped & Active Projects\n"
        "- Worked on dailylog.py in Cursor for 1h 30m.\n\n"
        "## Deep Focus & Research\n"
        "- Researched FastAPI documentation in Firefox.\n\n"
        "## Captured Notes & Next Steps\n"
        "- Refactor daily digest pipeline.\n"
    )

    evidence = dailylog.build_evidence(digest_md, sessions, notes, git)
    assert isinstance(evidence, list)
    assert len(evidence) > 0

    # Section-level evidence (#73)
    sections = {item["section"]: item for item in evidence if "section" in item}
    assert "Shipped & Active Projects" in sections or "Executive Summary" in sections

    # Sentence-level evidence (#350)
    # The bullet about dailylog.py in Cursor should link to the cursor session
    cursor_items = [
        item for item in evidence
        if any(s.get("app") == "cursor" or s.get("id") == 101 for s in item.get("sessions", []))
    ]
    assert len(cursor_items) > 0
    assert any("dailylog" in item.get("text", "").lower() or "cursor" in item.get("text", "").lower() for item in cursor_items)

    # Note linking (#73)
    note_items = [
        item for item in evidence
        if any(n.get("id") == "note-1" for n in item.get("notes", []))
    ]
    assert len(note_items) > 0


def test_upsert_and_retrieve_daily_log_with_evidence(db: Database) -> None:
    ev_data = [{"text": "sentence 1", "sessions": [{"id": 1, "app": "cursor"}]}]
    ev_json = json.dumps(ev_data)

    db.upsert_daily_log("2026-10-08", "# Digest", "fallback", evidence=ev_json)

    row = db.get_daily_log("2026-10-08")
    assert row is not None
    assert row["evidence"] == ev_json


def test_daily_log_api_returns_evidence_structure(db, client) -> None:
    app_db = client.app.state.st.db
    ev_data = [{"text": "Worked in Cursor", "sessions": [{"id": 42, "app": "cursor", "title": "code"}]}]
    app_db.upsert_daily_log("2026-10-08", "# Digest", "fallback", evidence=json.dumps(ev_data))

    res = client.get("/api/daily-log?day=2026-10-08").json()
    assert "evidence" in res
    assert isinstance(res["evidence"], list)
    assert len(res["evidence"]) == 1
    assert res["evidence"][0]["text"] == "Worked in Cursor"


def test_daily_log_without_evidence_returns_empty_list(db, client) -> None:
    app_db = client.app.state.st.db
    app_db.upsert_daily_log("2026-10-08", "# Digest", "fallback")

    res = client.get("/api/daily-log?day=2026-10-08").json()
    assert res["evidence"] == []


def test_editing_a_report_preserves_evidence(db, client) -> None:
    app_db = client.app.state.st.db
    ev_data = [{"text": "original sentence", "sessions": [{"id": 1}]}]
    app_db.upsert_daily_log("2026-10-08", "# Digest", "fallback", evidence=json.dumps(ev_data))

    client.put("/api/daily-log/2026-10-08/edit", json={"body": "edited text"})

    res = client.get("/api/daily-log?day=2026-10-08").json()
    assert res["edited"] == 1
    assert res["evidence"] == ev_data
