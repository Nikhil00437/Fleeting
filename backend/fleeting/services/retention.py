"""#138: retention policies per capture source.

The global `notes.trash_retention_days` says how long something sits in the
trash before it is really gone. It does not say how long it should be in the
database at all. A YouTube transcript and a hand-written note are not the same
kind of thing: the first is a byproduct of watching something, the second is
something you wrote. A policy of `"youtube:7"` keeps the second forever and ages
the first out in a week.

**Retention trashes; it does not delete.** Moving to the trash is the recoverable
step, and `trash_retention_days` is what turns that into a permanent one. A
retention policy that hard-deleted would be a slow-motion version of the panic
button (#136) — the user would lose data on a timer they set once and forgot,
with no window in which to notice. So this reuses that same erase path, which is
the note the tracker already made: *#136 and #138 are the same erase routine
with different cutoffs*.

The same `bulk.preview` / `require_confirm` pair as every other destructive
call, because "are you sure" should mean the same thing everywhere, and
`record_audit` because a policy firing on a timer is exactly the sort of thing
you want in `/api/audit` six months later with no memory of enabling it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Database
from .bulk import preview, require_confirm

log = logging.getLogger("fleeting.retention")

# A policy under a day would fire on the next poll and delete things faster than
# a person could notice. One day is the floor that still means anything.
MIN_DAYS = 1

# Further back than this is not a policy, it is a request to empty the database,
# and `preview()` is the thing that makes the difference visible.
MAX_DAYS = 3650


def parse_policies(spec: str) -> dict[str, int]:
    """`"youtube:7, file:30"` → `{"youtube": 7, "file": 30}`.

    Malformed entries are dropped rather than raising. A typo in a config file
    should not stop the app starting, and the preview reports what was actually
    understood — which is how the user finds the typo.
    """
    out: dict[str, int] = {}
    for part in (spec or "").split(","):
        entry = part.strip()
        if not entry or ":" not in entry:
            continue
        name, _, raw = entry.partition(":")
        name = name.strip()
        try:
            days = int(raw.strip())
        except ValueError:
            continue
        if not name or days < MIN_DAYS:
            continue
        out[name] = min(days, MAX_DAYS)
    return out


def due_notes(db: Database, policies: dict[str, int], now: datetime | None = None) -> list[dict]:
    """Notes past their source's cutoff, oldest first.

    Sources not in the policy are never due — there is no catch-all, because a
    policy that quietly applied to everything would delete the notes you wrote
    in favour of the ones you were dictated.
    """
    if not policies:
        return []
    now = now or datetime.now(timezone.utc)
    found: list[dict] = []
    for source, days in policies.items():
        cutoff = (now - timedelta(days=days)).isoformat(timespec="seconds")
        found.extend(
            dict(row)
            for row in db.execute(
                "SELECT id, title, type, created_at FROM notes"
                " WHERE type = ? AND trashed_at IS NULL AND created_at < ?"
                " ORDER BY created_at ASC",
                (source, cutoff),
            )
        )
    found.sort(key=lambda row: str(row.get("created_at") or ""))
    return found


def preview_due(db: Database, policies: dict[str, int]) -> dict[str, Any]:
    """The standard bulk preview, so a retention run reads like every other
    destructive confirmation."""
    rows = due_notes(db, policies)
    return preview(
        len(rows),
        [{"id": r["id"], "title": r.get("title"), "type": r.get("type"), "created_at": r.get("created_at")} for r in rows],
        policies=policies,
        operation="move to trash",
        recoverable=True,
    )


def prune(
    db: Database,
    spec: str,
    confirm: bool,
    bus: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply the policies. Trashes what is due, if confirmed.

    Returns `{"ok": True}` with a zero count when nothing is due: a dialog
    offering to delete nothing is how people learn to click through dialogs.
    """
    policies = parse_policies(spec)
    detail = preview_due(db, policies)
    require_confirm(None, confirm, detail)
    rows = due_notes(db, policies, now=now)
    if not rows:
        return {"ok": True, "trashed": 0, "detail": detail}

    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    for row in rows:
        # Soft delete, not `delete_note`. The trash window is what makes a
        # retention policy something you can undo; see the module docstring.
        db.execute(
            "UPDATE notes SET trashed_at = ? WHERE id = ? AND trashed_at IS NULL",
            (stamp, row["id"]),
        )
    db.commit()

    if bus is not None:
        for row in rows:
            bus.publish("note.updated", {"id": row["id"], "trashed_at": stamp})
        bus.publish("privacy.retention", {"policies": policies, "notes": len(rows)})
    db.record_audit(
        "privacy.retention",
        f"{len(rows)} note(s) past retention",
        {"policies": policies, "notes": len(rows)},
    )
    log.info("retention: trashed %d note(s) across %d policy(ies)", len(rows), len(policies))
    return {"ok": True, "trashed": len(rows), "detail": detail}


def describe_policies(spec: str) -> dict[str, Any]:
    """What the user wrote, and what was understood — so a typo is visible
    rather than a policy that quietly does nothing."""
    policies = parse_policies(spec)
    written = [p.strip() for p in (spec or "").split(",") if p.strip()]
    return {
        "policies": policies,
        "written": written,
        "ignored": [w for w in written if w.partition(":")[0].strip() not in policies],
        "explains": (
            "Notes are moved to the trash, then removed by `notes.trash_retention_days`."
            if policies
            else "No policies configured; nothing is aged out."
        ),
    }


__all__ = [
    "MAX_DAYS",
    "MIN_DAYS",
    "describe_policies",
    "due_notes",
    "parse_policies",
    "preview_due",
    "prune",
]
