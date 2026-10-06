"""Natural-language parsing for task quick-add (#278) and due dates (#27).

Pure regex parsing, no I/O and no LLM call: quick-add must stay instant and
keep working when the local model is down (same fallback philosophy as the
capture pipeline). `parse_quick_add("call dentist tomorrow @errands +health p1")`
returns the cleaned text plus the fields it could lift out of it.

Unparseable input is never an error: whatever cannot be recognised stays in
the text verbatim. Time-of-day phrases ("3pm") are deliberately *not*
stripped — the schema stores a due date, not a due time, and silently
dropping "3pm" would lose intent.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_WEEKDAY_RE = "|".join(_WEEKDAYS)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# Full names with the abbreviation as fallback, each fenced by \b — a plain
# prefix match would eat "Maybe" or "Jane 3" as dates.
_MONTH_RE = (
    r"january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|"
    r"august|aug|september|sept|sep|october|oct|november|nov|december|dec"
)

# A date phrase may be introduced by a preposition ("call the dentist by
# friday"); consuming it keeps the preposition from dangling in the text.
_PREP = re.compile(
    rf"\b(?:by|due(?:\s+on)?|on|before|until)\s+(?="
    rf"tomorrow|tonight|today|tmrw|tmr|next\s|this\s|in\s+\d|\d{{4}}-|"
    rf"(?:{_WEEKDAY_RE})\b|(?:{_MONTH_RE})\b)",
    re.IGNORECASE,
)


def _next_weekday(today: date, weekday: int, *, skip_week: bool) -> date:
    """Next occurrence of `weekday`. Bare "friday" is always ≥ tomorrow.
    "next friday" means the friday of next calendar week, anchored to next
    week's Monday so the answer does not depend on today's position in the
    week ("next monday" said on a Sunday is tomorrow)."""
    if not skip_week:
        ahead = (weekday - today.weekday()) % 7
        return today + timedelta(days=ahead or 7)
    next_monday = today + timedelta(days=7 - today.weekday())
    return next_monday + timedelta(days=weekday)


def _month_add(base: date, months: int) -> date:
    """Same day N months later, clamped to the month's length (Jan 31 → Feb 28)."""
    total = base.month - 1 + months
    year, month = base.year + total // 12, total % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@dataclass(frozen=True)
class _DateRule:
    """One date phrase. `resolve` returns None to leave the phrase untouched."""

    pattern: re.Pattern[str]
    resolve: Callable[[re.Match[str], date], date | None]


def _iso(m: re.Match[str], today: date) -> date | None:
    try:
        # An explicit year is a deliberate choice — kept even when in the past
        # (the task simply shows up overdue).
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
    except ValueError:
        return None


def _month_day(m: re.Match[str], today: date) -> date | None:
    month = _MONTHS[m.group("mon")[:3].lower()]
    try:
        d = date(today.year, month, int(m.group("d")))
    except ValueError:
        return None
    if d < today:
        d = date(today.year + 1, month, d.day)  # "oct 1" typed in November
    return d


def _in_n(m: re.Match[str], today: date) -> date | None:
    unit, n = m.group("u").lower(), int(m.group("n"))
    if n == 0:
        return None
    if unit.startswith("day"):
        return today + timedelta(days=n)
    if unit.startswith("week"):
        return today + timedelta(weeks=n)
    return _month_add(today, n)


def _today_tomorrow(m: re.Match[str], today: date) -> date | None:
    word = m.group("w").lower()
    return today if word in ("today", "tonight") else today + timedelta(days=1)


def _weekday(m: re.Match[str], today: date, *, skip_week: bool) -> date | None:
    return _next_weekday(today, _WEEKDAYS[m.group("wd").lower()], skip_week=skip_week)


def _next_month_or_week(m: re.Match[str], today: date) -> date | None:
    return today + timedelta(weeks=1) if m.group("u").lower() == "week" else _month_add(today, 1)


# Order is load-bearing: re.sub replaces left-to-right, and earlier rules
# claim their text first. "next friday" must be tried before "friday",
# "in 3 weeks" before a phrase after "in", month-day before bare weekday.
_DATE_RULES: tuple[_DateRule, ...] = (
    _DateRule(re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"), _iso),
    _DateRule(
        re.compile(rf"\b(?P<mon>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b", re.IGNORECASE),
        _month_day,
    ),
    _DateRule(
        re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH_RE})\.?\b", re.IGNORECASE),
        _month_day,
    ),
    _DateRule(re.compile(r"\bnext\s+(?P<u>week|month)\b", re.IGNORECASE), _next_month_or_week),
    _DateRule(re.compile(rf"\bnext\s+(?P<wd>{_WEEKDAY_RE})\b", re.IGNORECASE), lambda m, t: _weekday(m, t, skip_week=True)),
    _DateRule(re.compile(r"\bin\s+(?P<n>\d+)\s+(?P<u>days?|weeks?|months?)\b", re.IGNORECASE), _in_n),
    _DateRule(re.compile(r"\b(?P<w>today|tonight|tomorrow|tomorow|tmrw|tmr)\b", re.IGNORECASE), _today_tomorrow),
    _DateRule(re.compile(rf"\bthis\s+(?P<wd>{_WEEKDAY_RE})\b", re.IGNORECASE), lambda m, t: _weekday(m, t, skip_week=False)),
    _DateRule(re.compile(rf"\b(?P<wd>{_WEEKDAY_RE})\b", re.IGNORECASE), lambda m, t: _weekday(m, t, skip_week=False)),
)

# (?<!\w) keeps email addresses ("bob@example.com") from yielding a context.
_CONTEXT = re.compile(r"(?<!\w)@(?P<name>[a-z0-9][\w-]*)", re.IGNORECASE)
_PROJECT = re.compile(r"[+#](?P<name>[a-z0-9][\w-]*)", re.IGNORECASE)
# "p1", "!p1", "!"+"1"; the bare-letter form needs word fences so "rp1" or
# "p123" stay untouched.
_PRIORITY = re.compile(r"(?:(?<!\w)!(?:p)?|(?<!\w)p)([123])(?!\w)", re.IGNORECASE)


@dataclass
class QuickAddParse:
    """Result of parsing quick-add text. `text` is what should be shown."""

    text: str
    due_date: str | None = None
    context: str | None = None
    repo: str | None = None
    priority: str | None = None


def _strip_dates(text: str, today: date) -> tuple[str, str | None]:
    """Remove date phrases, returning cleaned text and the first hit as ISO."""
    due: str | None = None

    def replace(m: re.Match[str], rule: _DateRule) -> str:
        nonlocal due
        d = rule.resolve(m, today)
        if d is None:
            return m.group(0)
        if due is None:
            due = d.isoformat()
        return " "

    for rule in _DATE_RULES:
        text = rule.pattern.sub(lambda m, _r=rule: replace(m, _r), text)
    return text, due


def parse_quick_add(raw: str, today: date | None = None) -> QuickAddParse:
    """Split natural-language task text into clean text + planning fields.

    "@home" → context, "+project"/"#tag" → repo, "p1"/"!p1" → priority, and
    date phrases ("tomorrow", "by friday", "in 2 weeks", "oct 20") → due_date.
    The first recognised token of each kind wins; later ones are removed
    without overriding. Explicit dates keep their year even when past.
    """
    text = (raw or "").strip()
    if not text:
        return QuickAddParse(text="")

    today = today or date.today()
    text = _PREP.sub(" ", text)
    text, due_date = _strip_dates(text, today)

    context: str | None = None
    if m := _CONTEXT.search(text):
        context = m.group("name").lower()
    text = _CONTEXT.sub(" ", text)

    repo: str | None = None
    if m := _PROJECT.search(text):
        repo = m.group("name").lower()
    text = _PROJECT.sub(" ", text)

    priority: str | None = None
    if m := _PRIORITY.search(text):
        priority = f"P{m.group(1)}"
    text = _PRIORITY.sub(" ", text)

    text = re.sub(r"\s+", " ", text).strip(" ,.-–—")
    return QuickAddParse(text=text, due_date=due_date, context=context, repo=repo, priority=priority)
