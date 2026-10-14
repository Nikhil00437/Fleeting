"""#113/#118/#120: the vault sync log.

The log exists to answer one question the filesystem cannot: **does this file
still hold the bytes we wrote, or has it been edited since?**

A `stat()` says the file is newer than the database row. It cannot say whether
the content is ours or the user's edit on top of it. That is the whole basis of
conflict detection — and the failure mode when you get it wrong is silent and
serious: every file touched in Obsidian looks like a conflict, every conflict
looks like "a change to accept", and resolving them overwrites the user's actual
work.

Pinned here:

1. **Both hashes are recorded.** By the time anyone resolves a conflict the
   "before" is otherwise unrecoverable.
2. **The log never stops the write it is logging.** A logging failure that
   propagates turns "the vault did not sync" into "the note was not saved".
3. **It is a log, not a mirror.** Capped, append-only. A second copy of the
   vault in a place nobody expects to find one is a liability, not a feature.
"""

from __future__ import annotations

import pytest

from fleeting.services import vault_log


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "v.db"))
    database.migrate()
    return database


# ---- recording -------------------------------------------------------------


def test_a_write_is_recorded(db) -> None:
    vault_log.record(db, "n1", "/vault/2024/n1.md", "write", "aaa", "bbb")
    assert vault_log.last_write(db, "n1")["hash_after"] == "bbb"


def test_both_hashes_are_kept(db) -> None:
    """By the time anyone resolves a conflict the 'before' is otherwise gone."""
    vault_log.record(db, "n1", "/v/n1.md", "write", "what-we-wrote", "what-we-read")
    entry = vault_log.last_write(db, "n1")
    assert entry["hash_before"] == "what-we-wrote"
    assert entry["hash_after"] == "what-we-read"


def test_the_newest_write_wins(db) -> None:
    vault_log.record(db, "n1", "/v/n1.md", "write", "a", "one")
    vault_log.record(db, "n1", "/v/n1.md", "write", "b", "two")
    assert vault_log.last_write(db, "n1")["hash_after"] == "two"


def test_a_note_with_no_writes_has_none(db) -> None:
    """Distinguishable from "written with no hash", which would be a bug."""
    assert vault_log.last_write(db, "never-written") is None


def test_the_path_is_recorded(db) -> None:
    """Renamed or moved files are the first thing a person needs to see."""
    vault_log.record(db, "n1", "/vault/2024/n1.md", "write", "a", "b")
    assert vault_log.last_write(db, "n1")["path"] == "/vault/2024/n1.md"


def test_the_direction_is_recorded(db) -> None:
    vault_log.record(db, "n1", "/v/n1.md", "read", "a", "b")
    assert vault_log.last_write(db, "n1") is None, "a read is not a write"


def test_a_conflict_is_flagged(db) -> None:
    vault_log.record(db, "n1", "/v/n1.md", "write", "a", "b", conflict=True)
    assert vault_log.last_write(db, "n1")["conflict"] == 1


def test_a_clean_write_is_not_flagged(db) -> None:
    vault_log.record(db, "n1", "/v/n1.md", "write", "a", "b")
    assert vault_log.last_write(db, "n1")["conflict"] == 0


# ---- listing ---------------------------------------------------------------


def test_conflicts_are_listed_newest_first(db) -> None:
    vault_log.record(db, "n1", "/v/n1.md", "write", "a", "b", conflict=True)
    vault_log.record(db, "n2", "/v/n2.md", "write", "a", "b", conflict=True)
    assert [c["note_id"] for c in vault_log.conflicts(db)] == ["n2", "n1"]


def test_a_clean_write_is_not_a_conflict(db) -> None:
    """Otherwise every sync looks like something to resolve."""
    vault_log.record(db, "n1", "/v/n1.md", "write", "a", "b")
    assert vault_log.conflicts(db) == []


def test_the_conflict_list_is_bounded(db) -> None:
    """An endpoint that returns every conflicting file turns itself into a vault
    listing."""
    for i in range(300):
        vault_log.record(db, f"n{i}", "/v/n.md", "write", "a", "b", conflict=True)
    assert len(vault_log.conflicts(db)) <= 200


def test_history_is_ordered_and_bounded(db) -> None:
    for i in range(10):
        vault_log.record(db, "n1", "/v/n1.md", "write", str(i), str(i + 1))
    hist = vault_log.history(db, "n1", limit=3)
    assert len(hist) == 3
    assert [h["hash_after"] for h in hist] == ["10", "9", "8"]


def test_history_of_an_unknown_note_is_empty(db) -> None:
    assert vault_log.history(db, "nope") == []


# ---- it is a log, not a mirror ---------------------------------------------


def test_the_log_is_capped(db) -> None:
    """A second copy of the vault in a place nobody expects to find one is a
    liability, not a feature."""
    for i in range(vault_log.LOG_CAP + 40):
        vault_log.record(db, f"n{i}", "/v/n.md", "write", "a", "b")
    total = db.execute("SELECT COUNT(*) c FROM vault_sync_log").fetchone()["c"]
    assert total <= vault_log.LOG_CAP


def test_pruning_keeps_the_newest(db) -> None:
    """The newest entries are the ones anyone is about to ask about."""
    for i in range(vault_log.LOG_CAP + 10):
        vault_log.record(db, f"n{i}", "/v/n.md", "write", "a", "b")
    newest = db.execute("SELECT note_id FROM vault_sync_log ORDER BY id DESC LIMIT 1").fetchone()
    assert newest["note_id"] == f"n{vault_log.LOG_CAP + 9}"


def test_pruning_below_the_size_is_a_no_op(db) -> None:
    vault_log.record(db, "n1", "/v/n.md", "write", "a", "b")
    assert vault_log.prune(db) == 0
    assert db.execute("SELECT COUNT(*) c FROM vault_sync_log").fetchone()["c"] == 1


# ---- it never stops the thing it is logging --------------------------------


def test_a_logging_failure_does_not_propagate(db, monkeypatch) -> None:
    """A logging failure that propagates turns 'the vault did not sync' into
    'the note was not saved'."""
    from unittest.mock import MagicMock

    broken = MagicMock()
    broken.conn.execute.side_effect = RuntimeError("disk full")
    vault_log.record(broken, "n1", "/v/n1.md", "write", "a", "b")  # must not raise


def test_recording_onto_a_database_without_the_table_does_not_raise(monkeypatch, tmp_path) -> None:
    from unittest.mock import MagicMock

    legacy = MagicMock()
    legacy.conn.execute.side_effect = __import__("sqlite3").OperationalError("no such table")
    vault_log.record(legacy, "n1", "/v/n1.md", "write", "a", "b")  # must not raise

# ---- and the writer actually records ---------------------------------------


def test_syncing_a_note_records_what_it_wrote(tmp_path) -> None:
    """The log is only worth having if the write path writes to it."""
    from fleeting.config import PathsConfig
    from fleeting.services.markdown import sync_note

    db_conn = _fresh_db(tmp_path / "s.db")
    cfg = PathsConfig(vault_dir=str(tmp_path / "vault"))
    sync_note(cfg, _note("n1"), db_conn)
    assert vault_log.last_write(db_conn, "n1") is not None


def test_the_recorded_hash_matches_the_bytes_on_disk(tmp_path) -> None:
    """A hash that does not match the file turns every later check into a false
    conflict."""
    from fleeting.config import PathsConfig
    from fleeting.services.markdown import hash_text, sync_note

    db_conn = _fresh_db(tmp_path / "s.db")
    cfg = PathsConfig(vault_dir=str(tmp_path / "vault"))
    path = sync_note(cfg, _note("n1"), db_conn)
    assert vault_log.last_write(db_conn, "n1")["hash_after"] == hash_text(path.read_text(encoding="utf-8"))


def test_the_first_write_records_no_previous_content(tmp_path) -> None:
    """Absent, not empty-string: an empty file is not what was there before."""
    from fleeting.config import PathsConfig
    from fleeting.services.markdown import sync_note

    db_conn = _fresh_db(tmp_path / "s.db")
    sync_note(PathsConfig(vault_dir=str(tmp_path / "vault")), _note("n1"), db_conn)
    assert vault_log.last_write(db_conn, "n1")["hash_before"] is None


def test_a_second_write_records_what_was_there(tmp_path) -> None:
    from fleeting.config import PathsConfig
    from fleeting.services.markdown import sync_note

    db_conn = _fresh_db(tmp_path / "s.db")
    cfg = PathsConfig(vault_dir=str(tmp_path / "vault"))
    sync_note(cfg, _note("n1", "first"), db_conn)
    sync_note(cfg, _note("n1", "second"), db_conn)
    entry = vault_log.last_write(db_conn, "n1")
    assert entry["hash_before"] is not None
    assert entry["hash_before"] != entry["hash_after"]


def test_syncing_without_a_database_does_not_reach_for_one(tmp_path, monkeypatch) -> None:
    """A helper that goes looking for "the" database on its own is how test data
    ends up in the user's real one — which has happened here before."""
    import fleeting.db as dbmod

    opened: list[str] = []

    class Tripwire:
        def __init__(self, *a, **k):
            opened.append(str(a[0] if a else k))

    monkeypatch.setattr(dbmod, "Database", Tripwire)
    from fleeting.config import PathsConfig
    from fleeting.services.markdown import sync_note

    sync_note(PathsConfig(vault_dir=str(tmp_path / "vault")), _note("n1"))
    assert opened == [], f"a database was constructed without being given one: {opened}"


def _fresh_db(path):
    from fleeting.db import Database

    database = Database(str(path))
    database.migrate()
    return database


def _note(note_id: str = "n1", title: str = "A note") -> dict:
    return {
        "id": note_id,
        "title": title,
        "type": "text",
        "created_at": "2026-01-02T09:00:00+00:00",
        "tags": [],
        "action_items": [],
        "source": {},
    }
