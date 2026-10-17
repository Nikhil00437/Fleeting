"""Calendar import endpoints.

`/api/calendar/import` reads a local `.ics`; `/api/calendar/day` returns one
day. The parsed file is held per-process rather than written to the database —
a calendar is a read-only view, and a copy of somebody's real calendar sitting in
the notes database is a privacy problem the export feature did not ask for.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

log = logging.getLogger("fleeting.routers.calendar")

# The last parse, per process. #123 is "shown on the Timeline", which means read
# it repeatedly; re-parsing the file on every timeline render is wasteful and
# re-reading somebody's calendar off disk on every keystroke is worse.
_last: dict = {}


class ImportIn(BaseModel):
    path: str


@router.post("/import")
def import_calendar(body: ImportIn, request: Request) -> dict:
    """Parse a local `.ics`.

    Recurrence we cannot expand is **reported with its rule attached**, never
    silently dropped — a recurring meeting that quietly disappears is how a
    calendar integration becomes something people stop trusting.
    """
    from ..services.calendar_import import CalendarError, load

    try:
        parsed = load(body.path)
    except CalendarError as exc:
        raise HTTPException(400, {"error": "calendar_unreadable", "message": str(exc)}) from exc
    _last["parsed"] = parsed
    _last["path"] = body.path
    return {
        "path": body.path,
        "counts": parsed["counts"],
        "truncated": parsed["truncated"],
        "skipped": parsed["skipped"],
        "tz": parsed["tz"],
    }


@router.get("/day")
def calendar_day(request: Request, when: str | None = Query(None, alias="date")) -> dict:
    """One local day, timed events before all-day ones.

    The parameter is named `when` internally and aliased to `date` on the wire:
    a public API that says `?date_=` because of a local import is a permanent
    small ugliness in the one thing users will read.
    """
    from ..services.calendar_import import for_day

    parsed = _last.get("parsed")
    if not parsed:
        raise HTTPException(404, {"error": "no_calendar_loaded", "message": "import a calendar first"})
    try:
        day = date.fromisoformat(when) if when else date.today()
    except ValueError as exc:
        raise HTTPException(400, {"error": "bad_date", "message": str(exc)}) from exc
    return {"date": day.isoformat(), "events": for_day(parsed, day), "source": _last.get("path", "")}


@router.get("/status")
def calendar_status(request: Request) -> dict:
    """What is loaded, so the UI can say "no calendar imported" rather than
    showing an empty day that looks like a day with nothing in it."""
    parsed = _last.get("parsed")
    return {
        "loaded": parsed is not None,
        "path": _last.get("path", ""),
        "events": len(parsed["events"]) if parsed else 0,
    }
