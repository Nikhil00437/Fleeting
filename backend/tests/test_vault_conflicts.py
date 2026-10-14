"""#113: resolving a vault file that disagrees with the database row.

**There is no text merge, and the tests say why.** A three-way merge needs the
common ancestor — the content before either side changed — and keeping that means
storing a second copy of every note's text somewhere that is not the note. The
sync log keeps a *hash*, which is enough to tell the sides apart and not enough to
blend them. So the tests pin the three real choices and pin that importing the
file makes a **new note** rather than overwriting the row: the file never carried
the tags, tasks and summary the app maintains, so overwriting destroys them.

**Resolving must actually resolve.** If a resolution writes the file but logs
nothing, the next comparison still sees a file it does not recognise and the
conflict reappears — which is how "resolve" becomes a button that does nothing.
That specific regression is pinned.

**`keep_file` never overwrites the original note.** Two notes is a thing you can
undo; a half-and-half note is not.
"""

from __future__ import annotations


import pytest

from fleeting.services import markdown, vault_conflicts


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "c.db"))
    database.migrate()
    return database


@pytest.fixture()
def cfg(tmp_path):
    from fleeting.config import PathsConfig

    return PathsConfig(vault_dir=str(tmp_path / "vault"))


def note(note_id: str = "n1", title: str = "A note", **extra) -> dict:
    return {
        "id": note_id,
        "title": title,
        "type": "text",
        "created_at": "2026-01-02T09:00:00+00:00",
        "tags": ["one"],
        "action_items": [],
        "summary": "the app's summary",
        "source": {},
        **extra,
    }


@pytest.fixture()
def conflicted(cfg, db):
    """A note synced, then edited in the vault — the conflict case.

    It has to be in the database: `resolve` reads the row, and a fixture that
    only wrote a file is testing a conflict that does not exist.
    """
    n = note()
    db.insert_note(n)
    db.commit()
    markdown.sync_note(cfg, db.get_note("n1"), db)
    path = markdown.vault_path_for(cfg, n)
    path.write_text(
        "---\nid: n1\ntype: text\n---\n\n# Edited in Obsidian\n\nsomething worth keeping\n",
        encoding="utf-8",
    )
    return {"note": n, "path": path}


# ---- detection -------------------------------------------------------------


def test_an_edited_file_is_detected(conflicted, cfg, db) -> None:
    found = vault_conflicts.detect(cfg, db)
    assert [c["note_id"] for c in found] == ["n1"]


def test_detection_reports_where_the_file_is(conflicted, cfg, db) -> None:
    """A conflict you cannot find is a conflict you cannot resolve."""
    assert vault_conflicts.detect(cfg, db)[0]["path"].endswith(".md")


def test_a_clean_vault_has_no_conflicts(cfg, db) -> None:
    db.insert_note(note())
    db.commit()
    markdown.sync_note(cfg, db.get_note("n1"), db)
    assert vault_conflicts.detect(cfg, db) == []


def test_a_resolved_conflict_is_not_still_listed(conflicted, cfg, db) -> None:
    """Re-derived, not read from the log. A log that has never been pruned shows
    last week's resolution as still open, and a list nobody can clear is a list
    people stop reading."""
    vault_conflicts.resolve(cfg, db, "n1", "keep_db")
    assert vault_conflicts.detect(cfg, db) == []


def test_detection_is_bounded(cfg, db) -> None:
    """Scanning a hundred thousand notes should not hang the settings page."""
    for i in range(20):
        db.insert_note(note(f"n{i}"))
        db.commit()
        markdown.sync_note(cfg, db.get_note(f"n{i}"), db)
    assert len(vault_conflicts.detect(cfg, db, limit=5)) <= 5


# ---- keep_db ---------------------------------------------------------------


def test_keep_db_rewrites_the_file_from_the_database(conflicted, cfg, db) -> None:
    vault_conflicts.resolve(cfg, db, "n1", "keep_db")
    assert "the app's summary" in conflicted["path"].read_text(encoding="utf-8")


def test_keep_db_discards_the_file_edit(conflicted, cfg, db) -> None:
    vault_conflicts.resolve(cfg, db, "n1", "keep_db")
    assert "Edited in Obsidian" not in conflicted["path"].read_text(encoding="utf-8")


def test_keep_db_creates_no_note(conflicted, cfg, db) -> None:
    vault_conflicts.resolve(cfg, db, "n1", "keep_db")
    assert len(db.list_notes(limit=10)) == 1


# ---- keep_file -------------------------------------------------------------


def test_keep_file_keeps_the_file_untouched(conflicted, cfg, db) -> None:
    vault_conflicts.resolve(cfg, db, "n1", "keep_file")
    assert "Edited in Obsidian" in conflicted["path"].read_text(encoding="utf-8")


def test_keep_file_imports_the_file_as_a_new_note(conflicted, cfg, db) -> None:
    result = vault_conflicts.resolve(cfg, db, "n1", "keep_file")
    created = db.get_note(result["created_note_id"])
    assert created is not None
    # `parse_note_md` puts the first paragraph in `summary` and leaves `raw_text`
    # empty, so the words land there.
    assert "Edited in Obsidian" in created["title"]
    assert "something worth keeping" in created["summary"]


def test_keep_file_does_not_overwrite_the_original(conflicted, cfg, db) -> None:
    """The file never carried the tags, tasks and summary the app maintains."""
    vault_conflicts.resolve(cfg, db, "n1", "keep_file")
    original = db.get_note("n1")
    assert original["tags"] == ["one"]
    assert original["summary"] == "the app's summary"


def test_the_imported_note_says_where_it_came_from(conflicted, cfg, db) -> None:
    result = vault_conflicts.resolve(cfg, db, "n1", "keep_file")
    assert db.get_note(result["created_note_id"])["source"].get("from_vault") is True


# ---- keep_both -------------------------------------------------------------


def test_keep_both_does_both(conflicted, cfg, db) -> None:
    result = vault_conflicts.resolve(cfg, db, "n1", "keep_both")
    assert result["file_updated"] is True
    assert result["created_note_id"] is not None
    assert "Edited in Obsidian" in db.get_note(result["created_note_id"])["title"]


# ---- resolving actually resolves ------------------------------------------


def test_every_resolution_clears_the_conflict(conflicted, cfg, db) -> None:
    """If a resolution writes the file but logs nothing, the next comparison
    still sees a file it does not recognise and the conflict reappears — which is
    how 'resolve' becomes a button that does nothing."""
    vault_conflicts.resolve(cfg, db, "n1", "keep_both")
    assert vault_conflicts.detect(cfg, db) == []


def test_a_resolution_is_logged(conflicted, cfg, db) -> None:
    """Counted, not merely present.

    `last_write(db, "n1") is not None` passes on the *fixture's* sync write, so
    it says nothing about the resolution — and the conflict would still clear
    afterwards with a completely silent log, because a file with no recorded
    hash classifies as `rewrite` rather than `conflict`.
    """
    from fleeting.services import vault_log

    before = len(vault_log.history(db, "n1", limit=100))
    vault_conflicts.resolve(cfg, db, "n1", "keep_db")
    # Two entries: the resolution, then the write `sync_note` performs. What
    # matters is that the conflict stays on the record.
    after = vault_log.history(db, "n1", limit=100)
    assert len(after) == before + 2
    assert any(e["direction"].startswith("resolve:") and e["conflict"] == 1 for e in after)


def test_a_silent_log_still_leaves_the_conflict_resolved(conflicted, cfg, db, monkeypatch) -> None:
    """The failure the log prevents, stated directly.

    Without a resolution entry the file is written correctly, the conflict
    disappears — and conflict *detection* is then blind to that note forever,
    because it has no hash to compare against. A green checkmark on the wrong
    work.
    """
    from fleeting.services import vault_conflicts, vault_log

    before = len(vault_log.history(db, "n1", limit=100))
    # `resolve` binds `record` into its own namespace, so the module attribute
    # is not the thing to patch.
    monkeypatch.setattr(vault_conflicts, "record", lambda *a, **k: None)
    def write_but_do_not_log(cfg, note, db=None):
        """The exact bug: the file is written correctly and nothing is recorded."""
        path = markdown.vault_path_for(cfg, note)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown.render_note_md(note), encoding="utf-8")
        return path

    monkeypatch.setattr(vault_conflicts, "sync_note", write_but_do_not_log)
    vault_conflicts.resolve(cfg, db, "n1", "keep_db")
    # The conflict is gone…
    assert vault_conflicts.detect(cfg, db) == []
    # …and the reason is that the note is now unrecognisable, not that it was
    # resolved. This is the state the log exists to prevent.
    assert len(vault_log.history(db, "n1", limit=100)) == before


def test_a_resolution_is_audited(conflicted, cfg, db) -> None:
    """Six months later, with no memory of enabling anything."""
    vault_conflicts.resolve(cfg, db, "n1", "keep_db")
    entries = db.execute("SELECT * FROM audit_log WHERE action = 'vault.resolve'").fetchall()
    assert len(entries) == 1


# ---- refusing nonsense -----------------------------------------------------


def test_an_unknown_resolution_is_refused(conflicted, cfg, db) -> None:
    with pytest.raises(ValueError):
        vault_conflicts.resolve(cfg, db, "n1", "make_it_nice")


def test_resolving_a_note_that_does_not_exist(conflicted, cfg, db) -> None:
    with pytest.raises(LookupError):
        vault_conflicts.resolve(cfg, db, "nope", "keep_db")


def test_resolving_a_note_that_is_not_in_conflict_is_refused(cfg, db) -> None:
    """Otherwise 'resolve' silently does nothing, which is the same as the bug
    above and twice as confusing."""
    n = note("n2")
    db.insert_note(n)
    db.commit()
    markdown.sync_note(cfg, db.get_note("n2"), db)
    with pytest.raises(LookupError):
        vault_conflicts.resolve(cfg, db, "n2", "keep_db")


def test_every_resolution_is_one_of_the_three() -> None:
    assert vault_conflicts.RESOLUTIONS == ("keep_db", "keep_file", "keep_both")


# ---- the endpoints ---------------------------------------------------------


def test_the_conflicts_endpoint(client) -> None:
    body = client.get("/api/vault/conflicts").json()
    assert "conflicts" in body


def test_resolving_through_the_api(client) -> None:
    from conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "will be edited"}).json()["id"]
    wait_done(client, note_id)
    db = client.app.state.st.db
    path = markdown.vault_path_for(client.app.state.st.cfg.paths, db.get_note(note_id))
    path.write_text("---\nid: x\n---\n\n# Hand edited\n", encoding="utf-8")

    listed = client.get("/api/vault/conflicts").json()["conflicts"]
    assert listed
    r = client.post(f"/api/vault/conflicts/{note_id}", json={"resolution": "keep_db"})
    assert r.status_code == 200, r.text
    assert client.get("/api/vault/conflicts").json()["conflicts"] == []


def test_resolving_a_clean_note_through_the_api_is_404(client) -> None:
    from conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "clean note"}).json()["id"]
    wait_done(client, note_id)
    assert client.post(f"/api/vault/conflicts/{note_id}", json={"resolution": "keep_db"}).status_code == 404


def test_an_unknown_resolution_through_the_api_is_400(client) -> None:
    assert client.post("/api/vault/conflicts/nope", json={"resolution": "wat"}).status_code == 400