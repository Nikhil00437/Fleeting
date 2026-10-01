"""Markdown rendering / vault sync and subtitle parsing tests."""

from __future__ import annotations

from fleeting.config import PathsConfig
from fleeting.services.markdown import (
    note_filename,
    render_note_md,
    remove_note,
    sync_note,
    vault_path_for,
)
from fleeting.services.youtube import _parse_subtitle


def make_note(**over) -> dict:
    base = {
        "id": "abc123",
        "type": "text",
        "title": "My note",
        "summary": "A summary.",
        "raw_text": "Body text here.",
        "tags": ["one", "two"],
        "action_items": [
            {"id": "t1", "text": "Do the thing", "done": False},
            {"id": "t2", "text": "Done thing", "done": True},
        ],
        "source": {"url": "https://example.com", "channel": "ch"},
        "created_at": "2026-09-29T12:00:00+00:00",
    }
    base.update(over)
    return base


def test_render_note_md():
    md = render_note_md(make_note())
    assert md.startswith("---")
    assert "id: abc123" in md
    assert "  - one" in md
    assert "# My note" in md
    assert "- [ ] Do the thing" in md
    assert "- [x] Done thing" in md
    assert "Body text here." in md


def test_filename_stable_across_title_change():
    n1 = make_note(title="First title")
    n2 = make_note(title="Second totally different")
    assert note_filename(n1) == note_filename(n2)


def test_sync_update_and_remove(tmp_path):
    cfg = PathsConfig(vault_dir=str(tmp_path), vault_sync=True)
    note = make_note()
    path = sync_note(cfg, note)
    assert path and path.exists()
    # re-enrich with new title -> same file, updated content
    note["title"] = "Renamed"
    path2 = sync_note(cfg, note)
    assert path2 == path
    assert "Renamed" in path.read_text()
    # path is inside the vault -> removal allowed
    remove_note(cfg, note)
    assert not path.exists()


def test_sync_disabled_returns_none(tmp_path):
    cfg = PathsConfig(vault_dir=str(tmp_path), vault_sync=False)
    assert sync_note(cfg, make_note()) is None


def test_vault_path_structure(tmp_path):
    cfg = PathsConfig(vault_dir=str(tmp_path), vault_sync=True)
    path = vault_path_for(cfg, make_note())
    assert path.parent == tmp_path / "2026"


VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
Hello <c>world</c> this

00:00:02.500 --> 00:00:04.000
Hello <c>world</c> this

00:00:03.000 --> 00:00:05.000
is a test line

00:02:01.000 --> 00:02:03.000
another thought appears
"""


def test_parse_subtitle_dedupes_and_anchors():
    text = _parse_subtitle_from(VTT)
    assert text.count("Hello world this") == 1, "rolling dupes removed"
    assert "[2:01]" in text, "two-minute anchor inserted in M:SS form"


def _parse_subtitle_from(vtt: str, tmp_path=None):
    import tempfile
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    f = d / "video.vtt"
    f.write_text(vtt, encoding="utf-8")
    return _parse_subtitle(f)
