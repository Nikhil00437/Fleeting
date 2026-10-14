"""#118: the vault health report.

Four questions, each with a different failure behind it, and one property that
overrides all of them: **the report never repairs anything.** A health check that
silently deleted orphans would be a second, un-audited destructive path — and
"clean up my vault" is exactly the request that goes wrong while nobody is
looking. The response says so in words too.

The subtlest of the four is trashed notes. Their files are removed *on purpose*, so
counting them as "notes with no file" produces a permanent, unfixable warning that
teaches the user to ignore the report.

Broken links are pinned **conservatively**: a link counts only when no file of
that name exists anywhere in the vault. Obsidian resolves by shortest path, by
full path and by heading, and duplicating those rules here produces warnings people
learn to ignore — which is the same as no warning.
"""

from __future__ import annotations

import pytest

from fleeting.services import markdown, vault_health


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "h.db"))
    database.migrate()
    return database


@pytest.fixture()
def cfg(tmp_path):
    from fleeting.config import PathsConfig

    return PathsConfig(vault_dir=str(tmp_path / "vault"))


def add(db, note_id: str, title: str = "A note", **extra) -> dict:
    note = {
        "id": note_id,
        "title": title,
        "type": "text",
        "created_at": "2026-01-02T09:00:00+00:00",
        "tags": [],
        "action_items": [],
        "source": {},
        **extra,
    }
    db.insert_note(note)
    db.commit()
    return db.get_note(note_id)


def write_vault(cfg, relpath: str, text: str):
    path = markdown.expand_path(cfg.vault_dir) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---- the happy path --------------------------------------------------------


def test_a_synced_vault_is_healthy(cfg, db) -> None:
    add(db, "n1")
    markdown.sync_note(cfg, db.get_note("n1"), db)
    report = vault_health.scan(cfg, db)
    assert report["healthy"] is True


def test_the_vault_root_is_reported(cfg, db) -> None:
    assert vault_health.scan(cfg, db)["vault"].endswith("vault")


def test_the_report_says_it_repairs_nothing(cfg, db) -> None:
    """A health check that deletes orphans is a second, un-audited destructive
    path — and 'clean up my vault' is exactly the request that goes wrong while
    nobody is looking."""
    assert "never deletes" in vault_health.scan(cfg, db)["repairs"]


# ---- notes with no file -------------------------------------------------


def test_a_note_whose_file_is_missing_is_reported(cfg, db) -> None:
    add(db, "n1")
    report = vault_health.scan(cfg, db)
    assert report["notes_without_file"] == 1
    assert report["healthy"] is False


def test_the_missing_file_sample_names_the_note(cfg, db) -> None:
    add(db, "n1", "Something I wrote")
    sample = vault_health.scan(cfg, db)["notes_without_file_sample"][0]
    assert sample["id"] == "n1"
    assert sample["title"] == "Something I wrote"


def test_a_trashed_note_is_not_a_missing_file(cfg, db) -> None:
    """Its file was removed on purpose. Counting it produces a permanent,
    unfixable warning that teaches the user to ignore the report."""
    add(db, "n1", trashed_at="2026-02-01T00:00:00+00:00")
    assert vault_health.scan(cfg, db)["notes_without_file"] == 0


# ---- orphans --------------------------------------------------------------


def test_a_hand_written_file_is_an_orphan(cfg, db) -> None:
    write_vault(cfg, "2026/2026-01-02 mine.md", "# not written by the app\n")
    report = vault_health.scan(cfg, db)
    assert report["orphan_files"] == 1
    assert report["orphan_files_sample"][0]["stem"] == "2026-01-02 mine"


def test_an_orphans_path_is_relative_to_the_vault(cfg, db) -> None:
    """An absolute path tells you nothing you can act on from another machine."""
    write_vault(cfg, "2026/x.md", "# mine\n")
    assert vault_health.scan(cfg, db)["orphan_files_sample"][0]["path"] == "2026/x.md"


def test_a_file_the_app_claims_is_not_an_orphan(cfg, db) -> None:
    add(db, "n1")
    markdown.sync_note(cfg, db.get_note("n1"), db)
    assert vault_health.scan(cfg, db)["orphan_files"] == 0


def test_a_file_with_our_id_is_not_an_orphan(cfg, db) -> None:
    """Even at a path the app would not have chosen — the `id:` is the stronger
    claim."""
    write_vault(cfg, "Moved/somewhere-else.md", "---\nid: n1\ntype: text\n---\n\n# moved\n")
    add(db, "n1")
    assert vault_health.scan(cfg, db)["orphan_files"] == 0


def test_editor_folders_are_not_orphans(cfg, db) -> None:
    """.obsidian and .git are not the user's files."""
    write_vault(cfg, ".obsidian/workspace.md", "{}\n")
    write_vault(cfg, ".git/notes.md", "git internals\n")
    assert vault_health.scan(cfg, db)["orphan_files"] == 0


# ---- frontmatter ----------------------------------------------------------


def test_a_file_without_frontmatter_is_reported(cfg, db) -> None:
    write_vault(cfg, "plain.md", "# just a heading\n")
    report = vault_health.scan(cfg, db)
    assert report["files_without_frontmatter"] == 1
    assert report["healthy"] is False


def test_the_cost_is_stated_by_naming_it(cfg, db) -> None:
    """Without an `id:` the file cannot be imported back. That is the actual
    cost, and it is why this is a warning rather than a curiosity."""
    write_vault(cfg, "plain.md", "# just a heading\n")
    assert vault_health.scan(cfg, db)["files_without_frontmatter_sample"][0]["path"] == "plain.md"


def test_an_app_written_file_has_frontmatter(cfg, db) -> None:
    add(db, "n1")
    markdown.sync_note(cfg, db.get_note("n1"), db)
    assert vault_health.scan(cfg, db)["files_without_frontmatter"] == 0


# ---- broken links ---------------------------------------------------------


def test_a_link_to_a_missing_note_is_broken(cfg, db) -> None:
    write_vault(cfg, "a.md", "---\nid: a\n---\n\nSee [[nowhere]].\n")
    report = vault_health.scan(cfg, db)
    assert report["broken_links"] == 1
    assert report["broken_links_sample"][0]["target"] == "nowhere"


def test_a_link_to_an_existing_file_is_fine(cfg, db) -> None:
    write_vault(cfg, "a.md", "---\nid: a\n---\n\nSee [[b]].\n")
    write_vault(cfg, "b.md", "---\nid: b\n---\n\n# b\n")
    assert vault_health.scan(cfg, db)["broken_links"] == 0


def test_a_link_with_an_alias_is_resolved_by_its_target(cfg, db) -> None:
    """`[[b|the alias]]` links to `b`.

    The regex stops at the pipe, so the alias never reaches the lookup at all —
    which is why removing the `target in by_stem` guard is an equivalent mutant
    here rather than a gap.
    """
    write_vault(cfg, "a.md", "---\nid: a\n---\n\nSee [[b|the alias]].\n")
    write_vault(cfg, "b.md", "---\nid: b\n---\n\n# b\n")
    assert vault_health.scan(cfg, db)["broken_links"] == 0


def test_a_file_at_the_expected_path_is_ours_even_without_frontmatter(cfg, db) -> None:
    """The path is a claim too, and a stronger one than a missing `id:`.

    A file whose frontmatter was hand-stripped is still the note's file. Calling
    it an orphan invites the user to delete a note they only meant to tidy.
    """
    add(db, "n1")
    expected = markdown.vault_path_for(cfg, db.get_note("n1"))
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_text("# the note, frontmatter stripped by hand\n", encoding="utf-8")
    report = vault_health.scan(cfg, db)
    assert report["orphan_files"] == 0
    assert report["notes_without_file"] == 0
    assert report["files_without_frontmatter"] == 1


def test_the_broken_link_sample_is_bounded(cfg, db) -> None:
    """A report that lists every broken link in a five-year vault hangs the
    settings page."""
    links = "\n".join(f"See [[gone-{i}]]." for i in range(vault_health.MAX_SAMPLES * 2))
    write_vault(cfg, "a.md", f"---\nid: a\n---\n\n{links}\n")
    report = vault_health.scan(cfg, db)
    assert len(report["broken_links_sample"]) == vault_health.MAX_SAMPLES


def test_a_link_with_a_heading_is_resolved_by_its_target(cfg, db) -> None:
    write_vault(cfg, "a.md", "---\nid: a\n---\n\nSee [[b#a section]].\n")
    write_vault(cfg, "b.md", "---\nid: b\n---\n\n# b\n")
    assert vault_health.scan(cfg, db)["broken_links"] == 0


def test_a_path_link_is_resolved_by_its_filename(cfg, db) -> None:
    """Obsidian resolves by shortest path and by full path; both count as found.
    Duplicating its rules here produces warnings people learn to ignore, which is
    the same as no warning."""
    write_vault(cfg, "a.md", "---\nid: a\n---\n\nSee [[2026/b]].\n")
    write_vault(cfg, "2026/b.md", "---\nid: b\n---\n\n# b\n")
    assert vault_health.scan(cfg, db)["broken_links"] == 0


def test_the_broken_sample_says_where_it_came_from(cfg, db) -> None:
    write_vault(cfg, "a.md", "---\nid: a\n---\n\nSee [[nowhere]].\n")
    assert vault_health.scan(cfg, db)["broken_links_sample"][0]["from"] == "a"


# ---- bounded and honest ---------------------------------------------------


def test_the_report_admits_when_it_stopped_early(cfg, db, monkeypatch) -> None:
    """A report that silently covers the first N and reports `files: N` is worse
    than one that says it stopped."""
    monkeypatch.setattr(vault_health, "MAX_FILES", 1)
    for i in range(5):
        write_vault(cfg, f"f{i}.md", "---\nid: n\n---\n\n# x\n")
    assert vault_health.scan(cfg, db)["truncated"] is True


def test_a_small_vault_is_not_truncated(cfg, db) -> None:
    assert vault_health.scan(cfg, db)["truncated"] is False


def test_a_missing_vault_directory_is_reported_not_fatal(cfg, db) -> None:
    report = vault_health.scan(cfg, db)
    assert report["exists"] is False
    assert report["files"] == 0


def test_a_database_failure_does_not_take_the_report_down(cfg, monkeypatch) -> None:
    """A health page that 500s tells you nothing about your vault, which is the
    one thing it exists to tell you."""
    from unittest.mock import MagicMock

    broken = MagicMock()
    broken.list_notes.side_effect = RuntimeError("database locked")
    report = vault_health.scan(cfg, broken)
    assert report["notes"] == 0
    assert "files" in report


# ---- the endpoint ---------------------------------------------------------


def test_the_endpoint_reports_health(client) -> None:
    body = client.get("/api/vault/health").json()
    assert {"healthy", "files", "notes", "orphan_files", "broken_links"} <= set(body)


def test_the_endpoint_works_on_a_synced_note(client) -> None:
    from conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "a healthy note"}).json()["id"]
    wait_done(client, note_id)
    assert client.get("/api/vault/health").json()["orphan_files"] == 0