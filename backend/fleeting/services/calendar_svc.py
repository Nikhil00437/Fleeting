"""Calendar arithmetic shared by due dates, streaks, planner and review.

#443 makes "today" mean a configured IANA zone rather than whatever the box
happens to be set to — a capture made at 23:30 UTC while planning a New York
day should land on the New York date, not the UTC one. `zoneinfo` is stdlib,
so this costs nothing but an IANA name.

#444 keeps non-working days out of two places that are easy to get wrong:
streaks (a public holiday with no completions must not read as a broken run)
and the weekly planner (a holiday is not a day with capacity to fill).

Pure functions plus one small module-level zone cache; nothing here touches
request state, so the whole module is testable with a frozen `today`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# Process-wide zone + holiday set, configured once at boot from config.toml.
# Small mutable module state on purpose: there is one config per app instance
# and every date consumer (db, tasks, reminders, planner) must agree on what
# "today" means without threading a Config through every signature.
_tz_name: str = ""
_holidays: set[date] = set()


def configure(tz_name: str = "", holidays: Iterable[date] | str = ()) -> None:
    global _tz_name, _holidays
    _tz_name = (tz_name or "").strip()
    _holidays = parse_holidays(holidays) if isinstance(holidays, str) else set(holidays)


def current_tz() -> str:
    return _tz_name


def current_holidays() -> set[date]:
    return set(_holidays)


def now() -> datetime:
    """Timezone-aware 'now' in the configured zone (#443)."""
    z = zone(_tz_name)
    return datetime.now(z) if z else datetime.now().astimezone()


@lru_cache(maxsize=8)
def zone(name: str) -> ZoneInfo | None:
    """Cached ZoneInfo; None for an unknown name so config typos degrade."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def today(tz_name: str = "") -> date:
    """Today's date in `tz_name` (IANA). Empty/unknown zone → box local."""
    z = zone(tz_name)
    if z is None:
        return date.today()
    return datetime.now(z).date()


def parse_holidays(spec: str) -> set[date]:
    """Parse a comma-separated YYYY-MM-DD list; junk entries are skipped."""
    out: set[date] = set()
    for part in (spec or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            y, m, d = (int(x) for x in token.split("-"))
            out.add(date(y, m, d))
        except (ValueError, TypeError):
            continue
    return out


def is_workday(day: date, holidays: Iterable[date] = ()) -> bool:
    """Weekends and holidays are non-working; everything else is."""
    if day.weekday() >= 5:
        return False
    return day not in set(holidays)


def next_workday(day: date, holidays: Iterable[date] = ()) -> date:
    """First working day strictly after `day`."""
    nxt = day + timedelta(days=1)
    hol = set(holidays)
    while not is_workday(nxt, hol):
        nxt = nxt + timedelta(days=1)
    return nxt


def workdays_between(start: date, end: date, holidays: Iterable[date] = ()) -> list[date]:
    """Inclusive list of working days; empty when end precedes start."""
    if end < start:
        return []
    hol = set(holidays)
    out = []
    cur = start
    while cur <= end:
        if is_workday(cur, hol):
            out.append(cur)
        cur = cur + timedelta(days=1)
    return out