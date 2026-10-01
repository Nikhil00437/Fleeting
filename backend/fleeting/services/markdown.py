"""Markdown vault sync.

Every finished note is mirrored into the user's vault directory as a plain
Markdown file with YAML frontmatter — readable by Obsidian, or anything else.
Filenames are stable across re-enrichment so syncs are updates, not spam.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config import PathsConfig, expand_path

log = logging.getLogger("fleeting.markdown")


def _slugify(text: str, max_len: int = 48) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\u0900-\u097F-]", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:max_len].strip("-") or "note"


def note_filename(note: dict) -> str:
    """Stable across re-enrichment: date + id only (no title slug, which churns)."""
    date = (note.get("created_at") or "")[:10] or "undated"
    return f"{date} fleeting-{note['id']}.md"


def render_note_md(note: dict) -> str:
    """Note dict -> Markdown string with YAML frontmatter."""
    source = note.get("source") or {}
    tags = note.get("tags") or []
    fm_lines = [
        "---",
        f"id: {note['id']}",
        f"type: {note.get('type', 'text')}",
        f"created: {note.get('created_at', '')}",
        f"app: fleeting",
    ]
    if tags:
        fm_lines.append("tags:")
        fm_lines.extend(f"  - {t}" for t in tags)
    if source.get("url"):
        fm_lines.append(f"source: {source['url']}")
    if source.get("channel"):
        fm_lines.append(f"channel: {source['channel']}")
    fm_lines.append("---")

    parts = ["\n".join(fm_lines), f"# {note.get('title') or 'Untitled capture'}"]
    if note.get("summary"):
        parts.append(note["summary"])

    items = note.get("action_items") or []
    if items:
        checklist = "\n".join(f"- [{'x' if it.get('done') else ' '}] {it.get('text', '')}" for it in items)
        parts.append("## Action items\n" + checklist)

    raw = (note.get("raw_text") or "").strip()
    if raw:
        parts.append("## Content" if note.get("type") != "voice" else "## Transcript")
        parts.append(raw)

    return "\n\n".join(parts).strip() + "\n"


def vault_path_for(cfg: PathsConfig, note: dict) -> Path:
    vault = expand_path(cfg.vault_dir)
    date = (note.get("created_at") or "")[:10] or "undated"
    return vault / date[:4] / note_filename(note)


def sync_note(cfg: PathsConfig, note: dict) -> Path | None:
    """Write/update the note's markdown file. Returns path or None if sync off."""
    if not cfg.vault_sync:
        return None
    path = vault_path_for(cfg, note)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_note_md(note), encoding="utf-8")
    except OSError as exc:
        log.error("vault sync failed for note %s: %s", note.get("id"), exc)
        return None
    return path


def remove_note(cfg: PathsConfig, note: dict) -> None:
    if not cfg.vault_sync:
        return
    path = vault_path_for(cfg, note)
    vault_root = expand_path(cfg.vault_dir).resolve()
    try:
        if path.exists() and vault_root in path.resolve().parents:
            path.unlink()
    except OSError as exc:
        log.error("vault cleanup failed for note %s: %s", note.get("id"), exc)


def export_all(cfg: PathsConfig, notes: list[dict]) -> int:
    count = 0
    for note in notes:
        if sync_note(cfg, note):
            count += 1
    return count
