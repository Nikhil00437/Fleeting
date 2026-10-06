"""Recurrence for tasks (#28).

The stored format is an RFC-5545-style RRULE subset, validated at write time
by db._norm_task_recurrence: FREQ=DAILY|WEEKLY|MONTHLY|YEARLY with optional
INTERVAL=n (≥2) and, for WEEKLY, BYDAY=MO,TU,….

Advancement rule: the next occurrence is scheduled from the task's own due
date when it is still current, but from *today* when the task was completed
overdue — completing a weekly chore that lapsed two weeks should schedule
next week, not two weeks ago.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

_WEEKDAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _month_add(base: date, months: int) -> date:
    total = base.month - 1 + months
    year, month = base.year + total // 12, total % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _parse(rule: str) -> tuple[str, int, list[int]]:
    freq, interval, byday = "DAILY", 1, []
    for part in rule.upper().split(";"):
        if part.startswith("FREQ="):
            freq = part[5:]
        elif part.startswith("INTERVAL="):
            interval = max(1, int(part[9:]))
        elif part.startswith("BYDAY="):
            byday = [
                _WEEKDAY_CODES[c] for c in part[6:].split(",") if c in _WEEKDAY_CODES
            ]
    return freq, interval, sorted(set(byday))


def next_due(rule: str, base: date) -> date:
    """First occurrence of `rule` strictly after `base`.

    For WEEKLY with BYDAY the interval is deliberately ignored: the next
    matching weekday after the base date is what "tue,thu" means to a person,
    and a 2-week interval over a hand-written BYDAY list is more surprise
    than schedule.
    """
    freq, interval, byday = _parse(rule)
    if freq == "DAILY":
        return base + timedelta(days=interval)
    if freq == "WEEKLY":
        if byday:
            for offset in range(1, 8):
                cand = base + timedelta(days=offset)
                if cand.weekday() in byday:
                    return cand
            return base + timedelta(days=7)  # unreachable with valid BYDAY
        return base + timedelta(weeks=interval)
    if freq == "MONTHLY":
        return _month_add(base, interval)
    # YEARLY, clamped like monthly (Feb 29 → Feb 28).
    return _month_add(base, 12 * interval)


def next_anchor(due_date: str | None, today: date) -> date:
    """Where to start counting the next occurrence from."""
    if due_date:
        try:
            base = date.fromisoformat(due_date)
            return max(base, today)
        except ValueError:
            pass
    return today
