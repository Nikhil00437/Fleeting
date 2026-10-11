"""#415 a local birthday and anniversary reminder list.

A date is the one thing a note mentions that the note cannot hold: a birthday
written down in March is still true in November. So these are extracted once
into their own table where the user can read them, correct one, or delete it —
and never re-derived, because a reminder that changes itself is not a reminder.

Extraction is deterministic and narrow. A model asked to find birthdays
invents them — "we should catch up soon" becomes somebody's birthday often
enough to be embarrassing — and a wrong reminder is worse than a missed one.
Everything the extractor believes is shown, with the sentence it came from, so
a mistake is obvious rather than plausible.

No year is stored. A birthday recurs and the year is either wrong or absent;
keeping it would only produce a reminder for a date that has already passed.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..db import Database

KINDS = ("birthday", "anniversary")

_MONTHS = {
    name.lower(): num
    for num, name in enumerate(calendar.month_name)
    if name
} | {
    name.lower(): num
    for num, name in enumerate(calendar.month_abbr)
    if name
}

# The name is required: an unattributed "her birthday is March 3" has no owner,
# and inventing one is worse than skipping. That is also why there is no global
# re.IGNORECASE — the capital is what separates "Priya's birthday" from "her
# birthday", and scoping the flag would give it back.
_PATTERN = re.compile(
    r"(?P<name>[A-Z][a-z]+(?:'s)?|our|my)\s+(?:'s\s+)?(?P<kind>(?i:birthday|anniversary))"
    r"[^\n]{0,24}?(?P<date>\d{1,2}\s+[A-Za-z]{3,9}|[A-Za-z]{3,9}\s+\d{1,2}|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+of\s+[A-Za-z]{3,9})"
)
# Only the suffix, and only after a digit: matching "st" anywhere would
# turn "august" into "augu".
_TRAILING = re.compile(r"(?<=\d)(?:st|nd|rd|th)\b")


def parse_month_day(text: str) -> tuple[int, int] | None:
    """(month, day) from a phrase like "March 3" or "the 14th of February".

    Returns None rather than a best guess. Feb 30 is not March 2, and a
    reminder that fires on the wrong day is worse than no reminder.
    """
    raw = (text or "").strip().lower().replace(",", " ")
    # "the" goes first: stripping the ordinal out of "the 14th of February"
    # leaves a hole where the day was, and the number is the part that matters.
    raw = re.sub(r"^the\s+", "", raw)
    raw = _TRAILING.sub("", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    m = re.search(r"\bof\s+([a-z]+)\b", raw)
    if m and re.match(r"\s*(\d{1,2})\b", raw):
        month, day = _month(m.group(1)), int(re.match(r"\s*(\d{1,2})", raw).group(1))
    else:
        m = re.match(r"\s*([a-z]+)\s+(\d{1,2})$", raw)
        if m:
            month, day = _month(m.group(1)), int(m.group(2))
        else:
            m = re.match(r"\s*(\d{1,2})\s+([a-z]+)$", raw)
            if not m:
                return None
            day, month = int(m.group(1)), _month(m.group(2))

    if not month or not (1 <= day <= calendar.monthrange(2000, month)[1]):
        return None
    return (month, day)


def _month(name: str) -> int | None:
    return _MONTHS.get((name or "").strip().lower())


def next_occurrence(month_day: tuple[int, int], *, today: str) -> str:
    """The next YYYY-MM-DD this month/day falls on, on or after `today`.

    Feb 29 lands on Feb 28 in a common year rather than being skipped: a
    reminder that disappears for four years out of five is a bug, not a
    precision.
    """
    month, day = month_day
    year = int(today[:4])
    for candidate_year in (year, year + 1):
        d = date(candidate_year, month, min(day, calendar.monthrange(candidate_year, month)[1]))
        if d.isoformat() >= today:
            return d.isoformat()
    return today


def extract_reminders(text: str) -> list[dict[str, Any]]:
    """Every dated birthday or anniversary in `text`, with its source sentence.

    Narrow by construction: a month and a day must both be present, and a named
    person is preferred. Prose that merely discusses birthdays yields nothing.
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    for match in _PATTERN.finditer(text or ""):
        parsed = parse_month_day(match.group("date"))
        if not parsed:
            continue
        name = match.group("name").rstrip("'s")
        entry = {
            "name": name,
            "kind": match.group("kind").lower(),
            "month": parsed[0],
            "day": parsed[1],
            "source_text": match.group(0).strip(),
            "source_key": f"{name.lower()}|{match.group('kind').lower()}|{parsed[0]}-{parsed[1]}",
        }
        if entry["source_key"] not in seen:
            seen.add(entry["source_key"])
            found.append(entry)
    return found


def extract_and_store(
    db: "Database", text: str, *, note_id: str | None = None
) -> int:
    """Extract and store. Returns how many were newly added.

    Silent on a deleted reminder: the user removing one is a decision, and a
    reprocess must not undo it.
    """
    added = 0
    for entry in extract_reminders(text):
        row = db.add_reminder(
            entry["name"],
            entry["kind"],
            entry["month"],
            entry["day"],
            note_id=note_id,
            source_key=entry["source_key"],
        )
        if row:
            added += 1
    return added


def list_reminders(db: "Database") -> list[dict[str, Any]]:
    return db.list_reminders()


def update_reminder(db: "Database", reminder_id: str, changes: dict) -> dict | None:
    """Correct a reminder, refusing a date that does not exist.

    Extraction validates; correction did not, so the edit path was the one way
    to store Feb 30 — a reminder that then never fires on the right day. The
    check lives here rather than in the route so every caller gets it.
    """
    changes = dict(changes or {})
    if "month" in changes or "day" in changes:
        row = db.get_reminder(reminder_id)
        month = int(changes.get("month", (row or {}).get("month") or 0))
        day = int(changes.get("day", (row or {}).get("day") or 0))
        if not (1 <= month <= 12 and 1 <= day <= calendar.monthrange(2000, month)[1]):
            raise ValueError(f"{month}-{day} is not a date")
    return db.update_reminder(reminder_id, changes)


def delete_reminder(db: "Database", reminder_id: str) -> bool:
    return db.delete_reminder(reminder_id)


def upcoming(
    db: "Database", *, today: str | None = None, days: int = 45
) -> list[dict[str, Any]]:
    """Reminders falling due within `days`, soonest first, with days_until."""
    if not today:
        today = date.today().isoformat()
    horizon = (
        date.fromisoformat(today) + timedelta(days=max(1, int(days)))
    ).isoformat()
    out: list[dict[str, Any]] = []
    for row in db.list_reminders():
        when = next_occurrence((int(row["month"]), int(row["day"])), today=today)
        if when > horizon:
            continue
        out.append(
            {
                "id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "date": when,
                "days_until": (date.fromisoformat(when) - date.fromisoformat(today)).days,
                "note_id": row["note_id"],
            }
        )
    out.sort(key=lambda r: (r["days_until"], r["name"]))
    return out