"""#106 scheduled assistant jobs.

The tests are mostly about not doing something surprising: refusing a schedule
it cannot read rather than guessing, not running a job twice, and never
running a missed one from three days ago.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services import schedules as S


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "sched.db"))
    database.migrate()
    return database


# ---- reading a schedule --------------------------------------------------


@pytest.mark.parametrize(
    "text,kind,hour,minute",
    [
        ("every friday at 5pm", "weekly", 17, 0),
        ("fridays at 5pm", "weekly", 17, 0),
        ("daily at 9am", "daily", 9, 0),
        ("every day at 8", "daily", 8, 0),
        ("weekdays at 7", "weekday", 7, 0),
        ("mondays at 8:30", "weekly", 8, 30),
        ("monthly on the 1st at 9", "monthly", 9, 0),
        ("every tuesday at 17:45", "weekly", 17, 45),
    ],
)
def test_the_phrases_people_say_are_read(text: str, kind: str, hour: int, minute: int) -> None:
    parsed = S.parse_schedule(text)
    assert (parsed["kind"], parsed["hour"], parsed["minute"]) == (kind, hour, minute)


def test_midnight_is_midnight_not_twelve() -> None:
    assert S.parse_schedule("daily at 12am")["hour"] == 0


def test_noon_is_twelve() -> None:
    assert S.parse_schedule("daily at 12pm")["hour"] == 12


def test_a_schedule_without_a_time_is_refused() -> None:
    """Running at midnight because the user forgot a time is a guess."""
    with pytest.raises(ValueError, match="time"):
        S.parse_schedule("every friday")


def test_nonsense_is_refused_with_a_reason() -> None:
    with pytest.raises(ValueError):
        S.parse_schedule("sometime soonish")


def test_an_impossible_hour_is_refused() -> None:
    with pytest.raises(ValueError):
        S.parse_schedule("daily at 99am")


def test_an_empty_schedule_is_refused() -> None:
    with pytest.raises(ValueError):
        S.parse_schedule("  ")


def test_the_error_says_what_is_accepted() -> None:
    """A refusal the user cannot act on is a dead end."""
    with pytest.raises(ValueError) as exc:
        S.parse_schedule("when i feel like it")
    assert "every friday" in str(exc.value)


# ---- storing and listing -------------------------------------------------


def test_a_job_round_trips(db: Database) -> None:
    created = S.create_job(db, "draft my week summary", "every friday at 5pm")
    stored = S.list_jobs(db)
    assert len(stored) == 1
    assert stored[0].prompt == "draft my week summary"
    assert stored[0].job_id == created.job_id


def test_a_job_needs_something_to_do(db: Database) -> None:
    with pytest.raises(ValueError):
        S.create_job(db, "   ", "daily at 9am")


def test_a_bad_schedule_never_becomes_a_row(db: Database) -> None:
    """Refused at creation, not stored and silently skipped at 5pm."""
    with pytest.raises(ValueError):
        S.create_job(db, "do a thing", "whenever")
    assert S.list_jobs(db) == []


def test_a_job_can_be_deleted(db: Database) -> None:
    created = S.create_job(db, "draft", "daily at 9am")
    S.delete_job(db, created.job_id)
    assert S.list_jobs(db) == []


def test_a_job_can_be_paused(db: Database) -> None:
    created = S.create_job(db, "draft", "daily at 9am")
    S.set_enabled(db, created.job_id, False)
    assert S.list_jobs(db)[0].enabled is False


def test_the_next_run_is_visible(db: Database) -> None:
    created = S.create_job(db, "draft", "every friday at 5pm")
    when = S.next_run_after(created, datetime(2026, 10, 11, 12, 0))
    assert when is not None and when.startswith("2026-10-16T17:00")


# ---- firing --------------------------------------------------------------


def test_a_job_fires_at_its_time(db: Database) -> None:
    S.create_job(db, "draft", "every friday at 5pm")
    # 2026-10-16 is a Friday.
    due = S.due_jobs(db, datetime(2026, 10, 16, 17, 0))
    assert len(due) == 1


def test_a_job_does_not_fire_at_the_wrong_time(db: Database) -> None:
    S.create_job(db, "draft", "every friday at 5pm")
    assert S.due_jobs(db, datetime(2026, 10, 16, 16, 0)) == []


def test_a_weekly_job_does_not_fire_on_another_day(db: Database) -> None:
    S.create_job(db, "draft", "every friday at 5pm")
    # 2026-10-15 is a Thursday.
    assert S.due_jobs(db, datetime(2026, 10, 15, 17, 0)) == []


def test_a_weekday_job_skips_the_weekend(db: Database) -> None:
    S.create_job(db, "standup notes", "weekdays at 7")
    assert S.due_jobs(db, datetime(2026, 10, 17, 7, 0)) == []  # Saturday
    assert len(S.due_jobs(db, datetime(2026, 10, 16, 7, 0))) == 1  # Friday


def test_a_job_does_not_fire_twice(db: Database) -> None:
    """The laptop ticking twice in the same minute must not send two drafts."""
    S.create_job(db, "draft", "daily at 9am")
    moment = datetime(2026, 10, 12, 9, 0)

    assert len(S.due_jobs(db, moment)) == 1
    S.mark_run(db, S.list_jobs(db)[0].job_id, moment)
    assert S.due_jobs(db, moment) == []


def test_a_paused_job_never_fires(db: Database) -> None:
    created = S.create_job(db, "draft", "daily at 9am")
    S.set_enabled(db, created.job_id, False)
    assert S.due_jobs(db, datetime(2026, 10, 12, 9, 0)) == []


def test_a_job_fires_again_the_next_day(db: Database) -> None:
    S.create_job(db, "draft", "daily at 9am")
    first = datetime(2026, 10, 12, 9, 0)
    S.mark_run(db, S.list_jobs(db)[0].job_id, first)
    assert len(S.due_jobs(db, datetime(2026, 10, 13, 9, 0))) == 1


def test_due_jobs_is_about_this_instant_only(db: Database) -> None:
    """A sleeping laptop never ticks, so nothing fires for the hours it missed.

    There is no catch-up scan: the runner asks about *now* once a minute, so a
    missed slot is simply never offered. Firing three days of digests on wake
    would be the alternative, and it is not one.
    """
    S.create_job(db, "daily digest", "daily at 9am")
    assert len(S.due_jobs(db, datetime(2026, 10, 12, 9, 0))) == 1
    # The same minute on another day is a different job occurrence.
    assert len(S.due_jobs(db, datetime(2026, 10, 13, 9, 0))) == 1


def test_an_unparseable_row_is_skipped_not_fatal(db: Database) -> None:
    """One bad row must not stop every other job from running."""
    S.create_job(db, "draft", "daily at 9am")
    db.execute("INSERT INTO schedules (id, job, body, last_run, enabled, at) "
               "VALUES ('bad', 'x', 'not json at all', NULL, 1, '2026-01-01')")
    db.commit()
    assert len(S.list_jobs(db)) == 1

# ---- running -------------------------------------------------------------


@pytest.mark.anyio
async def test_a_job_runs_through_the_assistant(db: Database, monkeypatch) -> None:
    """The whole safety envelope depends on jobs not having their own path."""
    from fleeting.config import Config

    seen: list[str] = []

    async def fake_ask(messages, db_, cfg, bus=None, **kw):
        seen.append(messages[0]["content"])
        return {"message": "here is your week", "sources": [], "context_used": {}}

    monkeypatch.setattr("fleeting.services.assistant.ask_assistant", fake_ask)
    S.create_job(db, "draft my week summary", "daily at 9am")

    out = await S.run_due_jobs(db, Config(), None, now=datetime(2026, 10, 12, 9, 0))

    assert seen == ["draft my week summary"]
    assert out[0]["ok"] is True


@pytest.mark.anyio
async def test_a_failing_job_does_not_stop_the_others(db: Database, monkeypatch) -> None:
    from fleeting.config import Config

    async def fake_ask(messages, db_, cfg, bus=None, **kw):
        raise RuntimeError("model unreachable")

    monkeypatch.setattr("fleeting.services.assistant.ask_assistant", fake_ask)
    S.create_job(db, "one", "daily at 9am")
    S.create_job(db, "two", "daily at 9am")

    out = await S.run_due_jobs(db, Config(), None, now=datetime(2026, 10, 12, 9, 0))

    assert len(out) == 2
    assert all(r["ok"] is False for r in out)


@pytest.mark.anyio
async def test_a_run_is_recorded_even_when_it_fails(db: Database, monkeypatch) -> None:
    """Otherwise one broken model retries every minute until the heat death."""
    from fleeting.config import Config

    async def fake_ask(messages, db_, cfg, bus=None, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr("fleeting.services.assistant.ask_assistant", fake_ask)
    S.create_job(db, "one", "daily at 9am")
    moment = datetime(2026, 10, 12, 9, 0)

    await S.run_due_jobs(db, Config(), None, now=moment)
    assert S.due_jobs(db, moment) == []
