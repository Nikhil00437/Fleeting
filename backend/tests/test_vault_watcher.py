"""Tests for VaultSyncRegistry and VaultWatcher."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from watchdog.events import FileMovedEvent

from fleeting.config import PathsConfig
from fleeting.services.markdown import render_note_md, sync_note, vault_path_for
from fleeting.services.vault_watcher import (
    VaultSyncRegistry,
    VaultWatcher,
    _VaultEventHandler,
    sync_registry,
)


def test_registry_register_and_is_echo(tmp_path: Path):
    reg = VaultSyncRegistry()
    note_path = tmp_path / "2026-10-02 fleeting-123.md"
    content = "# Note\n\nSome content"

    sha = reg.register(note_path, content)
    assert isinstance(sha, str)
    assert len(sha) == 64

    # String and Path match
    assert reg.is_echo(note_path, content) is True
    assert reg.is_echo(str(note_path), content) is True


def test_registry_modified_content_not_echo(tmp_path: Path):
    reg = VaultSyncRegistry()
    note_path = tmp_path / "note.md"
    content = "# Note\n\nInitial"

    reg.register(note_path, content)
    assert reg.is_echo(note_path, "# Note\n\nEdited by user") is False


def test_registry_unknown_path_not_echo(tmp_path: Path):
    reg = VaultSyncRegistry()
    assert reg.is_echo(tmp_path / "unknown.md", "content") is False


def test_registry_ttl_expiration(tmp_path: Path):
    reg = VaultSyncRegistry()
    note_path = tmp_path / "note.md"
    content = "# Note\n\nInitial"

    reg.register(note_path, content)

    # Within default 10s TTL
    assert reg.is_echo(note_path, content, ttl=10.0) is True

    # With expired TTL
    with patch("time.monotonic") as mock_time:
        # Time when registered was e.g. 100.0, now 115.0
        mock_time.return_value = 200.0
        reg.register(note_path, content)
        mock_time.return_value = 215.0  # 15s later
        assert reg.is_echo(note_path, content, ttl=10.0) is False


def test_registry_clear(tmp_path: Path):
    reg = VaultSyncRegistry()
    note_path = tmp_path / "note.md"
    content = "# Note"

    reg.register(note_path, content)
    assert reg.is_echo(note_path, content) is True

    reg.clear()
    assert reg.is_echo(note_path, content) is False


def test_watcher_lifecycle(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    watcher = VaultWatcher(vault_dir)
    assert watcher.is_running() is False

    watcher.start()
    assert watcher.is_running() is True

    # Second start is idempotent
    watcher.start()
    assert watcher.is_running() is True

    watcher.stop()
    assert watcher.is_running() is False

    # Second stop is idempotent
    watcher.stop()
    assert watcher.is_running() is False


def test_watcher_nonexistent_directory(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist"
    watcher = VaultWatcher(nonexistent)
    # Shouldn't crash if directory does not exist
    watcher.start()
    assert watcher.is_running() is False


def test_watcher_debounces_file_events(tmp_path: Path):
    events: list[Path] = []

    def on_change(p: Path):
        events.append(p)

    watcher = VaultWatcher(tmp_path, on_change=on_change, debounce_secs=0.15)
    watcher.start()

    note_file = tmp_path / "test_debounce.md"

    try:
        # Rapidly write multiple times
        for i in range(5):
            note_file.write_text(f"# Version {i}\n", encoding="utf-8")
            time.sleep(0.02)

        # Wait for debounce to fire
        time.sleep(0.35)

        assert len(events) == 1
        assert events[0].resolve() == note_file.resolve()
    finally:
        watcher.stop()


def test_watcher_ignores_non_markdown_and_temp(tmp_path: Path):
    events: list[Path] = []

    def on_change(p: Path):
        events.append(p)

    watcher = VaultWatcher(tmp_path, on_change=on_change, debounce_secs=0.1)
    watcher.start()

    try:
        # Create non-markdown files
        (tmp_path / "plain.txt").write_text("hello", encoding="utf-8")
        (tmp_path / ".hidden.md").write_text("hidden", encoding="utf-8")
        (tmp_path / "note.md.tmp").write_text("temp", encoding="utf-8")
        (tmp_path / "note.md.swp").write_text("swap", encoding="utf-8")
        (tmp_path / "note.md~").write_text("backup", encoding="utf-8")
        (tmp_path / "foo.tmp.md").write_text("temp md", encoding="utf-8")
        (tmp_path / "#draft.md#").write_text("emacs auto-save", encoding="utf-8")

        time.sleep(0.25)
        assert len(events) == 0

        # Now write a valid .md file
        valid_md = tmp_path / "valid.md"
        valid_md.write_text("# Valid\n", encoding="utf-8")
        time.sleep(0.25)

        assert len(events) == 1
        assert events[0].resolve() == valid_md.resolve()
    finally:
        watcher.stop()


def test_watcher_filters_outside_vault(tmp_path: Path):
    vault_dir = tmp_path / "my_vault"
    vault_dir.mkdir()
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("# Outside", encoding="utf-8")

    watcher = VaultWatcher(vault_dir)
    assert watcher._should_ignore(outside_file) is True

    inside_file = vault_dir / "inside.md"
    inside_file.write_text("# Inside", encoding="utf-8")
    assert watcher._should_ignore(inside_file) is False


def test_watcher_tilde_expansion():
    watcher = VaultWatcher("~/test_vault")
    assert "~" not in str(watcher.vault_dir)
    assert str(watcher.vault_dir).startswith(str(Path.home()))


def test_watcher_on_moved_dispatches_src_and_dest(tmp_path: Path):
    events: list[Path] = []

    def on_change(p: Path):
        events.append(p)

    watcher = VaultWatcher(tmp_path, on_change=on_change, debounce_secs=0.05)
    handler = _VaultEventHandler(watcher)

    src_path = str(tmp_path / "original.md")
    dest_path = str(tmp_path / "renamed.md")

    event = FileMovedEvent(src_path, dest_path)
    handler.on_moved(event)

    time.sleep(0.15)

    dispatched = {p.resolve() for p in events}
    assert Path(src_path).resolve() in dispatched
    assert Path(dest_path).resolve() in dispatched


def test_watcher_on_moved_to_trash_only_dispatches_src(tmp_path: Path):
    events: list[Path] = []

    def on_change(p: Path):
        events.append(p)

    watcher = VaultWatcher(tmp_path, on_change=on_change, debounce_secs=0.05)
    handler = _VaultEventHandler(watcher)

    src_path = str(tmp_path / "note.md")
    trash_dir = tmp_path / ".trash"
    trash_dir.mkdir(exist_ok=True)
    dest_path = str(trash_dir / "note.md")

    event = FileMovedEvent(src_path, dest_path)
    handler.on_moved(event)

    time.sleep(0.15)

    dispatched = {p.resolve() for p in events}
    assert Path(src_path).resolve() in dispatched
    assert Path(dest_path).resolve() not in dispatched


def test_sync_note_registers_in_sync_registry(tmp_path: Path):
    sync_registry.clear()

    cfg = PathsConfig(vault_dir=str(tmp_path), vault_sync=True)
    note = {
        "id": "abc12345",
        "title": "Echo Test",
        "created_at": "2026-10-02T10:00:00Z",
        "type": "text",
        "summary": "Testing echo suppression",
        "action_items": [],
        "raw_text": "Hello world",
    }

    path = sync_note(cfg, note)
    assert path is not None
    assert path.exists()

    rendered = render_note_md(note)
    assert sync_registry.is_echo(path, rendered) is True

    # Modified content should not be echo
    assert sync_registry.is_echo(path, rendered + "\nExtra user edit") is False


def test_vault_path_for_date_fallback(tmp_path: Path):
    cfg = PathsConfig(vault_dir=str(tmp_path), vault_sync=True)

    # Note with created instead of created_at
    note_created = {
        "id": "111",
        "created": "2026-10-02T15:00:00Z",
    }
    p1 = vault_path_for(cfg, note_created)
    assert "2026" in str(p1.parent)
    assert "2026-10-02 fleeting-111.md" in p1.name

    # Undated note
    note_undated = {"id": "222"}
    p2 = vault_path_for(cfg, note_undated)
    assert "undated fleeting-222.md" in p2.name
