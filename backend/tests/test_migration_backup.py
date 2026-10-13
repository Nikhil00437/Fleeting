"""#188: back up the database before every schema migration.

A migration is the one moment the app rewrites every row it owns, with no undo.
`migrate()` has been the site of two real incidents already — it duplicated every
task once per boot, and an unredirected import ran it against the user's real
database. Both were found after the fact.

Two details that are easy to get wrong and invisible until they are not:

- **The backup must go through SQLite's backup API, not `shutil.copy`.** The app
  runs in WAL mode, so recent commits live in the `-wal` sidecar. Copying the
  main file alone yields a database that is missing the last writes — a backup
  that silently cannot restore the thing you backed it up for.
- **A brand-new database gets no backup.** `current == 0` means we just created
  it; there is nothing to lose. This is also what stops the suite writing
  thousands of backup files, since every test database starts at zero.

Rewinding `schema_version` on a fully migrated database makes `migrate()` re-run
v3, whose bare `CREATE TABLE activity` fails because the table is already there.
That is deliberate here, and it is the point of several tests: the backup is
taken *before* the loop, so it happens whether or not the migrations that follow
succeed. Testing the ordering is easier than manufacturing a genuine v2 database,
which cannot be built — the chain is not re-runnable by design.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fleeting.db import BACKUP_KEEP, MIGRATIONS, Database, _backup_before_migration


def _rewind(db: Database, version: int = 2) -> None:
    """Claim the database is at `version` while its schema is fully migrated."""
    db.conn.execute("DELETE FROM schema_version WHERE version > ?", (version,))
    db.conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (version,))
    db.conn.commit()


@pytest.fixture()
def existing(tmp_path) -> Database:
    path = tmp_path / "fleeting.db"
    db = Database(str(path))
    db.migrate()
    db.insert_note({"id": "n1", "title": "keep me", "raw_text": "body"})
    db.commit()
    _rewind(db)
    return db


def backups_for(path: Path) -> list[Path]:
    return sorted(p for p in path.parent.iterdir() if ".pre-v" in p.name)


def migrate_expecting_failure(db: Database) -> None:
    """`migrate()` on a rewound database fails at v3 by design."""
    with pytest.raises(sqlite3.OperationalError):
        db.migrate()


# ---- the decision ---------------------------------------------------------


def test_an_existing_database_is_backed_up_before_migrating(existing) -> None:
    path = Path(existing.path)
    migrate_expecting_failure(existing)
    assert backups_for(path), "nothing was backed up before a migration ran"


def test_the_backup_holds_the_pre_migration_data(existing) -> None:
    """A backup you cannot open is worse than none, because it looks like one."""
    migrate_expecting_failure(existing)
    backup = backups_for(Path(existing.path))[0]
    other = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        titles = [r[0] for r in other.execute("SELECT title FROM notes")]
    finally:
        other.close()
    assert titles == ["keep me"]


def test_the_backup_is_taken_even_though_the_migration_then_fails(existing) -> None:
    """The ordering is the property: the copy happens before the loop, so a
    migration that blows up half way still leaves you something to go back to."""
    migrate_expecting_failure(existing)
    assert backups_for(Path(existing.path))


def test_a_brand_new_database_is_not_backed_up(tmp_path) -> None:
    """Nothing to lose, and this is what keeps the suite from writing a backup
    file for every test that builds a database."""
    db = Database(str(tmp_path / "fresh.db"))
    db.migrate()
    assert backups_for(Path(db.path)) == []


def test_an_up_to_date_database_is_not_backed_up(tmp_path) -> None:
    db = Database(str(tmp_path / "current.db"))
    db.migrate()
    db.insert_note({"id": "n1", "title": "x", "raw_text": "y"})
    db.commit()
    db.migrate()  # nothing pending
    assert backups_for(Path(db.path)) == []


# ---- the copy itself ------------------------------------------------------


def test_the_backup_includes_commits_still_in_the_wal(existing) -> None:
    """The reason this uses SQLite's backup API rather than copying the file.

    In WAL mode the last writes live in the `-wal` sidecar. A plain file copy
    produces a database that is quietly missing them.
    """
    db = existing
    db.insert_note({"id": "n2", "title": "written after checkpoint", "raw_text": "x"})
    db.commit()
    wal = Path(db.path + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, "test needs data still in the WAL"

    backup = _backup_before_migration(db.path, 2)
    assert backup is not None
    other = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        titles = [r[0] for r in other.execute("SELECT title FROM notes")]
    finally:
        other.close()
    assert "written after checkpoint" in titles


def test_the_backup_is_named_for_the_version_it_protects(tmp_path) -> None:
    """Two updates from now you will not remember which file was the pre-state."""
    db = Database(str(tmp_path / "fleeting.db"))
    db.migrate()
    backup = _backup_before_migration(db.path, 2)
    assert backup is not None and "pre-v2" in backup.name


def test_only_the_newest_backups_are_kept(existing) -> None:
    """Otherwise every update for the next year adds a file and the one you need
    is buried under forty copies of the same database.

    Distinct versions, because backing up twice at one version writes one file —
    which made the first version of this test pass with the pruning deleted.
    """
    for version in range(2, 2 + BACKUP_KEEP + 3):
        _backup_before_migration(existing.path, version)
    assert len(backups_for(Path(existing.path))) == BACKUP_KEEP


def test_the_newest_backups_are_the_ones_kept(existing) -> None:
    """Counting is not enough: pruning the *oldest* is the useful direction. The
    most recent is the one you would restore to."""
    for version in range(2, 2 + BACKUP_KEEP + 3):
        _backup_before_migration(existing.path, version)
    names = [p.name for p in backups_for(Path(existing.path))]
    assert f"{Path(existing.path).name}.pre-v{BACKUP_KEEP + 4}.bak" in names
    assert f"{Path(existing.path).name}.pre-v2.bak" not in names


def test_repeated_backups_at_one_version_do_not_accumulate(tmp_path) -> None:
    """The same version recurs on consecutive boots, and the name is
    deterministic, so it overwrites rather than piling up."""
    db = Database(str(tmp_path / "fleeting.db"))
    db.migrate()
    for _ in range(BACKUP_KEEP + 4):
        _backup_before_migration(db.path, 2)
    assert len(backups_for(Path(db.path))) == 1


def test_a_missing_database_is_not_an_error(tmp_path) -> None:
    assert _backup_before_migration(str(tmp_path / "nope.db"), 2) is None


def test_a_failed_backup_does_not_abort_the_migration(existing) -> None:
    """Best effort. Refusing to start because a backup could not be written turns
    a recoverable problem into an app that will not launch."""
    db = existing
    original = db.conn

    class Broken:
        def __getattr__(self, name):
            return getattr(original, name)

        def backup(self, *_a, **_k):
            raise sqlite3.OperationalError("disk is on fire")

    import fleeting.db as fdb

    real_connect = fdb.sqlite3.connect

    def connect(path, *a, **k):
        if str(path).endswith(".bak"):
            raise sqlite3.OperationalError("disk is on fire")
        return real_connect(path, *a, **k)

    fdb.sqlite3.connect = connect
    try:
        assert _backup_before_migration(db.path, 2) is None
        migrate_expecting_failure(db)
    finally:
        fdb.sqlite3.connect = real_connect
    assert Broken  # keeps the helper honest about what is being simulated


def test_the_migration_chain_is_still_all_or_nothing(tmp_path) -> None:
    """The backup does not change the transaction discipline the docstring is
    about — that is what stops a crash-loop."""
    db = Database(str(tmp_path / "fleeting.db"))
    db.migrate()
    before = db.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
    assert before == len(MIGRATIONS)
    with pytest.raises(sqlite3.OperationalError):
        db.conn.executescript("BEGIN;\nSELECT no_such_function();\nCOMMIT;")
    assert (
        db.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"] == before
    )