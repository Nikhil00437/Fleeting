"""#390: jobs per hour, median enrichment time, error rate.

Only one of the three needs new data. Jobs per hour and error rate are both
derivable from `notes.status` and `processed_at`; a *duration* is not, because
nothing recorded how long a capture took. So the whole of #390's storage cost is
one nullable integer column.

`processed_at` was written on success only, which quietly made two of the three
metrics wrong: a failed capture had no timestamp, so an error rate computed
over the last hour silently ignored every failure in that hour. That is the kind
of number that looks fine precisely when it matters.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.process import Processor
from fleeting.services.runtime_metrics import (
    enrichment_summary,
    job_throughput,
    summarise,
)


@pytest.fixture()
def db(tmp_path) -> Database:
    d = Database(str(tmp_path / "m.db"))
    d.migrate()
    return d


def _note(db: Database, *, status: str, at: datetime, enrich_ms: int | None) -> None:
    db.insert_note(
        {
            "raw_text": "something",
            "title": "t",
            "type": "text",
            "status": status,
            "processed_at": at.isoformat(),
            "enrich_ms": enrich_ms,
            "error": "boom" if status == "failed" else None,
        }
    )


# ---- the column -----------------------------------------------------------


def test_the_duration_column_exists_and_is_nullable(db: Database) -> None:
    """Guarded columns are added idempotently; a NOT NULL default would make
    every existing row claim a duration it never had."""
    db.insert_note({"raw_text": "x", "title": "t", "type": "text"})
    row = db.get_note(db.execute("SELECT id FROM notes").fetchone()["id"])
    assert "enrich_ms" in row
    assert row["enrich_ms"] is None


@pytest.mark.anyio
async def test_a_finished_capture_records_its_duration(tmp_path) -> None:
    """The whole reason the column exists."""
    db = Database(str(tmp_path / "p.db"))
    db.migrate()
    cfg = Config()
    cfg.llm.provider = "none"
    proc = Processor(db, cfg, EventBus(), _NeverTranscribes())

    note = db.insert_note({"raw_text": "a real thought about the router", "type": "text"})["id"]
    proc.start()
    proc.enqueue(note)
    for _ in range(1500):
        row = db.get_note(note)
        if row.get("status") in ("done", "failed"):
            break
        await __import__("asyncio").sleep(0.01)
    else:
        raise AssertionError("never settled")

    assert row["status"] == "done"
    assert row["enrich_ms"] is not None and row["enrich_ms"] >= 0


class _NeverTranscribes:
    """Enough of a transcriber for a text capture, which never calls it."""

    loaded_model_size = "base"

    def __init__(self) -> None:
        from fleeting.config import Config as C

        self.cfg = C().transcribe

    def is_ready(self) -> bool:
        return True

    def transcribe_file(self, path, language=None):  # pragma: no cover
        raise AssertionError("a text capture must not transcribe")


# ---- the three metrics ----------------------------------------------------


def test_throughput_counts_completed_jobs_per_hour(db: Database) -> None:
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        _note(db, status="done", at=now - timedelta(minutes=5 * i), enrich_ms=100)
    _note(db, status="done", at=now - timedelta(hours=3), enrich_ms=100)
    # Still queued: not a completed job, so not counted.
    db.insert_note({"raw_text": "pending", "title": "t", "type": "text", "status": "pending"})

    out = job_throughput(db, hours=6, end=now)
    assert out["total"] == 4
    assert sum(b["count"] for b in out["buckets"]) == 4
    # Two of the three land in the 11:00 bucket, the third at 12:00 exactly.
    by_hour = {b["hour"]: b["count"] for b in out["buckets"]}
    assert by_hour["2026-10-12T11"] == 2, out["buckets"]
    assert by_hour["2026-10-12T12"] == 1, out["buckets"]


def test_throughput_is_empty_rather_than_zero_when_nothing_ran(db: Database) -> None:
    out = job_throughput(db, hours=6, end=datetime.now(timezone.utc))
    assert out["total"] == 0
    assert out["buckets"] == []


def test_the_median_is_a_median(db: Database) -> None:
    """A mean would hide one capture that took 90 seconds behind twenty fast
    ones, which is exactly the regression this is meant to surface."""
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    for ms in [100, 200, 300, 90_000]:
        _note(db, status="done", at=now, enrich_ms=ms)
    assert enrichment_summary(db, end=now)["median_ms"] == 250


def test_the_median_ignores_failures_and_untimed_rows(db: Database) -> None:
    """A failed capture has no enrichment to time, and counting its gap as a
    duration would drag the median toward the timeout."""
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    _note(db, status="done", at=now, enrich_ms=100)
    _note(db, status="done", at=now, enrich_ms=300)
    _note(db, status="failed", at=now, enrich_ms=None)
    _note(db, status="done", at=now, enrich_ms=None)
    assert enrichment_summary(db, end=now) == {"median_ms": 200, "samples": 2, "p95_ms": 300}
    # p95 of [100, 300] by nearest rank is 300 — the value that is there.


def test_error_rate_counts_both_sides(db: Database) -> None:
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    for _ in range(3):
        _note(db, status="done", at=now, enrich_ms=10)
    for _ in range(1):
        _note(db, status="failed", at=now, enrich_ms=None)
    out = summarise(db, hours=24, end=now)
    assert out["errors"]["failed"] == 1
    assert out["errors"]["rate"] == pytest.approx(0.25)


def test_a_clean_run_reports_zero_errors_not_none(db: Database) -> None:
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    _note(db, status="done", at=now, enrich_ms=10)
    out = summarise(db, hours=24, end=now)
    assert out["errors"]["failed"] == 0
    assert out["errors"]["rate"] == 0.0


def test_the_window_excludes_older_work(db: Database) -> None:
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    _note(db, status="done", at=now, enrich_ms=10)
    _note(db, status="failed", at=now - timedelta(hours=30), enrich_ms=None)
    out = summarise(db, hours=24, end=now)
    assert out["errors"]["failed"] == 0
    assert out["errors"]["total"] == 1


def test_the_median_matches_what_statistics_would_return(db: Database) -> None:
    """Pinned against the stdlib rather than a hand-rolled mean, so the value is
    checkable by eye."""
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    values = [50, 60, 70, 80, 90, 100, 5000]
    for v in values:
        _note(db, status="done", at=now, enrich_ms=v)
    assert enrichment_summary(db, end=now)["median_ms"] == statistics.median(values)

# ---- failures must be visible --------------------------------------------


@pytest.mark.anyio
async def test_a_failed_capture_still_carries_a_timestamp(tmp_path) -> None:
    """The reason `_fail` now writes `processed_at`.

    Before this, a failure left `processed_at` NULL, so it fell outside every
    windowed query: throughput did not count it and the error rate came back
    clean. A metric that hides failures is worse than no metric.
    """
    import asyncio

    db = Database(str(tmp_path / "f.db"))
    db.migrate()
    proc = Processor(db, Config(), EventBus(), _AlwaysFails())

    note = db.insert_note({"raw_text": "memo", "type": "voice", "audio_path": "/nope.wav"})["id"]
    proc.start()
    proc.enqueue(note)
    for _ in range(1500):
        row = db.get_note(note)
        if row.get("status") in ("done", "failed"):
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("never settled")

    assert row["status"] == "failed"
    assert row["processed_at"], "a failed capture has no timestamp"
    assert row["enrich_ms"] is None, "a failure has no enrichment to time"


class _AlwaysFails:
    loaded_model_size = "base"

    def __init__(self) -> None:
        from fleeting.config import Config as C
        from fleeting.services.transcribe import TranscriptionError

        self.cfg = C().transcribe
        self._exc = TranscriptionError("whisper failed: model load failed")

    def is_ready(self) -> bool:
        return True

    def transcribe_file(self, path, language=None):
        raise self._exc
