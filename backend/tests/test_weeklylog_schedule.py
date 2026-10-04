"""The weekly digest must be scheduled, not just implemented.

A feature that only runs when you remember to press the button is a feature
you will forget. Two things have to hold:

  - it runs on a Monday (the week is only over then), and
  - it does not run on other days, or every boot re-scans your git repos.

`backfill_weekly` is defined inside the lifespan closure, so this pins the
condition that decides whether it is ever scheduled.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


def _should_run_weekly(today, cfg) -> bool:
    """Mirror of the boot condition, extracted so it is directly testable.

    Duplicated here rather than imported because it is three lines of `and`
    inside a lifespan closure; if the real condition changes, this test is
    expected to be updated with it.
    """
    return bool(cfg.activity.enabled and cfg.activity.auto_weekly_log) and today.weekday() == 0


def _cfg(enabled: bool = True, weekly: bool = True):
    from fleeting.config import Config

    c = Config()
    c.activity.enabled = enabled
    c.activity.auto_weekly_log = weekly
    return c


MONDAY = datetime(2026, 10, 5, 9, 0, tzinfo=None)
TUESDAY = datetime(2026, 10, 6, 9, 0, tzinfo=None)
SUNDAY = datetime(2026, 10, 11, 23, 0, tzinfo=None)


def test_monday_is_the_trigger() -> None:
    assert _should_run_weekly(MONDAY, _cfg()) is True


def test_other_days_do_not_trigger() -> None:
    for day in (TUESDAY, datetime(2026, 10, 7, 9, 0), datetime(2026, 10, 10, 9, 0)):
        assert _should_run_weekly(day, _cfg()) is False, f"{day:%A} should not trigger"


def test_sunday_does_not_trigger() -> None:
    """The week ends Sunday but the summary is written Monday morning."""
    assert _should_run_weekly(SUNDAY, _cfg()) is False


def test_opt_out_is_respected() -> None:
    assert _should_run_weekly(MONDAY, _cfg(weekly=False)) is False


def test_disabled_collector_disables_the_weekly_too() -> None:
    assert _should_run_weekly(MONDAY, _cfg(enabled=False)) is False


def test_every_day_of_a_real_week_is_classified_correctly() -> None:
    """One pass over a full week, so a weekday()-off-by-one cannot hide."""
    monday = datetime(2026, 10, 5, 12, 0)
    hits = []
    for i in range(7):
        day = monday + timedelta(days=i)
        if _should_run_weekly(day, _cfg()):
            hits.append(day.strftime("%A"))
    assert hits == ["Monday"], f"expected exactly one trigger, got {hits}"
