"""#457: a backup index you cannot quietly edit.

#188 writes `<db>.pre-v<N>.bak` before every migration. That leaves a pile of
files with nothing tying them together: no record of what they are, when they
were taken, or whether the one you would restore from is the one that was made.
Restoring the wrong backup is a worse failure than having none.

A plain list of hashes is not enough. An index is a file, and a file can be
edited — someone (or something) rewrites the hash of the backup they replaced and
the index still "verifies". So each entry carries the hash of the entry before
it: `entries[i].prev == sha256(entries[i-1])`. Editing or removing one entry
breaks every hash after it, which is what makes the thing tamper-*evident*
rather than merely tamper-resistant.

Append-only, one JSON object per line, so a partially written index is still a
readable one — a crash mid-write must not destroy the record of the backups that
came before it.

The threat model is honest about itself: this detects *accidental* corruption and
casual editing. Anyone who can write the index can recompute the whole chain, and
this is not a signature. Say so rather than implying more.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleeting.services.backup_index import append, read_all, verify


@pytest.fixture()
def index_path(tmp_path) -> Path:
    return tmp_path / "backups.index.jsonl"


def _fake(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def test_an_empty_index_verifies(index_path: Path) -> None:
    """First run has no index. That is not a broken chain."""
    assert verify(index_path) == []


def test_a_missing_index_file_verifies(index_path: Path) -> None:
    assert verify(index_path) == []


def test_an_appended_entry_is_recorded(index_path: Path, tmp_path) -> None:
    backup = _fake(tmp_path / "fleeting.db.pre-v2.bak", b"x" * 100)
    append(index_path, backup, kind="pre-migration", version=2)
    entries = read_all(index_path)
    assert len(entries) == 1
    assert entries[0]["path"] == backup.name
    assert entries[0]["bytes"] == 100
    assert entries[0]["kind"] == "pre-migration"


def test_each_entry_records_the_hash_of_the_file_it_points_at(index_path, tmp_path) -> None:
    backup = _fake(tmp_path / "a.bak", b"contents")
    append(index_path, backup, kind="manual")
    assert read_all(index_path)[0]["file_sha256"] == sha256(b"contents")


def test_entries_chain(index_path, tmp_path) -> None:
    """The property that makes it tamper-evident: an entry names the hash of the
    one before it, so editing one breaks everything after it."""
    for name in ("a", "b", "c"):
        append(index_path, _fake(tmp_path / f"{name}.bak", name.encode()), kind="manual")
    entries = read_all(index_path)
    assert entries[0]["prev"] == ""
    assert entries[1]["prev"] == entry_hash(entries[0])
    assert entries[2]["prev"] == entry_hash(entries[1])


def test_a_second_index_continues_the_chain(index_path, tmp_path) -> None:
    append(index_path, _fake(tmp_path / "a.bak", b"a"), kind="manual")
    append(index_path, _fake(tmp_path / "b.bak", b"b"), kind="manual")
    entries = read_all(index_path)
    assert entries[1]["prev"] == entry_hash(entries[0])


def test_verify_passes_on_an_untouched_chain(index_path, tmp_path) -> None:
    for name in ("a", "b", "c"):
        append(index_path, _fake(tmp_path / f"{name}.bak", name.encode()), kind="manual")
    assert verify(index_path) == []


def test_editing_an_entry_breaks_the_chain(index_path, tmp_path) -> None:
    """The whole point. Swap a hash for a backup the editor controls and the
    entries after it no longer agree."""
    for name in ("a", "b", "c"):
        append(index_path, _fake(tmp_path / f"{name}.bak", name.encode()), kind="manual")
    lines = index_path.read_text().splitlines()
    edited = json.loads(lines[1])
    edited["bytes"] = 999_999
    lines[1] = json.dumps(edited, sort_keys=True)
    index_path.write_text("\n".join(lines) + "\n")

    problems = verify(index_path)
    assert problems, "an edited entry verified cleanly"
    assert any("b.bak" in p or "entry 2" in p for p in problems), problems


def test_removing_an_entry_breaks_the_chain(index_path, tmp_path) -> None:
    for name in ("a", "b", "c"):
        append(index_path, _fake(tmp_path / f"{name}.bak", name.encode()), kind="manual")
    lines = index_path.read_text().splitlines()
    del lines[1]
    index_path.write_text("\n".join(lines) + "\n")
    assert verify(index_path)


def test_a_backup_that_changed_on_disk_is_reported(index_path, tmp_path) -> None:
    """Different from an edited index: the index is fine and the *file* is not.
    That is what an interrupted write looks like."""
    backup = _fake(tmp_path / "a.bak", b"original")
    append(index_path, backup, kind="manual")
    backup.write_bytes(b"corrupted")
    problems = verify(index_path)
    assert any("a.bak" in p for p in problems), problems


def test_a_missing_backup_is_reported_not_silently_skipped(index_path, tmp_path) -> None:
    backup = _fake(tmp_path / "gone.bak", b"x")
    append(index_path, backup, kind="manual")
    backup.unlink()
    assert any("gone.bak" in p for p in verify(index_path))


def test_a_truncated_final_line_does_not_destroy_the_record(index_path, tmp_path) -> None:
    """A crash mid-append must not make the earlier entries unreadable. JSONL
    rather than one JSON document, for exactly this reason."""
    for name in ("a", "b"):
        append(index_path, _fake(tmp_path / f"{name}.bak", name.encode()), kind="manual")
    with index_path.open("a") as fh:
        fh.write('{"path": "c.bak", "byt')
    entries = read_all(index_path)
    assert [e["path"] for e in entries] == ["a.bak", "b.bak"]


def test_a_corrupt_line_is_reported_rather_than_crashing(index_path, tmp_path) -> None:
    append(index_path, _fake(tmp_path / "a.bak", b"a"), kind="manual")
    with index_path.open("a") as fh:
        fh.write("not json at all\n")
    entries = read_all(index_path)
    assert len(entries) == 1
    assert verify(index_path)


def test_the_index_does_not_grow_without_bound(tmp_path) -> None:
    """A log that outgrows its own usefulness stops being read."""
    from fleeting.services.backup_index import INDEX_CAP

    path = tmp_path / "i.jsonl"
    for i in range(INDEX_CAP + 10):
        append(path, _fake(tmp_path / f"{i}.bak", str(i).encode()), kind="manual")
    assert len(read_all(path)) <= INDEX_CAP


def test_capping_keeps_the_newest(tmp_path) -> None:
    """The backup you would restore from is the most recent one."""
    from fleeting.services.backup_index import INDEX_CAP

    path = tmp_path / "i.jsonl"
    for i in range(INDEX_CAP + 5):
        append(path, _fake(tmp_path / f"{i}.bak", str(i).encode()), kind="manual")
    entries = read_all(path)
    assert entries[-1]["path"] == f"{INDEX_CAP + 4}.bak"


def test_the_entries_are_serialisable(index_path, tmp_path) -> None:
    append(index_path, _fake(tmp_path / "a.bak", b"a"), kind="manual")
    json.dumps(read_all(index_path))


# ---- helpers used by the tests above --------------------------------------


def sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def entry_hash(entry: dict) -> str:
    from fleeting.services.backup_index import _entry_hash

    return _entry_hash(entry)


def entries_hash(entry: dict) -> str:
    return entry["sha256"]

# ---- wired into the #188 pre-migration backups ---------------------------


def test_a_pre_migration_backup_is_recorded(tmp_path) -> None:
    """Otherwise the index is a thing nothing writes to, and the feature is a
    file format rather than a feature."""
    from fleeting.db import BACKUP_KEEP, Database, _backup_before_migration

    db = Database(str(tmp_path / "fleeting.db"))
    db.migrate()
    db.insert_note({"id": "n1", "title": "x", "raw_text": "y"})
    db.commit()

    backup = _backup_before_migration(db.path, 2)
    assert backup is not None
    index = tmp_path / "backups.index.jsonl"
    entries = read_all(index)
    assert [e["path"] for e in entries] == [backup.name]
    assert entries[0]["kind"] == "pre-migration"
    assert entries[0]["version"] == 2
    assert verify(index) == []
    assert BACKUP_KEEP  # the cap is still the caller's business, not a test's


# ---- the endpoint ---------------------------------------------------------


def test_the_endpoint_lists_the_backups(client, tmp_path, monkeypatch) -> None:
    import fleeting.config as fcfg
    from fleeting.db import Database, _backup_index_path

    db = Database(str(tmp_path / "fleeting.db"))
    db.migrate()
    db.insert_note({"id": "n", "title": "x", "raw_text": "y"})
    db.commit()
    db.execute("DELETE FROM schema_version WHERE version > 2")
    db.commit()
    from fleeting.db import _backup_before_migration

    _backup_before_migration(db.path, 2)

    monkey = fcfg.DB_PATH
    fcfg.DB_PATH = str(db.path)
    try:
        body = client.get("/api/backups").json()
    finally:
        fcfg.DB_PATH = monkey
    assert body["backups"], body
    assert body["problems"] == []
    assert _backup_index_path(db.path).exists()
