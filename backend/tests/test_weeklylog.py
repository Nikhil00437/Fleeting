"""Weekly digest: aggregation, storage, scheduling.

The daily log covers 24 hours. A week of that is seven disconnected reports —
the thing a weekly summary has to add is the *shape* of the week: which days were
heavy, what carried over, what never got finished.

Reuses the daily machinery rather than reimplementing it: the per-day window
sessions, the stored daily summaries, the week's commits and captures. Falls
back to a deterministic digest when the LLM is unreachable, like the daily one.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from fleeting.db import Database


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "w.db")
    d.migrate()
    return d


def _sessions(db: Database, day: str, app: str, seconds: int, title: str = "work") -> None:
    db.upsert_activity(
        {
            "app_class": app,
            "title": title,
            "first_seen": f"{day}T10:00:00+00:00",
            "last_seen": f"{day}T11:00:00+00:00",
            "seconds": seconds,
            "day": day,
        }
    )


def _daily_log(db: Database, day: str, md: str) -> None:
    db.upsert_daily_log(day, md, "test-model")


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------


def test_weekly_log_round_trips(db: Database) -> None:
    assert db.get_weekly_log("2026-10-05") is None
    db.upsert_weekly_log("2026-10-05", "# Weekly\n\ntext", "test-model")
    row = db.get_weekly_log("2026-10-05")
    assert row is not None
    assert row["summary_md"].startswith("# Weekly")
    assert row["week_start"] == "2026-10-05"


def test_upsert_weekly_log_replaces_rather_than_duplicates(db: Database) -> None:
    db.upsert_weekly_log("2026-10-05", "first", "m")
    db.upsert_weekly_log("2026-10-05", "second", "m")
    assert db.execute("SELECT COUNT(*) AS c FROM weekly_logs").fetchone()["c"] == 1
    assert db.get_weekly_log("2026-10-05")["summary_md"] == "second"


def test_weekly_logs_are_separate_from_daily_logs(db: Database) -> None:
    """A week must never collide with a day key in the daily table."""
    db.upsert_daily_log("2026-10-05", "daily", "m")
    db.upsert_weekly_log("2026-10-05", "weekly", "m")
    assert db.get_daily_log("2026-10-05")["summary_md"] == "daily"
    assert db.get_weekly_log("2026-10-05")["summary_md"] == "weekly"


# ---------------------------------------------------------------------------
# week arithmetic
# ---------------------------------------------------------------------------


def test_week_start_is_monday() -> None:
    from fleeting.services.weeklylog import week_start_for

    # 2026-10-08 is a Thursday; its week starts Monday the 5th.
    assert week_start_for(date(2026, 10, 8)) == "2026-10-05"
    assert week_start_for(date(2026, 10, 5)) == "2026-10-05"  # Monday itself
    assert week_start_for(date(2026, 10, 11)) == "2026-10-05"  # Sunday
    assert week_start_for(date(2026, 10, 12)) == "2026-10-12"  # next Monday


def test_week_days_are_seven_consecutive_dates() -> None:
    from fleeting.services.weeklylog import week_days

    days = week_days("2026-10-05")
    assert len(days) == 7
    assert days[0] == "2026-10-05"
    assert days[-1] == "2026-10-11"


def test_week_days_crosses_a_month_boundary() -> None:
    from fleeting.services.weeklylog import week_days

    days = week_days("2026-09-28")
    assert days[0] == "2026-09-28"
    assert days[-1] == "2026-10-04"


def test_week_days_crosses_a_year_boundary() -> None:
    from fleeting.services.weeklylog import week_days

    days = week_days("2025-12-29")
    assert days[0] == "2025-12-29"
    assert days[-1] == "2026-01-04"


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def test_week_aggregation_sums_sessions_per_day(db: Database) -> None:
    from fleeting.services.weeklylog import aggregate_week

    _sessions(db, "2026-10-05", "code", 3600)
    _sessions(db, "2026-10-06", "code", 1800)
    _sessions(db, "2026-10-07", "zen", 600)

    agg = aggregate_week(db, "2026-10-05")
    by_day = {d["day"]: d["seconds"] for d in agg["days"]}
    assert by_day["2026-10-05"] == 3600
    assert by_day["2026-10-06"] == 1800
    assert by_day["2026-10-07"] == 600
    assert agg["total_seconds"] == 6000


def test_week_aggregation_includes_every_day_even_when_idle(db: Database) -> None:
    """A gap in the data must read as idle, not as a missing day."""
    from fleeting.services.weeklylog import aggregate_week

    _sessions(db, "2026-10-05", "code", 3600)
    agg = aggregate_week(db, "2026-10-05")
    assert len(agg["days"]) == 7
    idle = [d for d in agg["days"] if d["seconds"] == 0]
    assert len(idle) == 6


def test_week_aggregation_totals_by_app(db: Database) -> None:
    from fleeting.services.weeklylog import aggregate_week

    _sessions(db, "2026-10-05", "code", 3600)
    _sessions(db, "2026-10-06", "code", 1800)
    _sessions(db, "2026-10-06", "zen", 900)

    agg = aggregate_week(db, "2026-10-05")
    apps = {a["app_class"]: a["seconds"] for a in agg["apps"]}
    assert apps == {"code": 5400, "zen": 900}
    # heaviest first
    assert agg["apps"][0]["app_class"] == "code"


def test_week_aggregation_finds_the_busiest_day(db: Database) -> None:
    from fleeting.services.weeklylog import aggregate_week

    _sessions(db, "2026-10-05", "code", 600)
    _sessions(db, "2026-10-09", "code", 9000)
    agg = aggregate_week(db, "2026-10-05")
    assert agg["busiest_day"] == "2026-10-09"


def test_week_aggregation_collects_daily_summaries(db: Database) -> None:
    from fleeting.services.weeklylog import aggregate_week

    _daily_log(db, "2026-10-05", "# Daily Digest — 2026-10-05\n\nShipped the API.")
    _daily_log(db, "2026-10-06", "# Daily Digest — 2026-10-06\n\nDebugged ingress.")
    _daily_log(db, "2026-09-01", "outside the week")  # must be excluded

    agg = aggregate_week(db, "2026-10-05")
    assert len(agg["daily_logs"]) == 2
    assert all("outside" not in d["summary_md"] for d in agg["daily_logs"])


def test_week_aggregation_counts_open_tasks(db: Database) -> None:
    """Unfinished work is the thing a week-over-week view is actually for."""
    from fleeting.services.weeklylog import aggregate_week

    note = db.insert_note({"raw_text": "week note", "type": "text"})
    nid = note["id"] if isinstance(note, dict) else note
    db.insert_task({"note_id": nid, "text": "finish the migration", "done": False})
    db.insert_task({"note_id": nid, "text": "already done", "done": True})

    agg = aggregate_week(db, "2026-10-05")
    assert agg["open_tasks"] == 1
    assert agg["total_tasks"] == 2


def test_aggregate_week_on_an_empty_db_is_all_zeroes(db: Database) -> None:
    from fleeting.services.weeklylog import aggregate_week

    agg = aggregate_week(db, "2026-10-05")
    assert agg["total_seconds"] == 0
    assert agg["days"] and all(d["seconds"] == 0 for d in agg["days"])
    assert agg["daily_logs"] == []
    assert agg["open_tasks"] == 0
    assert agg["busiest_day"] is None


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def test_fallback_weekly_digest_is_useful_offline(db: Database) -> None:
    """No LLM must still produce something worth reading."""
    from fleeting.services.weeklylog import fallback_weekly_digest, aggregate_week

    _sessions(db, "2026-10-05", "code", 7200)
    _sessions(db, "2026-10-09", "code", 3600)
    _daily_log(db, "2026-10-05", "# Daily Digest\n\nDid work.")

    md = fallback_weekly_digest(aggregate_week(db, "2026-10-05"), "2026-10-05")
    assert "Weekly" in md
    assert "2026-10-05" in md
    assert "2026-10-11" in md  # the range end
    assert "3h" in md or "10800" in md  # total focus rendered humanly
    assert "code" in md.lower()


def test_fallback_weekly_digest_handles_an_empty_week(db: Database) -> None:
    from fleeting.services.weeklylog import aggregate_week, fallback_weekly_digest

    md = fallback_weekly_digest(aggregate_week(db, "2026-10-05"), "2026-10-05")
    assert "No tracked activity" in md


def test_fallback_weekly_digest_shows_idle_days(db: Database) -> None:
    """A week is seven bars wide; an idle day must appear as a gap, not vanish."""
    from fleeting.services.weeklylog import aggregate_week, fallback_weekly_digest

    _sessions(db, "2026-10-05", "code", 3600)
    md = fallback_weekly_digest(aggregate_week(db, "2026-10-05"), "2026-10-05")
    for i in range(7):
        assert f"`2026-10-{5 + i:02d}`" in md, f"day {i} missing from the week table"


def test_fallback_weekly_digest_never_emits_bare_seconds(db: Database) -> None:
    """Durations are humanised; raw second counts are not user-facing."""
    from fleeting.services.weeklylog import aggregate_week, fallback_weekly_digest

    for i in range(7):
        _sessions(db, f"2026-10-{5 + i:02d}", "zen", 90)
    md = fallback_weekly_digest(aggregate_week(db, "2026-10-05"), "2026-10-05")
    assert " 90" not in md and "90s" not in md
    assert "1m" in md or "1m 30s" in md


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_weekly_log_stores_and_reports(db: Database, monkeypatch) -> None:
    from fleeting.config import Config
    from fleeting.events import EventBus
    from fleeting.services import weeklylog

    _sessions(db, "2026-10-05", "code", 7200)
    cfg = Config()
    cfg.llm.provider = "none"
    cfg.activity.watch_dirs = ""  # keep real ~/Projects out of these tests

    async def fake_llm(transcript: str, week: str, cfg):
        return "# Weekly Digest\n\nLLM wrote this.", "test-model"

    monkeypatch.setattr(weeklylog, "generate_with_llm", fake_llm)
    row = await weeklylog.generate_weekly_log(db, cfg, "2026-10-05", bus=EventBus())

    assert row["week_start"] == "2026-10-05"
    assert "LLM wrote this" in row["summary_md"]
    assert db.get_weekly_log("2026-10-05") is not None


@pytest.mark.anyio
async def test_generate_weekly_log_falls_back_when_the_llm_fails(
    db: Database, monkeypatch
) -> None:
    from fleeting.config import Config
    from fleeting.events import EventBus
    from fleeting.services import weeklylog

    _sessions(db, "2026-10-05", "code", 7200)
    cfg = Config()
    cfg.llm.provider = "none"
    cfg.activity.watch_dirs = ""  # keep real ~/Projects out of these tests

    async def boom(transcript: str, week: str, cfg):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(weeklylog, "generate_with_llm", boom)
    row = await weeklylog.generate_weekly_log(db, cfg, "2026-10-05", bus=EventBus())

    assert "Weekly" in row["summary_md"]
    assert row["model"] == "fallback"


@pytest.mark.anyio
async def test_generate_weekly_log_refuses_an_empty_week(db: Database) -> None:
    """Do not store a contentless report that looks like a real one."""
    from fleeting.config import Config
    from fleeting.events import EventBus
    from fleeting.services import weeklylog

    cfg = Config()
    cfg.llm.provider = "none"
    # Isolate from the real ~/Projects etc., which would supply git commits.
    cfg.activity.watch_dirs = ""
    with pytest.raises(ValueError):
        await weeklylog.generate_weekly_log(db, cfg, "2026-10-05", bus=EventBus())
    assert db.get_weekly_log("2026-10-05") is None


@pytest.mark.anyio
async def test_regenerating_replaces_the_stored_report(db: Database, monkeypatch) -> None:
    from fleeting.config import Config
    from fleeting.events import EventBus
    from fleeting.services import weeklylog

    _sessions(db, "2026-10-05", "code", 7200)
    cfg = Config()
    cfg.llm.provider = "none"
    cfg.activity.watch_dirs = ""  # keep real ~/Projects out of these tests

    calls = {"n": 0}

    async def fake(transcript: str, week: str, cfg):
        calls["n"] += 1
        return f"# Weekly Digest\n\nattempt {calls['n']}", "m"

    monkeypatch.setattr(weeklylog, "generate_with_llm", fake)
    bus = EventBus()
    await weeklylog.generate_weekly_log(db, cfg, "2026-10-05", bus=bus)
    await weeklylog.generate_weekly_log(db, cfg, "2026-10-05", bus=bus)

    assert calls["n"] == 2
    assert db.execute("SELECT COUNT(*) AS c FROM weekly_logs").fetchone()["c"] == 1
    assert "attempt 2" in db.get_weekly_log("2026-10-05")["summary_md"]


@pytest.mark.anyio
async def test_generation_publishes_an_event(db: Database, monkeypatch) -> None:
    """The UI must learn a report landed without polling."""
    from fleeting.config import Config
    from fleeting.events import EventBus
    from fleeting.services import weeklylog

    _sessions(db, "2026-10-05", "code", 7200)
    cfg = Config()
    cfg.llm.provider = "none"
    cfg.activity.watch_dirs = ""  # keep real ~/Projects out of these tests

    async def fake(transcript: str, week: str, cfg):
        return "# Weekly Digest\n\ndone", "m"

    monkeypatch.setattr(weeklylog, "generate_with_llm", fake)
    bus = EventBus()
    q = bus.subscribe()
    await weeklylog.generate_weekly_log(db, cfg, "2026-10-05", bus=bus)

    payload = q.get_nowait()
    assert "weekly" in payload.lower()
    assert "2026-10-05" in payload


# ---------------------------------------------------------------------------
# commits
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_commits_are_included_when_watch_dirs_yield_them(
    db: Database, monkeypatch
) -> None:
    """A week with only commits (no tracked windows) is still a real week."""
    from fleeting.config import Config
    from fleeting.events import EventBus
    from fleeting.services import weeklylog

    cfg = Config()
    cfg.llm.provider = "none"
    cfg.activity.watch_dirs = str(db.path.rsplit("/", 1)[0])

    monkeypatch.setattr(
        weeklylog,
        "collect_git_subjects",
        lambda dirs, since, until: [{"repo": "fleeting", "subject": "fix: thing"}],
        raising=False,
    )
    import fleeting.services.weeklylog as mod

    monkeypatch.setattr(
        mod,
        "collect_git_subjects",
        lambda dirs, since, until: [{"repo": "fleeting", "subject": "fix: thing"}],
        raising=False,
    )

    seen: list[str] = []

    async def fake(transcript: str, week: str, cfg):
        seen.append(transcript)
        return "# Weekly Digest\n\ncommits only", "m"

    monkeypatch.setattr(mod, "generate_with_llm", fake)
    row = await mod.generate_weekly_log(db, cfg, "2026-10-05", bus=EventBus())

    assert "commits only" in row["summary_md"]
    assert seen and "fix: thing" in seen[0], "commits never reached the transcript"


@pytest.mark.anyio
async def test_commit_collection_failure_does_not_lose_the_report(
    db: Database, monkeypatch
) -> None:
    """Commits are a bonus; a git failure must not cost us the whole report."""
    import fleeting.services.weeklylog as mod
    from fleeting.config import Config
    from fleeting.events import EventBus

    _sessions(db, "2026-10-05", "code", 7200)
    cfg = Config()
    cfg.llm.provider = "none"
    cfg.activity.watch_dirs = "/tmp"

    def boom(dirs, since, until):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(mod, "collect_git_subjects", boom, raising=False)

    async def fake(transcript: str, week: str, cfg):
        return "# Weekly Digest\n\nwindows only", "m"

    monkeypatch.setattr(mod, "generate_with_llm", fake)
    row = await mod.generate_weekly_log(db, cfg, "2026-10-05", bus=EventBus())
    assert "windows only" in row["summary_md"]


def test_transcript_includes_every_day_bar() -> None:
    from fleeting.services.weeklylog import build_transcript

    agg = {
        "week_start": "2026-10-05",
        "week_end": "2026-10-11",
        "days": [
            {"day": f"2026-10-{5 + i:02d}", "seconds": 3600 if i == 0 else 0, "busy": i == 0}
            for i in range(7)
        ],
        "apps": [{"app_class": "code", "seconds": 3600}],
        "total_seconds": 3600,
        "commits": [],
        "daily_logs": [],
        "total_tasks": 2,
        "open_tasks": 1,
    }
    t = build_transcript(agg)
    for i in range(7):
        assert f"2026-10-{5 + i:02d}" in t
    assert "code" in t
    assert "1 open of 2 total" in t
