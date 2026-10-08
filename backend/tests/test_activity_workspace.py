"""#338 the Hyprland workspace each session ran on."""

from __future__ import annotations

from datetime import datetime

from fleeting.activity import ActivityCollector, probe_hyprland
from fleeting.config import ActivityConfig

from test_activity import FakeDB

NOW = datetime(2026, 10, 8, 9, 0, 0)


def _collector(probe=None) -> tuple[ActivityCollector, FakeDB]:
    db = FakeDB()
    cfg = ActivityConfig(poll_secs=20, idle_after_min=3, auto_daily_log=False)
    return ActivityCollector(db, cfg, probe=probe or (lambda: (None, None))), db


def test_workspace_is_recorded_on_the_session() -> None:
    col, db = _collector()
    col.poll_once({"class": "kitty", "title": "vim notes.md", "workspace": 3}, (0, 0), NOW)
    assert db.rows[0]["workspace"] == "3"


def test_a_session_keeps_the_workspace_it_started_on() -> None:
    """Switching workspace mid-session would rewrite history that already
    happened on the old one."""
    col, db = _collector()
    col.poll_once({"class": "kitty", "title": "vim", "workspace": 3}, (0, 0), NOW)
    col.poll_once({"class": "kitty", "title": "vim", "workspace": 7}, (1, 1), NOW)
    assert len(db.rows) == 1
    assert db.rows[0]["workspace"] == "3"


def test_a_missing_workspace_stores_none_not_zero() -> None:
    col, db = _collector()
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW)
    assert db.rows[0]["workspace"] is None


def test_the_default_probe_reports_the_active_workspace(monkeypatch) -> None:
    """hyprctl is the only source; the probe must not swallow its answer."""
    calls: list[list[str]] = []

    class Result:
        def __init__(self, out: str):
            self.stdout = out.encode()

    def fake_run(cmd, capture_output=True, timeout=5):
        calls.append(cmd)
        if cmd[-1] == "activewindow":
            return Result('{"class": "kitty", "title": "vim"}')
        if cmd[-1] == "activeworkspace":
            return Result('{"id": 3, "name": "3:dev"}')
        return Result("0,0")

    monkeypatch.setattr("fleeting.activity.subprocess.run", fake_run)
    win, _ = probe_hyprland()
    assert win is not None and win["workspace"] == "3"
    assert ["hyprctl", "-j", "activeworkspace"] in calls