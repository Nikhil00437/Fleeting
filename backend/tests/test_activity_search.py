"""Activity-aware search: query what you *did*, not only what you wrote down.

Notes are half the record. The other half is the window titles you worked
under, the commits you made and the files you saved — all of which the tracker
already collects for the daily log, but none of which were searchable. So
"what was I working on last Tuesday" could only answer from notes you happened
to capture.

Scope here is deliberately the data that is *already stored*: window sessions
(a new FTS index over `activity`) and commits (a new table, populated by the
same collection pass the daily/weekly reports already run). Saved-file paths are
not indexed — they are unbounded and mostly noise.
"""

from __future__ import annotations

import pytest

from fleeting.db import Database


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "s.db")
    d.migrate()
    return d


def _session(db: Database, day: str, app: str, title: str, seconds: int = 600) -> None:
    db.upsert_activity(
        {
            "app_class": app,
            "title": title,
            "first_seen": f"{day}T10:00:00+00:00",
            "last_seen": f"{day}T11:00:00+00:00",
            "seconds": seconds,
            "day": day,
        }
    )


def _commit(db: Database, repo: str, subject: str, when: str) -> None:
    db.record_commit(repo=repo, subject=subject, author="", committed_at=when)


# ---------------------------------------------------------------------------
# the activity index
# ---------------------------------------------------------------------------


def test_window_titles_are_searchable(db: Database) -> None:
    _session(db, "2026-10-04", "code", "fleeting — routers/notes.py — fleeting")
    hits = db.search_activity("routers/notes.py")
    assert len(hits) == 1
    assert "routers/notes.py" in hits[0]["title"]


def test_search_matches_the_app_class_too(db: Database) -> None:
    _session(db, "2026-10-04", "firefox", "kubernetes ingress docs")
    hits = db.search_activity("firefox")
    assert len(hits) == 1


def test_search_is_case_insensitive(db: Database) -> None:
    _session(db, "2026-10-04", "code", "Postgres Connection Pool")
    assert db.search_activity("postgres")
    assert db.search_activity("POSTGRES")


def test_search_supports_multi_word_queries(db: Database) -> None:
    _session(db, "2026-10-04", "code", "billing retry queue worker")
    assert db.search_activity("billing retry")
    # all terms must match, not just one
    assert db.search_activity("billing kubernetes") == []


def test_search_respects_a_limit(db: Database) -> None:
    for i in range(10):
        _session(db, "2026-10-04", "code", f"retry worker {i}")
    assert len(db.search_activity("retry", limit=3)) == 3


def test_search_can_be_scoped_to_a_date_range(db: Database) -> None:
    _session(db, "2026-10-04", "code", "old work")
    _session(db, "2026-10-20", "code", "new work")
    hits = db.search_activity("work", since_day="2026-10-10")
    assert len(hits) == 1
    assert "new work" in hits[0]["title"]


def test_search_excludes_zero_second_sessions(db: Database) -> None:
    """Sub-second tab switches are hidden everywhere else; keep that rule."""
    _session(db, "2026-10-04", "zen", "noise", seconds=0)
    assert db.search_activity("noise") == []


def test_updating_a_session_reindexes_it(db: Database) -> None:
    row_id = _session_id = None
    rid = db.upsert_activity(
        {
            "app_class": "code",
            "title": "first title",
            "first_seen": "2026-10-04T10:00:00+00:00",
            "last_seen": "2026-10-04T10:05:00+00:00",
            "seconds": 300,
            "day": "2026-10-04",
        }
    )
    assert db.search_activity("first")
    db.upsert_activity(
        {
            "id": rid,
            "app_class": "code",
            "title": "second title",
            "first_seen": "2026-10-04T10:00:00+00:00",
            "last_seen": "2026-10-04T10:05:00+00:00",
            "seconds": 300,
            "day": "2026-10-04",
        }
    )
    assert db.search_activity("second"), "update did not reindex"
    assert db.search_activity("first") == [], "stale row survived the update"
    del row_id, _session_id


def test_deleting_a_session_removes_it_from_the_index(db: Database) -> None:
    rid = db.upsert_activity(
        {
            "app_class": "code",
            "title": "ephemeral",
            "first_seen": "2026-10-04T10:00:00+00:00",
            "last_seen": "2026-10-04T10:05:00+00:00",
            "seconds": 300,
            "day": "2026-10-04",
        }
    )
    assert db.search_activity("ephemeral")
    db.execute("DELETE FROM activity WHERE id = ?", (rid,))
    db.commit()
    assert db.search_activity("ephemeral") == [], "deleted session still indexed"


def test_garbage_query_does_not_raise(db: Database) -> None:
    """FTS5 syntax errors must not 500 the search endpoint."""
    for junk in ['"', "AND", "*", "a AND", "NEAR(", "((", "^"]:
        db.search_activity(junk)


def test_garbage_query_returns_empty_not_everything(db: Database) -> None:
    """The dangerous failure is a bad query matching all rows."""
    _session(db, "2026-10-04", "code", "secret project")
    assert db.search_activity('"') == []


# ---------------------------------------------------------------------------
# commits
# ---------------------------------------------------------------------------


def test_commit_round_trips(db: Database) -> None:
    db.record_commit("fleeting", "fix: timezone bug in dailylog", "nik", "2026-10-04T10:00:00+00:00")
    rows = db.search_commits("timezone")
    assert len(rows) == 1
    assert rows[0]["repo"] == "fleeting"
    assert "dailylog" in rows[0]["subject"]


def test_commits_are_searchable_by_repo(db: Database) -> None:
    db.record_commit("fleeting", "chore: bump deps", "nik", "2026-10-04T10:00:00+00:00")
    db.record_commit("studio", "feat: new canvas", "nik", "2026-10-04T11:00:00+00:00")
    assert len(db.search_commits("studio")) == 1


def test_recording_the_same_commit_twice_is_idempotent(db: Database) -> None:
    """Re-running a digest must not duplicate history."""
    for _ in range(3):
        db.record_commit("fleeting", "fix: thing", "nik", "2026-10-04T10:00:00+00:00")
    assert db.execute("SELECT COUNT(*) AS c FROM commits").fetchone()["c"] == 1


def test_commit_search_is_scoped_by_date(db: Database) -> None:
    db.record_commit("fleeting", "old fix", "nik", "2020-01-01T10:00:00+00:00")
    db.record_commit("fleeting", "new fix", "nik", "2026-10-04T10:00:00+00:00")
    hits = db.search_commits("fix", since="2026-01-01")
    assert len(hits) == 1
    assert "new" in hits[0]["subject"]


# ---------------------------------------------------------------------------
# unified search
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unified_search_spans_notes_sessions_and_commits(db: Database, tmp_path) -> None:
    from fleeting.config import Config
    from fleeting.services.search import unified_search

    n = db.insert_note({"raw_text": "postgres pool notes", "type": "text", "title": "db work"})
    nid = n["id"] if isinstance(n, dict) else n
    _session(db, "2026-10-04", "code", "postgres pool tuning")
    db.record_commit("fleeting", "fix: postgres pool exhaustion", "nik", "2026-10-04T10:00:00+00:00")

    cfg = Config()
    cfg.llm.provider = "none"
    out = await unified_search(db, cfg, "postgres pool")

    assert [x["id"] for x in out["notes"]] == [nid]
    assert len(out["sessions"]) == 1
    assert "postgres pool tuning" in out["sessions"][0]["title"]
    assert len(out["commits"]) == 1
    assert out["total"] == 3


@pytest.mark.anyio
async def test_unified_search_respects_per_bucket_limits(db: Database) -> None:
    from fleeting.config import Config
    from fleeting.services.search import unified_search

    for i in range(8):
        _session(db, "2026-10-04", "code", f"widget work {i}")
    cfg = Config()
    cfg.llm.provider = "none"
    out = await unified_search(db, cfg, "widget", limit=3)
    assert len(out["sessions"]) == 3
    assert out["total"] == 3


@pytest.mark.anyio
async def test_unified_search_handles_a_bucket_with_no_hits(db: Database) -> None:
    """Empty buckets must be present, not missing — the UI indexes into them."""
    from fleeting.config import Config
    from fleeting.services.search import unified_search

    db.insert_note({"raw_text": "only a note here", "type": "text"})
    cfg = Config()
    cfg.llm.provider = "none"
    out = await unified_search(db, cfg, "note")
    assert out["notes"]
    assert out["sessions"] == []
    assert out["commits"] == []


@pytest.mark.anyio
async def test_unified_search_rejects_an_empty_query(db: Database) -> None:
    from fleeting.config import Config
    from fleeting.services.search import unified_search

    cfg = Config()
    out = await unified_search(db, cfg, "   ")
    assert out["total"] == 0


@pytest.mark.anyio
async def test_unified_search_never_leaks_a_500_on_junk(db: Database) -> None:
    from fleeting.config import Config
    from fleeting.services.search import unified_search

    _session(db, "2026-10-04", "code", "real work")
    cfg = Config()
    cfg.llm.provider = "none"
    out = await unified_search(db, cfg, '"')
    assert out["total"] == 0


def test_collected_commits_are_persisted_for_search(db: Database, tmp_path) -> None:
    """The commits a digest already collects must become searchable.

    Shelling out to git per *search* would be far too slow, so the collection
    pass the daily/weekly reports already run is what feeds the index.
    """
    from datetime import datetime

    import fleeting.services.files_activity as fa
    from fleeting.services.search import persist_commits

    repo = tmp_path / "fleeting"
    (repo / ".git").mkdir(parents=True)
    collected = [{"repo": "fleeting", "subjects": ["fix: stored for search", "chore: x"]}]
    persist_commits(db, collected, until=datetime(2026, 10, 5).astimezone())

    rows = db.search_commits("stored for search")
    assert len(rows) == 1
    assert rows[0]["repo"] == "fleeting"

    # and it must survive being persisted twice (a re-run digest)
    persist_commits(db, collected, until=datetime(2026, 10, 5).astimezone())
    assert db.execute("SELECT COUNT(*) AS c FROM commits").fetchone()["c"] == 2


def test_persist_commits_accepts_the_flat_shape_too(db: Database) -> None:
    """Some callers already flatten; do not silently drop those."""
    from datetime import datetime

    from fleeting.services.search import persist_commits

    persist_commits(
        db,
        [{"repo": "r", "subject": "flat: shape"}],
        until=datetime(2026, 10, 5).astimezone(),
    )
    assert len(db.search_commits("flat")) == 1


def test_persist_commits_ignores_junk(db: Database) -> None:
    from datetime import datetime

    from fleeting.services.search import persist_commits

    persist_commits(
        db,
        [None, {}, {"repo": "r"}, {"subjects": "not a list"}, {"repo": "r", "subjects": []}],
        until=datetime(2026, 10, 5).astimezone(),
    )
    assert db.execute("SELECT COUNT(*) AS c FROM commits").fetchone()["c"] == 0
