"""#66 redaction: window titles are scrubbed *before* they reach the DB."""

from __future__ import annotations

from datetime import datetime

from fleeting.activity import ActivityCollector, redact_title
from fleeting.config import ActivityConfig

from test_activity import FakeDB

NOW = datetime(2026, 10, 8, 9, 0, 0)


def _collector(**cfg_kwargs) -> tuple[ActivityCollector, FakeDB]:
    db = FakeDB()
    cfg = ActivityConfig(poll_secs=20, idle_after_min=3, auto_daily_log=False, **cfg_kwargs)
    return ActivityCollector(db, cfg, probe=lambda: (None, None)), db


def test_emails_are_always_stripped() -> None:
    assert redact_title("mail — ada@example.com — invoice") == "mail — «redacted» — invoice"


def test_configured_tokens_are_stripped_case_insensitively() -> None:
    out = redact_title("gh: Nikhil/fleeting ghp_SECRET12345 open", ["ghp_"])
    assert "ghp_SECRET12345" not in out
    assert "gh:" in out and "open" in out


def test_empty_rules_leave_the_title_alone() -> None:
    assert redact_title("notes.md — vim") == "notes.md — vim"


def test_blank_config_entries_are_ignored() -> None:
    assert redact_title("plain title", ["", "  "]) == "plain title"


def test_collector_never_writes_a_raw_title() -> None:
    """The point of write-time redaction: the secret must not exist at all."""
    col, db = _collector(redact_patterns="ghp_")
    col.poll_once({"class": "Alacritty", "title": "git push ghp_TOTALLYSECRET"}, (0, 0), NOW)
    assert all("ghp_TOTALLYSECRET" not in r["title"] for r in db.rows)
    assert db.rows[0]["title"] == "git push «redacted»"


def test_redacted_titles_still_merge_into_one_session() -> None:
    """Two polls differing only in the secret are the same session."""
    col, db = _collector(redact_patterns="token")
    col.poll_once({"class": "firefox", "title": "inbox token=abc"}, (0, 0), NOW)
    col.poll_once({"class": "firefox", "title": "inbox token=def"}, (1, 1), NOW)
    assert len(db.rows) == 1


def test_the_blocklist_still_blocks_untouched_titles() -> None:
    col, db = _collector(redact_patterns="firefox")
    col.poll_once({"class": "firefox", "title": "some page"}, (0, 0), NOW)
    assert db.rows[0]["app_class"] == "firefox"