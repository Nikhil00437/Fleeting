"""#336 git repo + branch next to terminal and editor sessions."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fleeting.activity import ActivityCollector, git_context
from fleeting.config import ActivityConfig

from test_activity import FakeDB

NOW = datetime(2026, 10, 8, 9, 0, 0)


def _collector() -> tuple[ActivityCollector, FakeDB]:
    db = FakeDB()
    cfg = ActivityConfig(poll_secs=20, idle_after_min=3, auto_daily_log=False)
    return ActivityCollector(db, cfg, probe=lambda: (None, None)), db


def _repo(tmp_path: Path, branch: str = "main") -> Path:
    repo = tmp_path / "fleeting"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    return repo


def test_branch_is_read_from_git_head(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "feat/search")
    assert git_context(repo / "src") == ("fleeting", "feat/search")


def test_a_detached_head_reports_the_short_sha(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".git" / "HEAD").write_text("9f2c1ab4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0\n")
    assert git_context(repo) == ("fleeting", "9f2c1ab")


def test_a_directory_without_git_has_no_context(tmp_path: Path) -> None:
    plain = tmp_path / "notes"
    plain.mkdir()
    assert git_context(plain) is None


def test_session_records_repo_and_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    cwd = str(repo / "src")
    col, db = _collector()
    col.poll_once({"class": "kitty", "title": "vim", "pid": os.getpid()}, (0, 0), NOW)
    # pid is our own process, so patch the resolver rather than fork a real repo
    col._cwd_of = lambda _pid: cwd  # type: ignore[method-assign]
    col.poll_once({"class": "kitty", "title": "vim 2", "pid": os.getpid()}, (1, 1), NOW)

    assert db.rows[0]["repo"] == "fleeting"
    assert db.rows[0]["branch"] == "main"


def test_an_unresolvable_pid_leaves_the_columns_empty() -> None:
    col, db = _collector()
    col.poll_once({"class": "kitty", "title": "vim", "pid": 999_999}, (0, 0), NOW)
    assert db.rows[0]["repo"] is None
    assert db.rows[0]["branch"] is None


def test_git_context_is_resolved_once_per_session(tmp_path: Path, monkeypatch) -> None:
    """The whole point is not spawning git per poll."""
    repo = _repo(tmp_path)
    calls: list[str] = []
    real = git_context

    def counting(cwd):
        calls.append(str(cwd))
        return real(cwd)

    col, _db = _collector()
    col._cwd_of = lambda _pid: str(repo)  # type: ignore[method-assign]
    monkeypatch.setattr("fleeting.activity.git_context", counting)
    col.poll_once({"class": "kitty", "title": "vim", "pid": 1}, (0, 0), NOW)
    col.poll_once({"class": "kitty", "title": "vim", "pid": 1}, (1, 1), NOW)
    col.poll_once({"class": "kitty", "title": "vim", "pid": 1}, (2, 2), NOW)
    assert len(calls) == 1