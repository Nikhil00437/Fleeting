"""#53 project auto-detection + time per project."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from fleeting.config import ActivityConfig
from fleeting.services.projects import detect_project, project_seconds

NOW = datetime(2026, 10, 8, 9, 0, 0)
ROOTS = ("~/Projects", "~/Documents")


def test_a_git_repo_is_the_project() -> None:
    assert detect_project("vim src/db.py", repo="fleeting", roots=ROOTS) == "fleeting"


def test_a_path_under_a_watched_root_names_the_project() -> None:
    assert detect_project("~/Projects/fleeting/backend — nvim", roots=ROOTS) == "fleeting"
    import os

    home_docs = os.path.expanduser("~/Documents")
    assert detect_project(f"{home_docs}/taxes.ods — libreoffice", roots=ROOTS) == "taxes"


def test_an_owner_repo_title_is_the_project() -> None:
    assert detect_project("Nikhil00437/Fleeting — GitHub", roots=ROOTS) == "Fleeting"


def test_a_bare_project_name_in_the_title_counts() -> None:
    assert detect_project("fleeting: main.rs — zed", roots=ROOTS) == "fleeting"


def test_an_ordinary_window_has_no_project() -> None:
    assert detect_project("Inbox — Thunderbird", roots=ROOTS) is None


def test_the_repo_beats_the_title() -> None:
    """A checked-out repo is ground truth; the title is a guess."""
    assert detect_project("some unrelated tab", repo="fleeting", roots=ROOTS) == "fleeting"


def test_an_unreadable_root_is_skipped_not_fatal() -> None:
    assert detect_project("~/Nope/thing — vim", roots=ROOTS) is None


@pytest.fixture
def db(tmp_path: Path):
    from fleeting.db import Database

    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _session(db, project: str | None, seconds: int, app: str = "kitty") -> None:
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (app, f"work", NOW.isoformat(), NOW.isoformat(), seconds, "2026-10-08", project),
    )


def test_time_per_project_sums_and_sorts(db) -> None:
    _session(db, "fleeting", 600)
    _session(db, "Fleeting", 300, app="firefox")  # same project, other spelling
    _session(db, "taxes", 900)
    _session(db, None, 120)

    rows = project_seconds(db, "2026-10-08")
    assert [(r["project"], r["seconds"]) for r in rows] == [
        ("taxes", 900),
        ("fleeting", 900),
    ]


def test_time_per_project_can_hide_the_unlabelled_time(db) -> None:
    _session(db, "fleeting", 600)
    _session(db, None, 120)
    total = sum(r["seconds"] for r in project_seconds(db, "2026-10-08", include_empty=True))
    assert total == 720
    assert sum(r["seconds"] for r in project_seconds(db, "2026-10-08")) == 600


def test_a_day_with_no_sessions_is_empty_not_an_error(db) -> None:
    assert project_seconds(db, "1999-01-01") == []


def test_the_collector_records_a_detected_project(tmp_path: Path) -> None:
    from test_activity import FakeDB

    from fleeting.activity import ActivityCollector

    fake = FakeDB()
    cfg = ActivityConfig(
        poll_secs=20,
        idle_after_min=3,
        auto_daily_log=False,
        watch_dirs=str(tmp_path),
    )
    col = ActivityCollector(fake, cfg, probe=lambda: (None, None))
    col.poll_once(
        {"class": "kitty", "title": f"{tmp_path}/fleeting/main.rs — nvim"}, (0, 0), NOW
    )
    assert fake.rows[0]["project"] == "fleeting"

def test_projects_endpoint(client) -> None:
    client.post("/api/notes", json={"type": "text", "title": "x", "raw_text": "y"})
    body = client.get("/api/activity/projects?day=2026-10-08").json()
    assert body["day"] == "2026-10-08"
    assert body["projects"] == []
