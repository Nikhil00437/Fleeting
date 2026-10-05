"""Activity-aware search over HTTP.

Additive by design: `/api/search` keeps its exact shape, so the existing notes
search and its UI are untouched.
"""

from __future__ import annotations

import pytest


def _seed(client) -> None:
    st = client.app.state.st
    note = st.db.insert_note(
        {"raw_text": "postgres pool notes", "type": "text", "title": "db work"}
    )
    st.db.upsert_activity(
        {
            "app_class": "code",
            "title": "postgres pool tuning — fleeting",
            "first_seen": "2026-10-04T10:00:00+00:00",
            "last_seen": "2026-10-04T11:00:00+00:00",
            "seconds": 3600,
            "day": "2026-10-04",
        }
    )
    st.db.record_commit("fleeting", "fix: postgres pool exhaustion", "nik", "2026-10-04T10:00:00+00:00")


def test_unified_search_returns_all_three_buckets(client) -> None:
    _seed(client)
    body = client.get("/api/search/unified", params={"q": "postgres pool"}).json()
    assert len(body["notes"]) == 1
    assert len(body["sessions"]) == 1
    assert len(body["commits"]) == 1
    assert body["total"] == 3
    assert body["counts"] == {"notes": 1, "sessions": 1, "commits": 1}


def test_unified_search_returns_empty_buckets_rather_than_omitting_them(client) -> None:
    """The UI indexes into these; a missing key would be a render crash."""
    client.app.state.st.db.insert_note({"raw_text": "lonely", "type": "text"})
    body = client.get("/api/search/unified", params={"q": "lonely"}).json()
    for key in ("notes", "sessions", "commits", "counts", "total"):
        assert key in body
    assert body["sessions"] == []
    assert body["commits"] == []


def test_unified_search_requires_a_query(client) -> None:
    assert client.get("/api/search/unified").status_code == 422
    assert client.get("/api/search/unified", params={"q": "  "}).json()["total"] == 0


def test_unified_search_bounds_the_limit(client) -> None:
    _seed(client)
    assert client.get("/api/search/unified", params={"q": "postgres", "limit": 0}).status_code == 422
    assert client.get("/api/search/unified", params={"q": "postgres", "limit": 99999}).status_code == 422
    assert client.get("/api/search/unified", params={"q": "postgres", "limit": 5}).status_code == 200


def test_unified_search_does_not_break_the_notes_only_endpoint(client) -> None:
    """Regression guard: /api/search must still return a bare array."""
    _seed(client)
    r = client.get("/api/search", params={"q": "postgres"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert r.json()[0]["title"] == "db work"


def test_unified_search_survives_a_junk_query(client) -> None:
    """FTS5 syntax errors must not 500, and must not match everything.

    Not asserting zero results: a bare `"a"*` is a legitimate prefix query that
    may legitimately match. The property that matters is bounded output.
    """
    _seed(client)
    for junk in ['"', "*", "AND", "((", "a OR", "^", "NEAR(", "()", "a:b:c"]:
        r = client.get("/api/search/unified", params={"q": junk})
        assert r.status_code == 200, f"{junk!r} produced {r.status_code}"
        assert r.json()["total"] <= 3, f"{junk!r} matched unexpectedly many rows"


def test_unified_search_can_be_scoped_by_day(client) -> None:
    st = client.app.state.st
    st.db.upsert_activity(
        {
            "app_class": "code",
            "title": "ancient work",
            "first_seen": "2020-01-01T10:00:00+00:00",
            "last_seen": "2020-01-01T11:00:00+00:00",
            "seconds": 3600,
            "day": "2020-01-01",
        }
    )
    body = client.get(
        "/api/search/unified", params={"q": "ancient", "since_day": "2026-01-01"}
    ).json()
    assert body["sessions"] == []


# ---------------------------------------------------------------------------
# upgrade path
# ---------------------------------------------------------------------------


def test_upgrading_an_existing_db_indexes_its_history(tmp_path) -> None:
    """A user upgrading from an older build must not get an empty index."""
    import sqlite3

    import fleeting.db as fdb

    path = tmp_path / "old.db"
    # Build a DB at the pre-v8 schema, with real activity rows.
    db = fdb.Database(path)
    db.migrate()
    db.upsert_activity(
        {
            "app_class": "code",
            "title": "pre-upgrade work",
            "first_seen": "2026-10-04T10:00:00+00:00",
            "last_seen": "2026-10-04T11:00:00+00:00",
            "seconds": 600,
            "day": "2026-10-04",
        }
    )
    # Simulate "before v8" by dropping the search objects.
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "DROP TRIGGER IF EXISTS activity_ai;"
        "DROP TRIGGER IF EXISTS activity_ad;"
        "DROP TRIGGER IF EXISTS activity_au;"
        "DROP TABLE IF EXISTS activity_fts;"
        "DROP TABLE IF EXISTS commits;"
        # rewind notes schema too, else re-running v9/v10 fails on ADD COLUMN
        "DROP INDEX IF EXISTS idx_notes_capture_id;"
        "DROP INDEX IF EXISTS idx_notes_type;"
        "ALTER TABLE notes DROP COLUMN capture_id;"
        "ALTER TABLE notes DROP COLUMN source_title;"
        "DROP TABLE IF EXISTS note_links;"
        "DROP INDEX IF EXISTS idx_notes_trashed;"
        "DROP INDEX IF EXISTS idx_notes_starred;"
        "ALTER TABLE notes DROP COLUMN starred;"
        "ALTER TABLE notes DROP COLUMN trashed_at;"
        "ALTER TABLE notes DROP COLUMN color;"
        "ALTER TABLE notes DROP COLUMN fields;"
        "ALTER TABLE notes DROP COLUMN sensitive;"
        "ALTER TABLE notes DROP COLUMN review_state;"
        "DELETE FROM schema_version WHERE version >= 8;"
    )
    conn.commit()
    conn.close()

    upgraded = fdb.Database(path)
    upgraded.migrate()

    assert upgraded.search_activity("pre-upgrade"), "history not indexed on upgrade"
    # ...and new rows track from here on.
    upgraded.upsert_activity(
        {
            "app_class": "code",
            "title": "post-upgrade work",
            "first_seen": "2026-10-05T10:00:00+00:00",
            "last_seen": "2026-10-05T11:00:00+00:00",
            "seconds": 600,
            "day": "2026-10-05",
        }
    )
    assert upgraded.search_activity("post-upgrade")


def test_migration_v8_does_not_require_the_activity_table(tmp_path) -> None:
    """v8 SQL must not reference `activity`, or a DB missing it cannot migrate.

    The FTS triggers do reference it, so they are created separately in
    migrate() behind an existence check.
    """
    import sqlite3

    import fleeting.db as fdb

    path = tmp_path / "no_activity.db"
    db = fdb.Database(path)
    db.migrate()
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "DROP TRIGGER IF EXISTS activity_ai;"
        "DROP TRIGGER IF EXISTS activity_ad;"
        "DROP TRIGGER IF EXISTS activity_au;"
        "DROP TABLE IF EXISTS activity_fts;"
        "DROP TABLE IF EXISTS commits;"
        "DROP TABLE IF EXISTS activity;"
        # rewind notes schema too, else re-running v9/v10 fails on ADD COLUMN
        "DROP INDEX IF EXISTS idx_notes_capture_id;"
        "DROP INDEX IF EXISTS idx_notes_type;"
        "ALTER TABLE notes DROP COLUMN capture_id;"
        "ALTER TABLE notes DROP COLUMN source_title;"
        "DROP TABLE IF EXISTS note_links;"
        "DROP INDEX IF EXISTS idx_notes_trashed;"
        "DROP INDEX IF EXISTS idx_notes_starred;"
        "ALTER TABLE notes DROP COLUMN starred;"
        "ALTER TABLE notes DROP COLUMN trashed_at;"
        "ALTER TABLE notes DROP COLUMN color;"
        "ALTER TABLE notes DROP COLUMN fields;"
        "ALTER TABLE notes DROP COLUMN sensitive;"
        "ALTER TABLE notes DROP COLUMN review_state;"
        "DELETE FROM schema_version WHERE version >= 8;"
    )
    conn.commit()
    conn.close()

    upgraded = fdb.Database(path)
    upgraded.migrate()  # must not raise

    assert upgraded.execute(
        "SELECT MAX(version) AS v FROM schema_version"
    ).fetchone()["v"] == len(fdb.MIGRATIONS)
    upgraded.record_commit("r", "subject here")
    assert len(upgraded.search_commits("subject")) == 1
    assert upgraded.search_activity("anything") == []
