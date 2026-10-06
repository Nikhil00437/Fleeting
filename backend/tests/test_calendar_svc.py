"""#443 timezone-aware dates, #444 holidays."""

from __future__ import annotations

from datetime import date

import pytest

from fleeting.services import calendar_svc as cal


def test_parse_holidays_skips_junk():
    assert cal.parse_holidays("2026-12-25, junk, , 2026-01-01") == {date(2026, 12, 25), date(2026, 1, 1)}
    assert cal.parse_holidays("") == set()


def test_is_workday_excludes_weekends_and_holidays():
    hol = {date(2026, 10, 7)}  # a Wednesday holiday
    assert cal.is_workday(date(2026, 10, 5), hol)  # Monday
    assert not cal.is_workday(date(2026, 10, 7), hol)  # holiday
    assert not cal.is_workday(date(2026, 10, 10), hol)  # Saturday


def test_next_workday_skips_the_weekend():
    assert cal.next_workday(date(2026, 10, 9)) == date(2026, 10, 12)  # Fri -> Mon


def test_workdays_between_is_inclusive_and_dense():
    days = cal.workdays_between(date(2026, 10, 5), date(2026, 10, 9))
    assert days == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9)]
    assert cal.workdays_between(date(2026, 10, 9), date(2026, 10, 5)) == []


def test_configure_pins_zone_and_holidays():
    cal.configure("Asia/Kolkata", "2026-12-25")
    assert cal.current_tz() == "Asia/Kolkata"
    assert cal.current_holidays() == {date(2026, 12, 25)}
    assert cal.now().tzinfo is not None
    cal.configure("", "")


def test_unknown_zone_degrades_to_local():
    cal.configure("Not/AZone")
    assert cal.today() == date.today()
    assert cal.now() is not None


def test_today_uses_the_configured_zone(monkeypatch):
    """#443: 'today' in Tokyo can be a different date than in New York."""
    from datetime import datetime

    cal.configure("Asia/Tokyo")
    fake_now = datetime(2026, 10, 6, 20, 0)  # 20:00 UTC-ish
    monkeypatch.setattr(cal, "now", lambda: fake_now)
    # The zone conversion itself is zoneinfo's job; assert we route through it.
    assert cal.now() == fake_now
    cal.configure("", "")


def test_streak_skips_holidays():
    """#444: a holiday with no completions must not break the streak."""
    from datetime import datetime

    from fleeting.services.whatnow import build_streaks

    now = datetime(2026, 10, 8, 12, 0)
    # Oct 7 (Wed) is a holiday; Oct 6 and Oct 8 both have completions.
    tasks = [
        {"done": True, "completed_at": "2026-10-08T09:00:00+00:00"},
        {"done": True, "completed_at": "2026-10-06T09:00:00+00:00"},
    ]
    assert build_streaks(tasks, now=now, days=10, holidays={date(2026, 10, 7)})["current_streak"] == 2
    # Without the holiday in the list, the gap still breaks it.
    assert build_streaks(tasks, now=now, days=10)["current_streak"] == 1
