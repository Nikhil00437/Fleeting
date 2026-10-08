"""#74 Export a report as Markdown or PDF."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services import report_export


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "export.db")
    database.migrate()
    return database


SAMPLE_MD = """# Daily Digest — 2026-10-08

## Executive Summary
Logged 6h of active focus across 4 applications.

## Shipped & Active Projects
- **Git (fleeting)** — feat: report exports
- **fleeting** — 5 modified files

## Deep Focus & Research
- **10:00–12:00** (2h) · **cursor** — *fleeting/services/report_export.py*
"""


def test_render_markdown_export() -> None:
    md = report_export.render_markdown_export("2026-10-08", SAMPLE_MD)
    assert "Daily Digest — 2026-10-08" in md
    assert "Executive Summary" in md
    assert md.endswith("\n")


def test_render_pdf_export() -> None:
    pdf_bytes = report_export.render_pdf_export("2026-10-08", SAMPLE_MD)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100
    assert pdf_bytes.startswith(b"%PDF-")


def test_pure_python_pdf_fallback() -> None:
    pdf_bytes = report_export.render_pure_python_pdf("2026-10-08", SAMPLE_MD)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes


def test_api_export_markdown(client) -> None:
    db = client.app.state.st.db
    db.upsert_daily_log("2026-10-08", SAMPLE_MD, "ollama")

    res = client.get("/api/daily-log/2026-10-08/export?format=md")
    assert res.status_code == 200
    assert "text/markdown" in res.headers["content-type"]
    assert "daily-log-2026-10-08.md" in res.headers["content-disposition"]
    assert "Executive Summary" in res.text


def test_api_export_pdf(client) -> None:
    db = client.app.state.st.db
    db.upsert_daily_log("2026-10-08", SAMPLE_MD, "ollama")

    res = client.get("/api/daily-log/2026-10-08/export?format=pdf")
    assert res.status_code == 200
    assert "application/pdf" in res.headers["content-type"]
    assert "daily-log-2026-10-08.pdf" in res.headers["content-disposition"]
    assert res.content.startswith(b"%PDF-")


def test_api_export_missing_log_returns_404(client) -> None:
    res = client.get("/api/daily-log/2026-01-01/export?format=md")
    assert res.status_code == 404
