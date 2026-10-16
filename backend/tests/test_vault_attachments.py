"""#120: attachments in the vault.

Four properties, and the first is the one that makes this worth having:

1. **Links are relative.** A vault is meant to be synced, zipped and moved. An
   absolute `file:///home/you/...` link works on this machine and is broken
   everywhere else — including in the copy somebody emails themselves. So no
   absolute path appears anywhere in the rendered note.
2. **A sensitive note copies nothing.** Same rule as the note file (#26): an
   attachment to a sensitive note is the same leak one directory level down.
3. **Copy, never hard-link, never move.** A hard link would make editing the
   attachment in the vault silently edit the app's copy — two files that look
   independent and are not. Moving would delete the app's only copy, and the
   vault may be a different machine.
4. **Filenames are treated as hostile input**, because they are: an upload
   filename and `Content-Disposition` are both user input, and
   `../../.ssh/authorized_keys` is a real header value.

Idempotence matters too — re-running must not rewrite unchanged files, because a
vault full of touched files breaks every incremental tool the user owns.
"""

from __future__ import annotations

import pytest

from fleeting.services import markdown, vault_attachments


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "a.db"))
    database.migrate()
    return database


@pytest.fixture()
def cfg(tmp_path):
    from fleeting.config import PathsConfig

    return PathsConfig(vault_dir=str(tmp_path / "vault"))


@pytest.fixture()
def files(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    return root


@pytest.fixture()
def note(db):
    db.insert_note(
        {"id": "n1", "title": "A note", "type": "text", "created_at": "2026-01-02T09:00:00+00:00", "tags": []}
    )
    db.commit()
    return db.get_note("n1")


def attach(db, files, note_id="n1", filename="diagram.png", body=b"\x89PNG-ish"):
    path = files / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    db.conn.execute(
        "INSERT INTO note_attachments (id, note_id, filename, path, size, created_at)"
        " VALUES (?, ?, ?, ?, ?, '2026-01-02T09:00:00+00:00')",
        (f"att-{filename}-{len(body)}-{path.stat().st_mtime_ns}", note_id, filename, str(path), len(body)),
    )
    db.commit()
    return path


# ---- relative links -------------------------------------------------------


def test_the_link_is_relative(cfg, db, files, note) -> None:
    """An absolute link works on this machine and is broken everywhere else,
    including in the copy somebody emails themselves."""
    attach(db, files)
    body = markdown.render_note_md(note, [])
    result = vault_attachments.copy_attachments(cfg, db, note, files)
    links = vault_attachments.link_lines(note, result["copied"] and [{"safe": "diagram.png"}] or [])
    assert links, "expected a link line"
    assert not any(line.startswith("![[/") or ":/" in line or ":\\" in line for line in links)
    assert "file://" not in body


def test_the_link_points_into_the_attachments_folder(cfg, db, files, note) -> None:
    attach(db, files)
    links = vault_attachments.link_lines(note, [{"safe": "diagram.png"}])
    assert links[0].startswith("![[attachments/")
    assert "fleeting-n1" in links[0]


def test_no_links_are_rendered_without_attachments(cfg, db, note) -> None:
    assert vault_attachments.link_lines(note, []) == []


# ---- sensitive notes ------------------------------------------------------


def test_a_sensitive_note_copies_nothing(cfg, db, files) -> None:
    """Same rule as the note file (#26): an attachment to a sensitive note is the
    same leak one directory level down."""
    db.insert_note(
        {"id": "s1", "title": "secret", "type": "text", "created_at": "2026-01-02T09:00:00+00:00",
         "tags": [], "sensitive": 1}
    )
    db.commit()
    attach(db, files, note_id="s1", filename="private.png")
    result = vault_attachments.copy_attachments(cfg, db, db.get_note("s1"), files)
    assert result["skipped"] == "sensitive"
    assert result["copied"] == []


def test_the_sensitive_plan_says_so_before_anything_runs(cfg, db, files) -> None:
    db.insert_note(
        {"id": "s1", "title": "secret", "type": "text", "created_at": "2026-01-02T09:00:00+00:00",
         "tags": [], "sensitive": 1}
    )
    db.commit()
    assert vault_attachments.plan(cfg, db, db.get_note("s1"), files)["skipped"] == "sensitive"


# ---- copying --------------------------------------------------------------


def test_an_attachment_is_copied(cfg, db, files, note) -> None:
    attach(db, files)
    result = vault_attachments.copy_attachments(cfg, db, note, files)
    assert result["ok"] is True
    assert result["copied"] == ["diagram.png"]


def test_the_copy_is_a_real_copy_not_a_link(cfg, db, files, note) -> None:
    """A hard link makes editing the attachment in the vault silently edit the
    app's copy — two files that look independent and are not."""
    source = attach(db, files)
    vault_attachments.copy_attachments(cfg, db, note, files)
    target = next((cfg_paths(cfg) / "attachments").rglob("diagram.png"))
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_ino != source.stat().st_ino
    source.write_bytes(b"changed in the app")
    assert target.read_bytes() != source.read_bytes()


def test_the_original_is_not_moved(cfg, db, files, note) -> None:
    """The vault may be a different machine, and the app's copy is the only one
    there."""
    source = attach(db, files)
    vault_attachments.copy_attachments(cfg, db, note, files)
    assert source.exists()


def test_copying_twice_copies_nothing_the_second_time(cfg, db, files, note) -> None:
    """A vault full of touched files breaks every incremental tool the user
    owns."""
    attach(db, files)
    vault_attachments.copy_attachments(cfg, db, note, files)
    second = vault_attachments.copy_attachments(cfg, db, note, files)
    assert second["copied"] == []
    assert second["counts"]["present"] == 1


def test_a_changed_attachment_is_copied_again(cfg, db, files, note) -> None:
    attach(db, files, body=b"first")
    vault_attachments.copy_attachments(cfg, db, note, files)
    attach(db, files, body=b"second and longer")
    assert vault_attachments.copy_attachments(cfg, db, note, files)["copied"] == ["diagram.png"]


def cfg_paths(cfg):
    """The vault root, as a `Path`. Repeated often enough to be worth a name."""
    from pathlib import Path

    return Path(cfg.vault_dir).expanduser()


# ---- missing files --------------------------------------------------------


def test_a_missing_attachment_is_reported_not_fatal(cfg, db, note) -> None:
    """The row outlives the file. A hard error would fail the whole sync for one
    file the user deleted by hand."""
    db.conn.execute(
        "INSERT INTO note_attachments (id, note_id, filename, path, size, created_at)"
        " VALUES ('a1', 'n1', 'gone.png', '/tmp/definitely-not-here/gone.png', 5, '2026-01-02T00:00:00+00:00')"
    )
    db.commit()
    result = vault_attachments.copy_attachments(cfg, db, note, tmp_path_for(db))
    assert result["ok"] is True
    assert result["counts"]["missing"] == 1


def tmp_path_for(db):
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())


# ---- hostile filenames ----------------------------------------------------


@pytest.mark.parametrize(
    "hostile,expected",
    [
        ("../../../.ssh/authorized_keys", "authorized-keys"),
        ("/etc/passwd", "passwd"),
        ("My Photo (1).JPG", "my-photo-1.jpg"),
        ("..", "file"),
        ("", "file"),
        # The emoji slugifies to nothing, so the stem falls back rather than
        # becoming the extension.
        ("🎉.png", "file.png"),
    ],
)
def test_a_hostile_filename_is_made_safe(hostile, expected) -> None:
    """An upload filename and `Content-Disposition` are both user input, and a
    traversal is a real header value."""
    assert vault_attachments.safe_name(hostile) == expected


def test_a_hostile_filename_cannot_escape_the_vault(cfg, db, files, note) -> None:
    attach(db, files, filename="../../escape.png")
    vault_attachments.copy_attachments(cfg, db, note, files)
    copies = list((cfg_paths(cfg) / "attachments").rglob("*.png"))
    assert copies
    assert all(c.parent.parent == cfg_paths(cfg) / "attachments" for c in copies)


# ---- the plan -------------------------------------------------------------


def test_the_plan_counts_before_anything_runs(cfg, db, files, note) -> None:
    """A sync that copies a few hundred files without saying so is a sync you
    cannot undo cheaply."""
    attach(db, files)
    detail = vault_attachments.plan(cfg, db, note, files)
    assert detail["counts"] == {"copy": 1, "present": 0, "missing": 0}
    assert not (cfg_paths(cfg) / "attachments").exists()


def test_the_plan_names_the_target_folder(cfg, db, files, note) -> None:
    attach(db, files)
    assert vault_attachments.plan(cfg, db, note, files)["folder"].endswith("attachments/" + note_stem())


def note_stem() -> str:
    """The stem attachments are filed under — derived, not hard-coded, so a change
    to the filename scheme moves both sides at once."""
    from pathlib import Path

    from fleeting.services.markdown import note_filename

    return Path(note_filename({"id": "n1", "created_at": "2026-01-02T09:00:00+00:00"})).stem


# ---- removal --------------------------------------------------------------


def test_trashing_a_note_removes_its_attachment_folder(cfg, db, files, note) -> None:
    """The vault copy of a deleted note's attachment is the same leak as the
    note file staying behind."""
    attach(db, files)
    vault_attachments.copy_attachments(cfg, db, note, files)
    assert vault_attachments.remove_attachments(cfg, note)
    assert not (cfg_paths(cfg) / "attachments" / note_stem()).exists()


def test_removing_a_folder_that_is_not_there_is_fine(cfg, note) -> None:
    assert vault_attachments.remove_attachments(cfg, note) == []


def test_removing_the_note_takes_the_attachments_with_it(cfg, db, files, note) -> None:
    """Through `remove_note`, not `remove_attachments`.

    Testing the helper proved the helper works. It said nothing about whether the
    note's own removal path calls it — and mutation checking found that it did
    not, so trashing a note left its images sitting in the vault.
    """
    attach(db, files)
    vault_attachments.copy_attachments(cfg, db, note, files)
    assert (cfg_paths(cfg) / "attachments" / note_stem()).exists()

    markdown.remove_note(cfg, note)

    assert not (cfg_paths(cfg) / "attachments" / note_stem()).exists()


def test_the_note_file_is_still_removed_too(cfg, db, files, note) -> None:
    attach(db, files)
    markdown.sync_note(cfg, note, db)
    vault_attachments.copy_attachments(cfg, db, note, files)
    path = markdown.vault_path_for(cfg, note)
    assert path.exists()
    markdown.remove_note(cfg, note)
    assert not path.exists()