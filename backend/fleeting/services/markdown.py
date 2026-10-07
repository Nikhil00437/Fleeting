"""Markdown vault sync.

Every finished note is mirrored into the user's vault directory as a plain
Markdown file with YAML frontmatter — readable by Obsidian, or anything else.
Filenames are stable across re-enrichment so syncs are updates, not spam.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from ..config import PathsConfig, expand_path
from .vault_watcher import sync_registry

log = logging.getLogger("fleeting.markdown")


def _slugify(text: str, max_len: int = 48) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\u0900-\u097F-]", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:max_len].strip("-") or "note"


def note_filename(note: dict) -> str:
    """Stable across re-enrichment: date + id only (no title slug, which churns)."""
    from .calendar_svc import date_tag

    date_str = date_tag(note.get("created_at") or note.get("created")) or "undated"
    return f"{date_str} fleeting-{note['id']}.md"


def _clean_task_text(text: str) -> str:
    """Strip metadata tags from checklist text leaving clean human-readable text."""
    cleaned = re.sub(r"\[[pP][123]\]", "", text)
    cleaned = re.sub(r"\[due:\d{4}-\d{2}-\d{2}\]", "", cleaned)
    cleaned = re.sub(r"\[repo:[a-zA-Z0-9_-]+\]", "", cleaned)
    cleaned = re.sub(r"\[id:[a-zA-Z0-9_-]+\]", "", cleaned)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def render_note_md(note: dict) -> str:
    """Note dict -> Markdown string with YAML frontmatter."""
    source = note.get("source") or {}
    tags = note.get("tags") or []
    created_val = note.get("created_at") or note.get("created") or ""
    fm_lines = [
        "---",
    ]
    if note.get("id"):
        fm_lines.append(f"id: {note['id']}")
    fm_lines.extend([
        f"type: {note.get('type', 'text')}",
        f"created: {created_val}",
        f"app: fleeting",
    ])
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
        checklist_lines = []
        for it in items:
            done_char = "x" if it.get("done") else " "
            raw_t = (it.get("text") or "").strip()
            clean_t = _clean_task_text(raw_t)

            tags_to_add = []
            p = (it.get("priority") or "").strip().upper()
            if p in ("P1", "P3"):
                tags_to_add.append(f"[{p}]")
            if it.get("due_date"):
                tags_to_add.append(f"[due:{str(it['due_date']).strip()}]")
            if it.get("repo"):
                tags_to_add.append(f"[repo:{str(it['repo']).strip()}]")

            suffix = (" " + " ".join(tags_to_add)) if tags_to_add else ""
            checklist_lines.append(f"- [{done_char}] {clean_t}{suffix}")

        parts.append("## Action items\n" + "\n".join(checklist_lines))

    raw = (note.get("raw_text") or "").strip()
    if raw:
        parts.append("## Content" if note.get("type") != "voice" else "## Transcript")
        parts.append(raw)

    return "\n\n".join(parts).strip() + "\n"


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract and parse YAML frontmatter between '---' markers.

    Returns (frontmatter_dict, remaining_body).
    """
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return {}, content

    match = re.match(r"^[ \t]*---[ \t]*\r?\n(.*?)\r?\n[ \t]*---[ \t]*(?:\r?\n|$)(.*)$", stripped, re.DOTALL)
    if not match:
        return {}, content

    fm_raw = match.group(1)
    body = match.group(2)

    fm_data: dict[str, Any] = {}
    try:
        loaded = yaml.safe_load(fm_raw)
        if isinstance(loaded, dict):
            fm_data = loaded
    except Exception as exc:
        log.warning("Failed to parse YAML frontmatter with PyYAML, using regex fallback: %s", exc)
        id_m = re.search(r"^id:\s*(.*)$", fm_raw, re.MULTILINE)
        if id_m:
            fm_data["id"] = id_m.group(1).strip()
        type_m = re.search(r"^type:\s*(.*)$", fm_raw, re.MULTILINE)
        if type_m:
            fm_data["type"] = type_m.group(1).strip()
        created_m = re.search(r"^created:\s*(.*)$", fm_raw, re.MULTILINE)
        if created_m:
            fm_data["created"] = created_m.group(1).strip()
        src_m = re.search(r"^source:\s*(.*)$", fm_raw, re.MULTILINE)
        if src_m:
            fm_data["source"] = src_m.group(1).strip()
        ch_m = re.search(r"^channel:\s*(.*)$", fm_raw, re.MULTILINE)
        if ch_m:
            fm_data["channel"] = ch_m.group(1).strip()

    return fm_data, body


def _parse_checklist_items(lines: list[str]) -> list[dict[str, Any]]:
    """Parse checklist items from lines matching - [ ] or - [x] syntax."""
    items: list[dict[str, Any]] = []
    pattern = re.compile(r"^[ \t]*-[ \t]*\[([ xX])\](?:[ \t]+(.*))?$")
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        done = match.group(1).lower() == "x"
        raw_text = (match.group(2) or "").strip()

        # Extract priority tag: [P1], [P2], [P3]
        p_match = re.search(r"\[([pP][123])\]", raw_text)
        priority = p_match.group(1).upper() if p_match else "P2"

        # Extract due date tag: [due:YYYY-MM-DD]
        due_match = re.search(r"\[due:(\d{4}-\d{2}-\d{2})\]", raw_text)
        due_date = due_match.group(1) if due_match else None

        # Extract repo tag: [repo:name]
        repo_match = re.search(r"\[repo:([a-zA-Z0-9_-]+)\]", raw_text)
        repo = repo_match.group(1) if repo_match else None

        # Extract optional id tag: [id:name]
        id_match = re.search(r"\[id:([a-zA-Z0-9_-]+)\]", raw_text)
        task_id = id_match.group(1) if id_match else None

        # Strip metadata tags to produce clean human-readable text
        clean_text = _clean_task_text(raw_text)

        items.append({
            "id": task_id,
            "text": clean_text,
            "done": done,
            "priority": priority,
            "due_date": due_date,
            "repo": repo,
        })
    return items


def parse_note_md(content: str) -> dict[str, Any]:
    """Parse Markdown content into structured note dictionary.

    Returns dict with keys:
    id, type, created, created_at, title, summary, tags, action_items, raw_text, source.
    """
    fm_data, body = _parse_frontmatter(content)

    # 1. Frontmatter attributes
    note_id = str(fm_data["id"]).strip() if fm_data.get("id") is not None else None
    note_type = str(fm_data.get("type") or "text").strip()

    c = fm_data.get("created")
    if isinstance(c, (datetime, date)):
        created_str = c.isoformat()
    elif c is not None:
        created_str = str(c).strip()
    else:
        created_str = ""

    tags_raw = fm_data.get("tags")
    if isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    elif isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif tags_raw is None and fm_data.get("tag"):
        tags = [str(fm_data["tag"]).strip()]
    else:
        tags = []

    src = fm_data.get("source")
    if isinstance(src, dict):
        source_dict: dict[str, Any] = {str(k): v for k, v in src.items()}
    elif isinstance(src, str) and src.strip():
        source_dict = {"url": src.strip()}
    else:
        source_dict = {}
    if fm_data.get("channel"):
        source_dict["channel"] = str(fm_data["channel"]).strip()

    # 2. Title extraction: first # Heading
    lines = body.splitlines()
    title = ""
    title_idx = -1
    for i, line in enumerate(lines):
        m = re.match(r"^#[ \t]+(.+)$", line)
        if m:
            title = m.group(1).strip()
            title_idx = i
            break

    # 3. Section extraction: split by ## Heading
    remaining_lines = lines[title_idx + 1:] if title_idx != -1 else lines
    pre_section_lines: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_section: str | None = None
    current_section_lines: list[str] = []

    for line in remaining_lines:
        h2_match = re.match(r"^##[ \t]+(.+)$", line)
        if h2_match:
            if current_section is not None:
                sections.append((current_section, current_section_lines))
            else:
                pre_section_lines = current_section_lines
            current_section = h2_match.group(1).strip()
            current_section_lines = []
        else:
            current_section_lines.append(line)

    if current_section is not None:
        sections.append((current_section, current_section_lines))
    else:
        pre_section_lines = current_section_lines

    # Summary: paragraphs before first ## Subheading
    pre_text = "\n".join(pre_section_lines).strip()
    if title or sections:
        summary = pre_text
        raw_text = ""
    else:
        summary = ""
        raw_text = pre_text

    # Extract sections
    action_items: list[dict[str, Any]] = []
    raw_text_parts: list[str] = []

    for sec_title, sec_lines in sections:
        sec_lower = sec_title.lower()
        if sec_lower in ("action items", "action item", "tasks", "todos"):
            action_items.extend(_parse_checklist_items(sec_lines))
        elif sec_lower in ("content", "transcript"):
            raw_text_parts.append("\n".join(sec_lines).strip())
        else:
            sec_body = "\n".join(sec_lines).strip()
            if sec_body:
                raw_text_parts.append(f"## {sec_title}\n\n{sec_body}")
            else:
                raw_text_parts.append(f"## {sec_title}")

    # Fallback: if no ## Action items heading was present, check pre_section_lines for checklist items
    if not action_items:
        fallback_items = _parse_checklist_items(pre_section_lines)
        if fallback_items:
            action_items = fallback_items
            non_cl_lines = [l for l in pre_section_lines if not re.match(r"^[ \t]*-[ \t]*\[([ xX])\]", l)]
            clean_pre = "\n".join(non_cl_lines).strip()
            if title or sections:
                summary = clean_pre
            else:
                raw_text = clean_pre

    if raw_text_parts:
        raw_text = "\n\n".join(raw_text_parts).strip()

    return {
        "id": note_id,
        "type": note_type,
        "created": created_str,
        "created_at": created_str,
        "title": title,
        "summary": summary,
        "tags": tags,
        "action_items": action_items,
        "raw_text": raw_text,
        "source": source_dict,
    }



def vault_path_for(cfg: PathsConfig, note: dict) -> Path:
    vault = expand_path(cfg.vault_dir)
    from .calendar_svc import date_tag

    date = date_tag(note.get("created_at") or note.get("created")) or "undated"
    return vault / date[:4] / note_filename(note)


def sync_note(cfg: PathsConfig, note: dict) -> Path | None:
    """Write/update the note's markdown file. Returns path or None if sync off.

    #26: sensitive notes never leave the database — the vault mirror is a
    plain-text copy on disk that outlives the app, so it must stay clean.
    """
    if not cfg.vault_sync:
        return None
    if note.get("sensitive"):
        # Also remove any file written before the note was marked sensitive.
        remove_note(cfg, note)
        return None
    path = vault_path_for(cfg, note)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = render_note_md(note)
        path.write_text(rendered, encoding="utf-8")
        sync_registry.register(path, rendered)
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


