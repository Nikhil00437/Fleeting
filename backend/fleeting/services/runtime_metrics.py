"""#390: how the app itself is doing, as opposed to what it recorded.

Three numbers, all derived from `notes`. Two of them — jobs per hour and error
rate — were already computable and one, a duration, was not, so the entire
storage cost of this item is one nullable integer column.

Aggregated in SQL rather than by pulling rows into Python: a busy day is a few
thousand notes and this runs on a view the user may well leave open. The
duration median and p95 are done in Python because SQLite has no percentile
function, but only over the rows the query already narrowed to the window.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Database

# Not a per-hour wall clock on purpose: an hour with no work should be absent
# from the series rather than present and zero, because "nothing happened" and
# "nothing was measured" look identical once they are both rendered as a bar.
_BUCKET = "%Y-%m-%dT%H"


def _end(end: datetime | None) -> datetime:
    """The window's end. A parameter so tests are not coupled to the clock —
    and so a caller replaying yesterday's log gets the same answer twice."""
    return end or datetime.now(timezone.utc)


def _cutoff(hours: int, end: datetime | None = None) -> str:
    return (_end(end) - timedelta(hours=hours)).isoformat()


def _done_rows(db: Database, hours: int, end: datetime | None = None) -> list[Any]:
    return db.execute(
        "SELECT status, error, processed_at, enrich_ms FROM notes "
        "WHERE processed_at IS NOT NULL AND processed_at >= ?",
        (_cutoff(hours, end),),
    ).fetchall()


def job_throughput(
    db: Database, *, hours: int = 24, end: datetime | None = None
) -> dict[str, Any]:
    """Completed captures per hour over the window, oldest first."""
    rows = db.execute(
        "SELECT processed_at FROM notes "
        "WHERE processed_at IS NOT NULL AND processed_at >= ? "
        "ORDER BY processed_at",
        (_cutoff(hours, end),),
    ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        stamp = str(row["processed_at"])[:13]  # YYYY-MM-DDTHH
        # `processed_at` is UTC; the bucket is labelled in UTC too, so a
        # metrics page never disagrees with itself at midnight.
        counts[stamp] = counts.get(stamp, 0) + 1

    buckets = [{"hour": h, "count": c} for h, c in sorted(counts.items())]
    return {
        "total": len(rows),
        "buckets": buckets,
        "per_hour": round(len(rows) / hours, 2) if hours else 0.0,
    }


def enrichment_summary(
    db: Database, *, hours: int = 24, end: datetime | None = None
) -> dict[str, Any]:
    """Median and p95 enrichment time, over captures that actually finished.

    A mean is the wrong statistic here: one capture that took 90 seconds hides
    behind twenty fast ones, and that is precisely the regression worth seeing.
    Failures and untimed rows are excluded — a failed capture has no enrichment
    to time, and counting the gap until it gave up would pull the median toward
    the timeout rather than toward reality.
    """
    rows = db.execute(
        "SELECT enrich_ms FROM notes "
        "WHERE status = 'done' AND enrich_ms IS NOT NULL "
        "AND processed_at IS NOT NULL AND processed_at >= ?",
        (_cutoff(hours, end),),
    ).fetchall()
    values = sorted(int(r["enrich_ms"]) for r in rows)
    if not values:
        return {"median_ms": 0, "samples": 0, "p95_ms": 0}
    return {
        "median_ms": int(statistics.median(values)),
        # Nearest-rank rather than statistics.quantiles, which needs a
        # meaningful spread to interpolate between and answers 290 for a
        # two-sample [100, 300]. Nearest-rank is the value that is actually
        # there, which is what a small window can honestly report.
        "p95_ms": values[min(len(values) - 1, (95 * len(values) + 99) // 100 - 1)],
        "samples": len(values),
    }


def summarise(
    db: Database, *, hours: int = 24, end: datetime | None = None
) -> dict[str, Any]:
    """Everything #390 asks for, in one object."""
    rows = _done_rows(db, hours, end)
    failed = sum(1 for r in rows if r["status"] == "failed")
    total = len(rows)
    return {
        "hours": hours,
        "throughput": job_throughput(db, hours=hours, end=end),
        "enrichment": enrichment_summary(db, hours=hours, end=end),
        "errors": {
            "failed": failed,
            "total": total,
            # 0.0 rather than None when nothing ran: a clean hour is a fact,
            # and a null reads as "unknown" in the UI.
            "rate": round(failed / total, 4) if total else 0.0,
        },
    }