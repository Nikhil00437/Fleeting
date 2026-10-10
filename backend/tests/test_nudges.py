"""#110: a nightly "what did I forget?" nudge for open loops.

The whole feature is a question asked at one moment of the day: of the things
you said you'd do and have not, which are still yours? Everything here is
deterministic and reads from trackers that already exist (#169 unfinished
threads, the task table). No model call — a nudge that invents its own items
is worse than no nudge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting import notify
from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.nudges import nightly_nudge, nightly_notify, notify_text, should_notify
from fleeting.services.unfinished_threads import get_unfinished_threads


@pytest.fixture
def env(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    cfg = Config()
    cfg.paths.vault_dir = str(tmp_path / "vault")
    return db, cfg, EventBus()


def _task(db: Database, text: str, **kw) -> str:
    return db.insert_task({"text": text, **kw})["id"]


def _thread(db: Database, day: str, text: str) -> None:
    """A real open thread: #169 derives threads from daily-log markdown."""
    db.upsert_daily_log(
        day,
        f"## Loose ends\n\n- {text}\n\n## Done\n\n- shipped the thing\n",
        "test",
    )


# ---- what counts as an open loop ------------------------------------------


def test_an_overdue_task_is_a_loop(env):
    db, cfg, bus = env
    _task(db, "call the dentist", due_date="2026-01-01")

    res = nightly_nudge(db, cfg, day="2026-10-10")

    assert res["count"] == 1
    assert "dentist" in res["items"][0]["text"]


def test_a_task_due_later_is_not_a_loop(env):
    db, cfg, bus = env
    _task(db, "future thing", due_date="2030-01-01")

    assert nightly_nudge(db, cfg, day="2026-10-10")["count"] == 0


def test_a_task_due_today_is_not_yet_a_loop(env):
    """It is not forgotten at 9am; it becomes a loop tomorrow."""
    db, cfg, bus = env
    _task(db, "today thing", due_date="2026-10-10")

    assert nightly_nudge(db, cfg, day="2026-10-10")["count"] == 0


def test_a_done_task_is_never_a_loop(env):
    db, cfg, bus = env
    tid = _task(db, "already done", due_date="2026-01-01")
    db.update_task(tid, {"done": 1})

    assert nightly_nudge(db, cfg, day="2026-10-10")["count"] == 0


def test_an_archived_tasks_note_is_not_a_loop(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "old", "raw_text": "old", "status": "done"})
    _task(db, "buried task", due_date="2026-01-01", note_id=note["id"])
    db.update_note(note["id"], {"archived": 1})

    assert nightly_nudge(db, cfg, day="2026-10-10")["count"] == 0


def test_an_unresolved_thread_is_a_loop(env):
    db, cfg, bus = env
    _thread(db, "2026-10-09", "waiting on priya for the invoice")

    res = nightly_nudge(db, cfg, day="2026-10-10")

    assert res["count"] == 1
    assert "priya" in res["items"][0]["text"]


def test_a_resolved_thread_is_not_a_loop(env):
    from fleeting.services.unfinished_threads import resolve_thread

    db, cfg, bus = env
    _thread(db, "2026-10-09", "settled already")
    threads = get_unfinished_threads(db)
    assert threads, "the fixture should produce a thread to resolve"
    resolve_thread(db, threads[0]["id"], "resolve")

    assert nightly_nudge(db, cfg, day="2026-10-10")["count"] == 0


# ---- ordering and shape ---------------------------------------------------


def test_the_most_overdue_comes_first(env):
    db, cfg, bus = env
    _task(db, "due recently", due_date="2026-10-05")
    _task(db, "due ages ago", due_date="2025-01-01")

    res = nightly_nudge(db, cfg, day="2026-10-10")

    assert "ages ago" in res["items"][0]["text"]


def test_each_item_says_what_kind_of_loop_it_is(env):
    """A thread and a task need different follow-up, so they must be told apart."""
    db, cfg, bus = env
    _thread(db, "2026-10-09", "an open question")
    _task(db, "a late task", due_date="2026-01-01")

    kinds = {i["kind"] for i in nightly_nudge(db, cfg, day="2026-10-10")["items"]}

    assert kinds == {"thread", "task"}


def test_an_empty_inbox_produces_no_nudge(env):
    db, cfg, bus = env
    res = nightly_nudge(db, cfg, day="2026-10-10")
    assert res["count"] == 0
    assert res["items"] == []


def test_the_list_is_capped(env):
    """A hundred overdue tasks is not a nudge, it is a wall."""
    db, cfg, bus = env
    for i in range(40):
        _task(db, f"overdue {i}", due_date="2020-01-01")

    res = nightly_nudge(db, cfg, day="2026-10-10", limit=10)

    assert len(res["items"]) == 10
    # The count is what actually matched, not what survived the cap — hiding
    # it would make "10" read as "that is all of them".
    assert res["count"] == 40


def test_a_sensitive_note_never_reaches_the_nudge_text(env):
    """#26: a sensitive note's body must not be sent anywhere, including here."""
    db, cfg, bus = env
    note = db.insert_note({"title": "secret", "raw_text": "secret", "status": "done"})
    db.update_note(note["id"], {"sensitive": 1})
    _task(db, "a task in a sensitive note", due_date="2026-01-01", note_id=note["id"])

    res = nightly_nudge(db, cfg, day="2026-10-10")

    assert res["count"] == 0


# ---- once a night, not once per boot --------------------------------------


def test_the_nudge_fires_once_per_day(env):
    db, cfg, bus = env
    cfg.notifications.nightly_nudge = True
    _task(db, "overdue", due_date="2026-01-01")

    assert should_notify(db, cfg, day="2026-10-10") is True
    assert should_notify(db, cfg, day="2026-10-10") is False


def test_a_new_day_gets_another_nudge(env):
    db, cfg, bus = env
    cfg.notifications.nightly_nudge = True
    _task(db, "overdue", due_date="2026-01-01")

    assert should_notify(db, cfg, day="2026-10-10") is True
    assert should_notify(db, cfg, day="2026-10-11") is True


def test_nothing_is_sent_when_there_is_nothing_to_forget(env):
    db, cfg, bus = env

    assert should_notify(db, cfg, day="2026-10-10") is False


def test_the_nudge_is_off_unless_asked_for(env):
    """Opt-in, like #416: an unrequested midnight notification is the kind of
    thing that gets the whole app muted."""
    db, cfg, bus = env
    _task(db, "overdue", due_date="2026-01-01")

    cfg.notifications.nightly_nudge = False
    assert should_notify(db, cfg, day="2026-10-10") is False

    cfg.notifications.nightly_nudge = True
    assert should_notify(db, cfg, day="2026-10-10") is True


def test_a_quiet_inbox_does_not_consume_the_days_nudge(env):
    """Nothing was sent, so the day is still available for the real send."""
    db, cfg, bus = env
    cfg.notifications.nightly_nudge = True

    assert should_notify(db, cfg, day="2026-10-10") is False
    _task(db, "overdue", due_date="2026-01-01")
    assert should_notify(db, cfg, day="2026-10-10") is True

def test_a_task_already_shown_as_a_thread_is_not_listed_twice(env):
    """#169 already surfaces stale tasks; a nudge repeating them is noise."""
    db, cfg, bus = env
    _thread(db, "2026-09-01", "ring the clinic about results")
    _task(db, "ring the clinic about results", due_date="2020-01-01")

    res = nightly_nudge(db, cfg, day="2026-10-10")

    assert res["count"] == 1
    assert res["items"][0]["kind"] == "thread"


# ---- what actually gets sent ----------------------------------------------


def test_the_notification_names_the_oldest_loop(env):
    db, cfg, bus = env
    cfg.notifications.nightly_nudge = True
    _thread(db, "2026-09-01", "the very old thing")
    _thread(db, "2026-10-09", "the recent thing")

    summary, body = notify_text(nightly_nudge(db, cfg, day="2026-10-10"))

    assert "2 open loops" in summary
    assert "the very old thing" in body


def test_one_loop_is_not_a_plural(env):
    db, cfg, bus = env
    _thread(db, "2026-09-01", "just the one")

    summary, _ = notify_text(nightly_nudge(db, cfg, day="2026-10-10"))

    assert "1 open loop" in summary


def test_the_night_job_sends_once_and_publishes(env, monkeypatch):
    db, cfg, bus = env
    cfg.notifications.nightly_nudge = True
    _task(db, "overdue", due_date="2020-01-01")

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(notify, "send", lambda s, b="": sent.append((s, b)) or True)
    events: list[dict] = []
    bus.subscribe("nudge.ready", lambda data: events.append(data))

    assert nightly_notify(db, cfg, bus, day="2026-10-10") is True
    assert nightly_notify(db, cfg, bus, day="2026-10-10") is False

    assert len(sent) == 1
    assert len(events) == 1
    assert events[0]["count"] == 1


def test_the_night_job_is_silent_when_off(env, monkeypatch):
    db, cfg, bus = env
    _task(db, "overdue", due_date="2020-01-01")

    sent: list[str] = []
    monkeypatch.setattr(notify, "send", lambda s, b="": sent.append(s) or True)

    assert nightly_notify(db, cfg, bus, day="2026-10-10") is False
    assert sent == []


def test_a_failing_notification_does_not_stop_the_day_job(env, monkeypatch):
    """A dead notification server must not take the daily report down with it."""
    db, cfg, bus = env
    cfg.notifications.nightly_nudge = True
    _task(db, "overdue", due_date="2020-01-01")

    def boom(summary: str, body: str = "") -> bool:
        raise RuntimeError("no notification daemon")

    monkeypatch.setattr(notify, "send", boom)

    # Still answers, and still records the night, rather than propagating.
    assert nightly_notify(db, cfg, bus, day="2026-10-10") is True


def test_a_failed_desktop_send_still_reaches_the_app(env, monkeypatch):
    """The in-app nudge is the one the user can act on, so it must survive."""
    db, cfg, bus = env
    cfg.notifications.nightly_nudge = True
    _task(db, "overdue", due_date="2020-01-01")

    def boom(summary: str, body: str = "") -> bool:
        raise RuntimeError("no notification daemon")

    monkeypatch.setattr(notify, "send", boom)
    events: list[dict] = []
    bus.subscribe("nudge.ready", lambda data: events.append(data))

    nightly_notify(db, cfg, bus, day="2026-10-10")

    assert len(events) == 1
    assert events[0]["count"] == 1


# ---- the HTTP surface ------------------------------------------------------


def test_the_endpoint_returns_the_same_list_the_notification_uses(client):
    db = client.app.state.st.db
    _task(db, "overdue task", due_date="2020-01-01")

    r = client.get("/api/activity/nudge")

    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "task"


def test_the_endpoint_is_quiet_on_an_empty_inbox(client):
    r = client.get("/api/activity/nudge")

    assert r.status_code == 200
    assert r.json()["items"] == []
