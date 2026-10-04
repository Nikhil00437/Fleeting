"""Migration atomicity.

`executescript` implicitly COMMITs before running, then commits each statement,
so a script that fails halfway leaves a partially-migrated DB with no
`schema_version` row. Next boot re-runs migration v1 — whose bare
`CREATE TABLE notes` then fails on the table v1 itself created — and
`create_app` does not guard `migrate()`, so the service crash-loops and the
user must delete their DB by hand.
"""

from __future__ import annotations

import sqlite3

import pytest

import fleeting.db as fdb
from fleeting.db import Database


def _fresh(tmp_path, *, migrate: bool = True) -> Database:
    """Build a DB the way create_app does — Database() alone does not migrate."""
    db = Database(tmp_path / "m.db")
    if migrate:
        db.migrate()
    return db


def test_migrations_apply_cleanly(tmp_path) -> None:
    db = _fresh(tmp_path)
    v = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
    assert v == len(fdb.MIGRATIONS)


def test_migrate_is_idempotent(tmp_path) -> None:
    """Re-running on an up-to-date DB must be a no-op, not an error."""
    db = _fresh(tmp_path)
    db.migrate()
    db.migrate()
    v = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
    assert v == len(fdb.MIGRATIONS)


def test_failed_migration_leaves_no_partial_schema(tmp_path, monkeypatch) -> None:
    """A failing migration must roll back entirely and stay versioned."""
    db = _fresh(tmp_path)
    baseline = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
    assert baseline == len(fdb.MIGRATIONS)

    boom = "CREATE TABLE mig_ok (a); CREATE TABLE mig_bad (a); CREATE TABLE mig_bad (a);"
    monkeypatch.setattr(fdb, "MIGRATIONS", [*fdb.MIGRATIONS, boom])

    with pytest.raises(sqlite3.OperationalError):
        db.migrate()

    # No half-built tables left behind...
    names = {
        r["name"]
        for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "mig_ok" not in names, "statements before the failure were committed"
    assert "mig_bad" not in names

    # ...and the version marker did not advance past the broken migration.
    v = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
    assert v == baseline


def test_database_recovers_after_failed_migration(tmp_path, monkeypatch) -> None:
    """The real user story: a bad upgrade must not brick the next boot."""
    db = _fresh(tmp_path)
    boom = "CREATE TABLE mig_ok (a); CREATE TABLE mig_bad (a); CREATE TABLE mig_bad (a);"
    monkeypatch.setattr(fdb, "MIGRATIONS", [*fdb.MIGRATIONS, boom])
    with pytest.raises(sqlite3.OperationalError):
        db.migrate()

    # Plugin removed / bug fixed; MIGRATIONS is back to normal.
    monkeypatch.undo()
    db2 = Database(tmp_path / "m.db")
    db2.migrate()
    assert db2.execute(
        "SELECT MAX(version) AS v FROM schema_version"
    ).fetchone()["v"] == len(fdb.MIGRATIONS)
    # And the app still works on the recovered DB.
    db2.insert_note({"raw_text": "hello", "note_type": "text"})
    assert len(db2.list_notes(limit=10)) == 1


def test_schema_version_has_no_duplicate_rows(tmp_path) -> None:
    """The table has no PK, so a re-applied migration could duplicate rows."""
    db = _fresh(tmp_path)
    db.migrate()
    db.migrate()
    rows = db.execute("SELECT version, COUNT(*) AS c FROM schema_version GROUP BY version").fetchall()
    assert all(r["c"] == 1 for r in rows), "duplicate version rows"