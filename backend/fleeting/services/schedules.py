"""#106 scheduled assistant jobs: "every Friday 5pm, draft my week summary".

A job is a named prompt and a schedule. Nothing else. It is deliberately not a
script, because a script that runs unattended is code the user cannot read in
the place where they would check it, and the whole safety envelope of this
version rests on the user being able to see what the model is about to do.

Three properties matter more than the feature:

- **A misfiring job is loud.** A schedule that cannot be parsed is refused at
  creation, not silently skipped at 5pm.
- **Nothing runs twice, and nothing runs late.** `last_run` stops a double
  tick, and there is no catch-up scan at all: the runner asks about *now* once
  a minute, so a laptop asleep for three hours wakes to nothing rather than to
  three missed digests.
- **Jobs write through the same door as the assistant.** A job produces an
  ordinary chat turn, so confirm-before-act, undo and the trace all apply. A
  scheduler that could bypass them would be the hole this version exists to
  close.

Five schedule shapes, because those are the ones people actually say. A full
cron parser is a project, not a feature.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..db import Database

log = logging.getLogger("fleeting.schedules")

# "every friday 5pm", "daily at 9am", "mondays at 08:30", "weekdays at 7",
# "monthly on the 1st". Five shapes, because these are the five things people
# say, and a real cron parser would be a project with its own edge cases.
_DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_EVERY_DAY = re.compile(r"^every\s+day|^(daily|everyday)$|^every\s+morning$")
_EVERY_WEEKDAY = re.compile(r"^(every\s+)?weekdays?$")
_EVERY_WEEK = re.compile(
    # The alternatives are grouped before the "s" — ungrouped, it binds to
    # "sunday" alone, so "mondays" and "fridays" stop matching.
    rf"^(?:every\s+)?(?P<day>{'|'.join(_DAY_NAMES)})s?$"
)
_MONTHLY = re.compile(r"^(every\s+month|monthly)(\s+on\s+the\s+(?P<dom>\d{1,2})(?:st|nd|rd|th)?)?$")
_TIME = re.compile(r"\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)\b|\b(?P<h24>\d{1,2}):(?P<m24>\d{2})\b")
_AT = re.compile(r"\b(at|@)\b")
# Only used to reuse the parsing path above; the real hour comes from the
# pre-"at" number.
_BARE = re.compile(r"^(?P<ampm>am|pm) (?P<h>\d{1,2})$")

MAX_JOBS = 50


@dataclass
class Schedule:
    job_id: str
    prompt: str
    raw: str
    kind: str
    hour: int
    minute: int
    weekday: int | None = None
    day_of_month: int | None = None
    created_at: str = ""
    last_run: str | None = None
    enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.job_id,
            "prompt": self.prompt,
            "schedule": self.raw,
            "kind": self.kind,
            "hour": self.hour,
            "minute": self.minute,
            "weekday": self.weekday,
            "day_of_month": self.day_of_month,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "enabled": self.enabled,
        }


def parse_schedule(text: str) -> dict[str, Any]:
    """Turn a phrase into a schedule, or raise ValueError with the reason.

    Refused rather than guessed. A schedule that silently means the wrong hour
    is worse than one that was never created: the user would find out at 5am.
    """
    raw = (text or "").strip().lower()
    if not raw:
        raise ValueError("empty schedule")

    hour: int | None = None
    minute = 0
    # "at 7" has no am/pm and no colon, and it is the most common thing people
    # type. Checked after the formatted times so 5pm is never read as 5.
    bare = re.search(r"\b(?:at|@)\s+(\d{1,2})\b", raw)
    match = _TIME.search(raw)
    if not match and bare:
        hour = int(bare.group(1))
        if hour > 23:
            raise ValueError(f"'{text}' is not a time of day")
        # Remove the number too: "weekdays at 7" must reduce to "weekdays",
        # or the leftover digit makes the kind unrecognisable.
        raw = raw[: bare.start(1)] + " " + raw[bare.end(1) :]
    elif match:
        if match.group("h24") is not None:
            hour, minute = int(match.group("h24")), int(match.group("m24"))
        else:
            hour = int(match.group("h"))
            minute = int(match.group("m") or 0)
            if match.group("ampm") == "pm" and hour < 12:
                hour += 12
            elif match.group("ampm") == "am" and hour == 12:
                hour = 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"'{text}' is not a time of day")

    weekday: int | None = None
    dom: int | None = None
    kind: str | None = None

    stripped = _TIME.sub("", raw)
    stripped = _AT.sub(" ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()

    if _EVERY_DAY.match(stripped):
        kind = "daily"
    elif _EVERY_WEEKDAY.match(stripped):
        kind = "weekday"
    elif _MONTHLY.match(stripped):
        kind = "monthly"
        dom_match = _MONTHLY.match(stripped)
        if dom_match and dom_match.group("dom"):
            dom = int(dom_match.group("dom"))
            if not 1 <= dom <= 31:
                raise ValueError(f"there is no {dom}th of the month")
    else:
        week = _EVERY_WEEK.match(stripped)
        if week:
            kind = "weekly"
            name = week.group("day") or ""
            name = name.rstrip("s")
            weekday = _DAY_NAMES.index(name) if name in _DAY_NAMES else None
            if weekday is None:
                raise ValueError(f"'{name}' is not a day of the week")

    if kind is None:
        raise ValueError(
            "I could not read that schedule. Try: 'every friday at 5pm', "
            "'daily at 9am', 'weekdays at 7', 'mondays at 8:30', "
            "or 'monthly on the 1st'."
        )
    if hour is None:
        raise ValueError("that schedule has no time — add one, e.g. 'at 5pm'")
    return {
        "kind": kind,
        "hour": hour,
        "minute": minute,
        "weekday": weekday,
        "day_of_month": dom,
    }


def is_due(sched: Schedule, now: datetime) -> bool:
    """True when this job should run at `now`.

    Matching is on the minute, not the window, because the caller is what
    ticks; the window logic lives in `due_jobs` so a single tick cannot fire
    the same job twice.
    """
    if not sched.enabled:
        return False
    if now.hour != sched.hour or now.minute != sched.minute:
        return False
    if sched.kind == "weekly":
        return sched.weekday == now.weekday()
    if sched.kind == "weekday":
        return now.weekday() < 5
    if sched.kind == "monthly":
        return now.day == (sched.day_of_month or 1)
    return True


def _encode(sched: Schedule) -> str:
    return json.dumps(
        {
            "id": sched.job_id,
            "prompt": sched.prompt,
            "raw": sched.raw,
            "kind": sched.kind,
            "hour": sched.hour,
            "minute": sched.minute,
            "weekday": sched.weekday,
            "day_of_month": sched.day_of_month,
            "created_at": sched.created_at,
            "last_run": sched.last_run,
            "enabled": sched.enabled,
        },
        ensure_ascii=False,
    )


def _decode(row: dict) -> Schedule | None:
    raw = row.get("body") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        log.warning("schedule %s is unparseable; skipping it", row.get("id"))
        return None
    try:
        return Schedule(
            job_id=str(data["id"]),
            prompt=str(data["prompt"]),
            raw=str(data.get("raw", "")),
            kind=str(data["kind"]),
            hour=int(data["hour"]),
            minute=int(data.get("minute", 0)),
            weekday=data.get("weekday"),
            day_of_month=data.get("day_of_month"),
            created_at=str(data.get("created_at") or ""),
            # The columns are authoritative. `mark_run` writes last_run to the
            # row, and reading it back out of the JSON body meant a job that
            # had just run looked like it never had — and so fired twice.
            last_run=row.get("last_run"),
            enabled=bool(row.get("enabled", 1)),
        )
    except Exception:
        log.warning("schedule %s is missing fields; skipping it", row.get("id"))
        return None


def create_job(db: "Database", prompt: str, schedule_text: str) -> Schedule:
    """Parse, then store. Parsing happens first so a bad phrase never becomes
    a row that quietly fails at 5pm."""
    parsed = parse_schedule(schedule_text)
    if not (prompt or "").strip():
        raise ValueError("a job needs something to do")
    if len(list_jobs(db)) >= MAX_JOBS:
        raise ValueError(f"you already have {MAX_JOBS} jobs")

    now = datetime.now().astimezone()
    sched = Schedule(
        job_id=new_id(),
        prompt=prompt.strip(),
        raw=(schedule_text or "").strip(),
        created_at=now.isoformat(timespec="seconds"),
        **parsed,
    )
    db.execute(
        "INSERT INTO schedules (id, job, body, last_run, enabled, at) "
        "VALUES (:id, :job, :body, NULL, 1, :at)",
        {"id": sched.job_id, "job": sched.prompt[:120], "body": _encode(sched), "at": sched.created_at},
    )
    db.commit()
    return sched


def list_jobs(db: "Database") -> list[Schedule]:
    rows = db.execute("SELECT * FROM schedules ORDER BY at ASC").fetchall()
    return [s for s in (_decode(dict(r)) for r in rows) if s]


def delete_job(db: "Database", job_id: str) -> bool:
    db.execute("DELETE FROM schedules WHERE id = ?", (job_id,))
    db.commit()
    return True


def set_enabled(db: "Database", job_id: str, enabled: bool) -> Schedule | None:
    sched = next((s for s in list_jobs(db) if s.job_id == job_id), None)
    if not sched:
        return None
    sched.enabled = enabled
    db.execute(
        "UPDATE schedules SET body = ?, enabled = ? WHERE id = ?",
        (_encode(sched), 1 if enabled else 0, job_id),
    )
    db.commit()
    return sched


def due_jobs(db: "Database", now: datetime) -> list[Schedule]:
    """Jobs due at this exact minute, and not already run for it.

    Deliberately no catch-up window. A job missed while the laptop slept is
    missed, and firing it on wake is worse than not firing it at all.
    """
    due: list[Schedule] = []
    for sched in list_jobs(db):
        if not sched.enabled:
            continue
        target = now.replace(second=0, microsecond=0)
        if is_due(sched, target):
            if sched.last_run == target.isoformat(timespec="minutes"):
                continue
            due.append(sched)
    return due


def mark_run(db: "Database", job_id: str, when: datetime) -> None:
    stamp = when.isoformat(timespec="minutes")
    db.execute("UPDATE schedules SET last_run = ? WHERE id = ?", (stamp, job_id))
    db.commit()
    for sched in list_jobs(db):
        if sched.job_id == job_id:
            sched.last_run = stamp


def next_run_after(sched: Schedule, now: datetime) -> str | None:
    """When this job next fires, for the UI to show rather than hide."""
    probe = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 14):
        if is_due(sched, probe):
            return probe.isoformat(timespec="minutes")
        probe += timedelta(minutes=1)
    return None


from ..db import new_id  # noqa: E402  (kept last: avoids a circular import)


async def run_due_jobs(db: "Database", cfg: Any, bus: Any, *, now: datetime | None = None) -> list[dict]:
    """Run everything due right now, through the ordinary assistant path.

    A job produces a normal chat turn, so confirm-before-act, the undo token
    and the trace all apply to it exactly as they do to a typed question. A
    scheduler with its own execution path would be a hole straight through the
    safety envelope this version exists to build.

    A failing job is logged and skipped. One unreachable model must not stop
    the other jobs, and must not stop the next tick either.
    """
    moment = now or datetime.now().astimezone()
    results: list[dict] = []
    for sched in due_jobs(db, moment):
        mark_run(db, sched.job_id, moment)
        try:
            from .assistant import ask_assistant

            outcome = await ask_assistant(
                [{"role": "user", "content": sched.prompt}],
                db,
                cfg,
                bus=bus,
            )
            results.append({"id": sched.job_id, "ok": True, "answer": outcome.get("message", "")})
        except Exception as exc:
            log.warning("scheduled job %s failed: %s", sched.job_id, exc)
            results.append({"id": sched.job_id, "ok": False, "error": str(exc)[:200]})
    return results