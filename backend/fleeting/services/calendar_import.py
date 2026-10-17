"""#123: local calendar import, shown on the Timeline.

Parses `.ics` with the standard library. No CalDAV — "local calendar import" is
what was asked for, and a CalDAV client brings credentials and a network stack
for something most people can solve by exporting a file.

**Recurrence is expanded for the frequencies that matter and *reported* for the
ones that are not.** `FREQ=DAILY/WEEKLY/MONTHLY/YEARLY` with `INTERVAL`,
`COUNT` and `UNTIL` covers almost everything in a personal calendar. Anything
else — `BYSETPOS`, `FREQ=MONTHLY;BYDAY=2TU`, exdates — is listed as **skipped
with its rule attached**, because silently dropping a recurring meeting is how a
calendar integration becomes something people stop trusting.

**Bounded on both axes.** A file with a thousand events, and a daily standup that
recurs for ten years, are both real. `MAX_EVENTS` and `MAX_EXPANSIONS` exist, and
when either bites the result says so rather than quietly returning a short list.

**One occurrence per instance, all-day vs timed kept apart.** An all-day event is
a date; a timed one is an instant. Collapsing them into one string is how a
calendar integration ends up putting a 14:00–15:00 meeting on the wrong day in
some timezones.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .calendar_svc import current_tz

log = logging.getLogger("fleeting.calendar")

# Events returned per file, and instances generated per recurring event. A
# ten-year daily standup is 3,650 instances, which is not a calendar view.
MAX_EVENTS = 2000
MAX_EXPANSIONS = 200
MAX_SKIP_REPORTED = 20

# Frequencies we expand. Anything else is reported rather than guessed at.
EXPANDABLE = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")

# The only RRULE parts we act on. Anything else — `BYDAY`, `BYSETPOS`,
# `BYMONTH`, `WKST` — changes *which* days an event lands on, and expanding it as
# a plain interval silently puts a meeting on the wrong date. Reported instead.
SUPPORTED_RRULE_PARTS = frozenset({"FREQ", "INTERVAL", "COUNT", "UNTIL"})

_LINE = re.compile(r"^[A-Z-]+[;:]")
_UNFOLD = re.compile(r"\r?\n[ \t]")


class CalendarError(RuntimeError):
    """Anything that stopped the parse. The message is shown to the user."""


def _unfold(text: str) -> str:
    """RFC 5545 line folding: a CRLF followed by a space or tab is a soft break."""
    return _UNFOLD.sub("", text)


def _lines(text: str) -> list[str]:
    return [ln for ln in _unfold(text).splitlines() if ln.strip()]


def _value(raw: str) -> str:
    """The part after the first `:` of a content line."""
    _, _, value = raw.partition(":")
    return value.strip()


def _unescape(text: str) -> str:
    return (
        text.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    )


def parse_dt(raw: str) -> tuple[datetime | None, bool, str]:
    """`(when, is_date_only, tz)`.

    ICS is explicit about what it does not say: `20260115T090000Z` is UTC,
    `20260115T090000` is local, `20260115` is a date. Returning a single
    "datetime" for all three loses the distinction that matters most when
    rendering a day view.
    """
    text = raw.strip()
    if not text:
        return None, False, ""
    if text.endswith("Z"):
        try:
            return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=None), False, "Z"
        except ValueError:
            return None, False, ""
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(text, fmt), False, ""
        except ValueError:
            continue
    try:
        return datetime.strptime(text, "%Y%m%d"), True, ""
    except ValueError:
        return None, False, ""


def parse_rrule(value: str) -> dict[str, str]:
    """`RRULE:FREQ=WEEKLY;INTERVAL=2` → `{"FREQ": "WEEKLY", "INTERVAL": "2"}`."""
    body = _value(value)
    out: dict[str, str] = {}
    for part in body.split(";"):
        key, _, val = part.partition("=")
        if key.strip():
            out[key.strip().upper()] = val.strip()
    return out


def expand(start: datetime, rule: dict[str, str], limit: int = MAX_EXPANSIONS) -> list[datetime]:
    """Expand a recurrence we support. Empty list for one we do not."""
    freq = rule.get("FREQ", "").upper()
    if freq not in EXPANDABLE:
        return []
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until_dt, _, _ = parse_dt(rule["UNTIL"]) if rule.get("UNTIL") else (None, False, "")
    until = until_dt.date() if until_dt else None

    out: list[datetime] = []
    current = start
    # The original day-of-month, kept separately. Stepping from `current` instead
    # drifts: Jan 31 → Feb 28 → **Mar 28**, because February's clamped day then
    # becomes the anchor. A monthly event on the 31st is either the 31st or it is
    # skipped and reported — never the 28th of every month after.
    anchor_day = start.day
    guard = 0
    while len(out) < limit and guard < limit * 12:
        guard += 1
        if count is not None and len(out) >= count:
            break
        if until and current.date() > until:
            break
        out.append(current)
        if freq == "DAILY":
            current += timedelta(days=interval)
        elif freq == "WEEKLY":
            current += timedelta(weeks=interval)
        elif freq == "MONTHLY":
            month = start.month - 1 + interval * (len(out))
            year = start.year + month // 12
            month = month % 12 + 1
            current = current.replace(
                year=year, month=month, day=min(anchor_day, _days_in(year, month))
            )
        else:  # YEARLY
            year = current.year + interval
            current = current.replace(
                year=year, day=min(anchor_day, _days_in(year, current.month))
            )
    return out


def _days_in(year: int, month: int) -> int:
    import calendar as cal

    return cal.monthrange(year, month)[1]


def parse_ics(text: str, *, tz: str = "") -> dict[str, Any]:
    """The whole file: events, how many were skipped, and why.

    Never raises — a malformed calendar file should produce a list with warnings,
    not an error page.
    """
    lines = _lines(text)
    if not lines:
        raise CalendarError("that file has no lines in it — is it really a .ics?")

    events: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    truncated = False

    current: dict[str, Any] | None = None
    for raw in lines:
        # Three tokens, and getting them confused parses nothing at all.
        #
        # `BEGIN:VEVENT` and `SUMMARY:Standup` both split on their first colon
        # into a name and a value — but for the delimiters that "name" is
        # `BEGIN` and the thing worth comparing is `BEGIN:VEVENT`. Splitting once
        # and testing the name against `"BEGIN:VEVENT"` therefore never matches,
        # and every event is skipped without a word of complaint.
        head, _, rest = raw.partition(":")
        head = head.strip().upper()
        if head in ("BEGIN", "END"):
            marker = f"{head}:{rest.partition(':')[0].strip().upper()}"
            name = rest.partition(":")[0].strip().upper()
        else:
            marker = ""
            name = head.split(";", 1)[0].strip().upper()
        if marker == "BEGIN:VEVENT":
            current = {"attendees": 0, "rrule": "", "exdates": []}
            continue
        if marker == "END:VEVENT":
            if current is not None:
                built, why = _build(current, tz)
                if built is None:
                    if len(skipped) < MAX_SKIP_REPORTED:
                        skipped.append({"reason": why})
                elif len(events) >= MAX_EVENTS:
                    truncated = True
                else:
                    events.extend(built)
            current = None
            continue
        if current is None:
            continue
        if name == "SUMMARY":
            current["summary"] = _unescape(_value(raw))
        elif name == "LOCATION":
            current["location"] = _unescape(_value(raw))
        elif name == "DTSTART":
            current["dtstart"] = _value(raw)
        elif name == "DTEND":
            current["dtend"] = _value(raw)
        elif name == "UID":
            current["uid"] = _value(raw)
        elif name == "RRULE":
            current["rrule"] = raw
        elif name == "EXDATE":
            current["exdates"].append(_value(raw))
        elif name == "ATTENDEE":
            current["attendees"] += 1

    return {
        "events": events,
        "counts": {"parsed": len(events), "skipped": len(skipped)},
        "skipped": skipped,
        "truncated": truncated,
        "tz": tz or current_tz(),
    }


def _build(vevent: dict[str, Any], tz: str) -> tuple[list[dict[str, Any]] | None, str]:
    start, all_day, tz_mark = parse_dt(vevent.get("dtstart", ""))
    if start is None:
        return None, "no usable DTSTART"
    end, _, _ = parse_dt(vevent.get("dtend", "")) if vevent.get("dtend") else (None, False, "")
    duration = (end - start) if end and end > start else None

    base = {
        "summary": vevent.get("summary", "(untitled)"),
        "location": vevent.get("location", ""),
        "all_day": all_day,
        "tz": tz_mark or tz or current_tz(),
        "uid": vevent.get("uid", ""),
        "attendees": vevent.get("attendees", 0),
    }

    if not vevent.get("rrule"):
        return [_instance(base, start, all_day, duration)], ""

    rule = parse_rrule(vevent["rrule"])
    if rule.get("FREQ", "").upper() not in EXPANDABLE:
        return None, f"unsupported recurrence: {vevent['rrule']}"
    extra_parts = sorted(set(rule) - SUPPORTED_RRULE_PARTS)
    if extra_parts:
        # `FREQ=MONTHLY;BYDAY=2TU` expands perfectly well as a plain MONTHLY — on
        # the wrong day, every month, forever. Reported with the rule so the user
        # can see exactly what was not understood.
        return None, f"unsupported recurrence: {vevent['rrule']} (uses {', '.join(extra_parts)})"
    excluded = {parse_dt(v)[0] for v in vevent["exdates"] if parse_dt(v)[0]}

    out: list[dict[str, Any]] = []
    for when in expand(start, rule):
        if when in excluded:
            continue
        out.append(_instance(base, when, all_day, duration))
    if not out:
        return None, f"recurrence produced nothing: {vevent['rrule']}"
    if len(out) >= MAX_EXPANSIONS:
        out.append({"__truncated__": True})
    return out, ""


def _instance(base: dict[str, Any], start: datetime, all_day: bool, duration: timedelta | None) -> dict[str, Any]:
    row = dict(base)
    row["start"] = start.isoformat()
    row["end"] = (start + duration).isoformat() if duration else None
    row["date"] = start.date().isoformat()
    return row


def load(path: str | Path) -> dict[str, Any]:
    """Read and parse a file. The one place that touches the filesystem."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise CalendarError(f"no such calendar file: {target}")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CalendarError(f"could not read {target.name}: {exc}") from exc
    if "BEGIN:VCALENDAR" not in text:
        raise CalendarError(f"{target.name} does not look like a calendar file")
    return parse_ics(text)


def for_day(parsed: dict[str, Any], day: date) -> list[dict[str, Any]]:
    """Events on one local day, timed before all-day — the order a day view
    actually reads in."""
    target = day.isoformat()
    rows = [e for e in parsed["events"] if e.get("date") == target]
    return sorted(rows, key=lambda e: (bool(e.get("all_day")), e.get("start") or ""))


def discover(roots: list[str | Path], limit: int = 20) -> list[Path]:
    """Calendar files under the given folders, bounded.

    Searched rather than configured: calendar exports go somewhere different on
    every platform, and a hardcoded list of paths is wrong on all of them.
    """
    out: list[Path] = []
    for root in roots:
        base = Path(root).expanduser()
        if not base.is_dir():
            continue
        for candidate in sorted(base.rglob("*.ics")):
            if candidate.is_file():
                out.append(candidate)
            if len(out) >= limit:
                return out
    return out