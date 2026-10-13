"""#137: what is stored per category, and how big.

The companion to `/api/offline`. That answers "what leaves the machine"; this
answers "what is on it, and which of it would hurt to lose". You cannot protect
data you do not know you have, and the numbers people usually guess at are wrong
— the audio directory or the vault export is routinely larger than the notes.

Three properties this is built around:

- **Bytes come from the filesystem, not from summing column lengths.** A blob, an
  audio file and a row of text are not comparable, and `length()` on a text
  column under-reports by the page and row overhead SQLite actually spends.
- **A missing directory is zero, not an error.** Before the first capture there
  is no audio directory; that is not a failure, and a first-run inventory page
  that 500s is a first-run inventory page nobody sees.
- **Categories are ordered by size.** The point is to find the big one, and a
  list sorted by name makes that a scanning job.

No path outside the configured directories is ever read: this reports on the
user's own layout, and walking anything else would be a different feature with a
much worse failure mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services.inventory import inventory, dir_size


@pytest.fixture()
def db(tmp_path) -> Database:
    from fleeting.db import Database as _D

    d = _D(str(tmp_path / "inv.db"))
    d.migrate()
    return d


def cfg(tmp_path) -> Config:
    c = Config()
    c.paths.vault_dir = str(tmp_path / "vault")
    return c


def _write(path: Path, n: int = 10) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * n)


# ---- sizes ----------------------------------------------------------------


def test_dir_size_sums_the_tree(tmp_path) -> None:
    _write(tmp_path / "a", 10)
    _write(tmp_path / "sub" / "b", 20)
    assert dir_size(tmp_path) == 30


def test_dir_size_of_a_missing_directory_is_zero(tmp_path) -> None:
    assert dir_size(tmp_path / "never-created") == 0


def test_dir_size_of_a_file_is_that_file(tmp_path) -> None:
    _write(tmp_path / "one", 7)
    assert dir_size(tmp_path / "one") == 7


def test_dir_size_ignores_nothing_it_can_read(tmp_path) -> None:
    """A file it cannot stat must not take the whole page down."""
    _write(tmp_path / "a", 10)
    _write(tmp_path / "b", 10)
    (tmp_path / "b").chmod(0o000)
    try:
        assert dir_size(tmp_path) == 20
    finally:
        (tmp_path / "b").chmod(0o644)


# ---- the inventory --------------------------------------------------------


def test_it_reports_the_tables_and_the_directories(tmp_path, db) -> None:
    out = inventory(db, cfg(tmp_path))
    names = {c["name"] for c in out["categories"]}
    assert {"notes", "tasks", "activity"} <= names
    assert any(c["kind"] == "files" for c in out["categories"])


def test_each_category_carries_a_count_and_a_size(tmp_path, db) -> None:
    for c in inventory(db, cfg(tmp_path))["categories"]:
        assert "name" in c and "count" in c and "bytes" in c
        assert c["bytes"] >= 0 and c["count"] >= 0


def test_categories_are_ordered_by_size_largest_first(tmp_path, db) -> None:
    """The point is to find the big one; sorted by name it is a scanning job."""
    sizes = [c["bytes"] for c in inventory(db, cfg(tmp_path))["categories"]]
    assert sizes == sorted(sizes, reverse=True)


def test_a_category_the_user_cannot_delete_is_labelled(tmp_path, db) -> None:
    """Notes come from a capture; the database file does not go when you delete
    a note. Merging those into one number is how an inventory misleads."""
    out = {c["name"]: c for c in inventory(db, cfg(tmp_path))["categories"]}
    assert out["notes"]["deletable"] is True
    assert out["database"]["deletable"] is False
    assert out["log"]["deletable"] is False, "the log is not a note you can delete"


def test_a_fresh_install_reports_zero_rather_than_failing(tmp_path, db) -> None:
    """Before the first capture there is no audio directory. That is the common
    case, not an error."""
    out = inventory(db, cfg(tmp_path))
    assert out["total_bytes"] >= 0
    assert out["categories"]


def test_note_count_reflects_the_database(tmp_path, db) -> None:
    db.insert_note({"id": "n1", "title": "one", "raw_text": "body"})
    db.insert_note({"id": "n2", "title": "two", "raw_text": "body"})
    db.commit()
    out = {c["name"]: c for c in inventory(db, cfg(tmp_path))["categories"]}
    assert out["notes"]["count"] == 2


def test_soft_deleted_notes_are_counted_separately(tmp_path, db) -> None:
    """Trash is still on disk. Counting it as if it were gone is how someone
    deletes a note and finds it in the disk usage the next day."""
    db.insert_note({"id": "n1", "title": "live", "raw_text": "b"})
    db.insert_note({"id": "n2", "title": "trashed", "raw_text": "b"})
    db.update_note("n2", {"trashed_at": "2026-01-01T00:00:00+00:00"})
    db.commit()
    out = {c["name"]: c for c in inventory(db, cfg(tmp_path))["categories"]}
    assert out["notes"]["count"] == 1
    assert out["notes"]["count_deleted"] == 1


def test_the_report_is_serialisable(tmp_path, db) -> None:
    json.dumps(inventory(db, cfg(tmp_path)))


def test_the_total_is_the_sum_of_the_categories(tmp_path, db) -> None:
    """A total that disagrees with its own parts is worse than no total."""
    out = inventory(db, cfg(tmp_path))
    assert out["total_bytes"] == sum(c["bytes"] for c in out["categories"])


def test_it_does_not_walk_anything_outside_the_configured_paths(tmp_path, db) -> None:
    """A secret directory next to the vault must not appear. This reports on the
    user's own layout; reading anything else would be a different feature with a
    much worse failure mode."""
    outside = tmp_path / "private"
    _write(outside / "secret", 5_000)
    out = inventory(db, cfg(tmp_path))
    assert all("private" not in json.dumps(c) for c in out["categories"])

# ---- the endpoint ---------------------------------------------------------


def test_the_endpoint_answers(client) -> None:
    body = client.get("/api/inventory").json()
    assert set(body) == {"categories", "total_bytes"}
    assert body["categories"]


def test_every_category_is_labelled_with_where_it_lives(client) -> None:
    """A size with no path is not actionable — the question this page answers is
    always "which directory do I delete"."""
    for c in client.get("/api/inventory").json()["categories"]:
        assert "where" in c and "deletable" in c


# ---- gaps found by the first mutation pass -------------------------------


def test_the_database_reports_a_real_size(tmp_path, db) -> None:
    """Zero was what a mutation reported, and nothing here noticed — a page that
    says "your database is 0 bytes" is worse than no page."""
    out = {c["name"]: c for c in inventory(db, cfg(tmp_path))["categories"]}
    assert out["database"]["bytes"] > 0


def test_the_vault_is_actually_measured(tmp_path, db) -> None:
    from fleeting.services.inventory import dir_size as _ds

    vault = tmp_path / "vault"
    _write(vault / "note.md", 5_000)
    out = {c["name"]: c for c in inventory(db, cfg(tmp_path))["categories"]}
    assert out["vault"]["bytes"] == _ds(vault) == 5_000


def test_the_total_counts_more_than_one_category(tmp_path, db) -> None:
    """`sum` and `max` agree when only one category is non-empty, which is what
    an unseeded database looks like."""
    _write(tmp_path / "vault" / "a.md", 3_000)
    _write(tmp_path / "audio" / "b.webm", 7_000)
    out = inventory(db, cfg(tmp_path))
    non_zero = [c for c in out["categories"] if c["bytes"]]
    assert len(non_zero) >= 2, [c["name"] for c in non_zero]
    assert out["total_bytes"] == sum(c["bytes"] for c in out["categories"])


def test_an_unreadable_directory_is_skipped_not_fatal(tmp_path, db) -> None:
    """A *file* cannot be made unstat-able with chmod — stat needs only the
    parent's read permission. An unreadable directory is the case that really
    happens, and it must cost that subtree rather than the whole page."""
    root = tmp_path / "tree"
    _write(root / "ok.md", 1_000)
    locked = root / "locked"
    _write(locked / "inside.md", 5_000)
    locked.chmod(0o000)
    try:
        assert dir_size(root) == 1_000
    finally:
        locked.chmod(0o755)
