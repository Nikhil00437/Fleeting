"""#72 editable reports: a human edit survives regeneration."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "log.db")
    database.migrate()
    return database


def test_a_stored_report_is_returned_as_is(db: Database) -> None:
    db.upsert_daily_log("2026-10-08", "# Digest\n\nAI text", "ollama")
    row = db.get_daily_log("2026-10-08")
    assert row is not None
    assert row["summary_md"] == "# Digest\n\nAI text"
    assert row["edited"] == 0


def test_saving_an_edit_marks_the_report_and_keeps_the_ai_text(db: Database) -> None:
    db.upsert_daily_log("2026-10-08", "AI text", "ollama")
    db.set_daily_log_edit("2026-10-08", "# Digest\n\nmy own words")

    row = db.get_daily_log("2026-10-08")
    assert row is not None
    assert row["edited"] == 1
    assert row["edited_body"] == "# Digest\n\nmy own words"
    assert row["summary_md"] == "AI text"  # the AI version stays for comparison


def test_regeneration_never_overwrites_an_edit(db: Database) -> None:
    """The whole point of #72: you corrected it, a regeneration must not undo it."""
    db.upsert_daily_log("2026-10-08", "AI text", "ollama")
    db.set_daily_log_edit("2026-10-08", "my own words")

    db.upsert_daily_log("2026-10-08", "regenerated AI text", "ollama")

    row = db.get_daily_log("2026-10-08")
    assert row is not None
    assert row["edited_body"] == "my own words"
    assert row["summary_md"] == "regenerated AI text"


def test_clearing_the_edit_restores_the_ai_version(db: Database) -> None:
    db.upsert_daily_log("2026-10-08", "AI text", "ollama")
    db.set_daily_log_edit("2026-10-08", "my own words")
    assert db.clear_daily_log_edit("2026-10-08") is True

    row = db.get_daily_log("2026-10-08")
    assert row is not None
    assert row["edited"] == 0
    assert row["edited_body"] in (None, "")
    assert db.clear_daily_log_edit("2026-10-08") is False


def test_an_empty_edit_clears_rather_than_storing_blank(db: Database) -> None:
    """Blanking the editor means "I want the AI version back", not "show nothing"."""
    db.upsert_daily_log("2026-10-08", "AI text", "ollama")
    db.set_daily_log_edit("2026-10-08", "   ")
    assert db.clear_daily_log_edit("2026-10-08") is False  # nothing was ever set
    row = db.get_daily_log("2026-10-08")
    assert row is not None and row["edited"] == 0


def test_the_effective_body_prefers_the_edit(db: Database) -> None:
    from fleeting.services.dailylog import effective_body

    db.upsert_daily_log("2026-10-08", "AI text", "ollama")
    assert effective_body(db.get_daily_log("2026-10-08")) == "AI text"

    db.set_daily_log_edit("2026-10-08", "mine")
    assert effective_body(db.get_daily_log("2026-10-08")) == "mine"


def test_the_effective_body_of_a_missing_report_is_empty() -> None:
    from fleeting.services.dailylog import effective_body

    assert effective_body(None) == ""


def test_the_edit_endpoint_saves_clears_and_reports(db, client) -> None:
    app_db = client.app.state.st.db
    app_db.upsert_daily_log("2026-10-08", "AI text", "ollama")

    saved = client.put("/api/daily-log/2026-10-08/edit", json={"body": "my words"}).json()
    assert saved["edited"] == 1
    assert saved["body"] == "my words"
    assert client.get("/api/daily-log?day=2026-10-08").json()["summary_md"] == "AI text"

    cleared = client.delete("/api/daily-log/2026-10-08/edit")
    assert cleared.status_code == 204
    assert client.get("/api/daily-log?day=2026-10-08").json()["edited"] == 0


def test_editing_a_report_that_was_never_generated_is_a_404(client) -> None:
    assert client.put("/api/daily-log/1999-01-01/edit", json={"body": "x"}).status_code == 404
    assert client.delete("/api/daily-log/1999-01-01/edit").status_code == 404


def test_a_blank_edit_is_refused(client) -> None:
    app_db = client.app.state.st.db
    app_db.upsert_daily_log("2026-10-08", "AI text", "ollama")
    # blanking clears the edit rather than storing an empty report
    assert client.put("/api/daily-log/2026-10-08/edit", json={"body": "  "}).status_code == 204
    assert client.get("/api/daily-log?day=2026-10-08").json()["edited"] == 0


def test_the_generated_report_mirrors_the_edited_body_to_the_vault(tmp_path: Path) -> None:
    """The vault copy is the report people read in Obsidian; an edit that does
    not reach it means the two silently diverge."""
    from fleeting.config import Config
    from fleeting.services import dailylog

    database = Database(tmp_path / "mirror.db")
    database.migrate()
    database.upsert_daily_log("2026-10-08", "AI text", "fallback")

    cfg = Config()
    cfg.llm.provider = "none"
    cfg.paths.vault_dir = str(tmp_path / "vault")
    cfg.paths.vault_sync = True

    dailylog.mirror_to_vault(cfg, "2026-10-08", "AI text")
    database.set_daily_log_edit("2026-10-08", "my corrected words")
    dailylog.mirror_to_vault(cfg, "2026-10-08", dailylog.effective_body(database.get_daily_log("2026-10-08")))

    written = list((tmp_path / "vault").rglob("2026-10-08*.md"))
    assert written, "the vault copy should exist"
    assert "my corrected words" in written[0].read_text()