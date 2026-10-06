"""Task export (#40): todo.txt and a Markdown checklist.

Two formats because they answer different needs: `todo.txt` drops into any
todo.txt-aware editor, the Markdown checklist renders inside the vault so it
reads like the notes around it. Both are pure renderers — writing them to disk
is the caller's job, so the same output can be downloaded or filed.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def _sorted_open(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Undated work first (by priority), then dated work by date — a checklist
    # you can actually work top-down.
    return sorted(
        tasks,
        key=lambda t: (
            0 if not t.get("due_date") else 1,
            t.get("due_date") or "",
            {"P1": 0, "P2": 1, "P3": 2}.get(t.get("priority", "P2"), 1),
        ),
    )


def render_todo_txt(tasks: list[dict[str, Any]], done: list[dict[str, Any]] | None = None) -> str:
    """todo.txt format: one line per task, `x ` prefix when completed."""
    lines: list[str] = []
    for t in _sorted_open(tasks):
        suffix = f" @{t['due_date']}" if t.get("due_date") else ""
        lines.append(f"(A) {t['text']}{suffix}")
    for t in done or []:
        lines.append(f"x (A) {t['text']}")
    return "\n".join(lines) + ("\n" if lines else "")


def render_markdown(tasks: list[dict[str, Any]], done: list[dict[str, Any]] | None = None, day: str | None = None) -> str:
    """A vault-friendly checklist grouped by priority, with a done section."""
    header = f"# Tasks\n\n_Exported {day or date.today().isoformat()}_\n"
    by_priority = {"P1": [], "P2": [], "P3": []}
    for t in _sorted_open(tasks):
        by_priority.setdefault(t.get("priority", "P2"), []).append(t)

    parts = [header]
    for level in ("P1", "P2", "P3"):
        if not by_priority[level]:
            continue
        parts.append(f"\n## {level}\n")
        for t in by_priority[level]:
            due = f" — _due {t['due_date']}_" if t.get("due_date") else ""
            tag = f" `#{t['repo']}`" if t.get("repo") else ""
            parts.append(f"- [ ] {t['text']}{tag}{due}\n")
    if done:
        parts.append("\n## Done\n")
        for t in done:
            parts.append(f"- [x] {t['text']}\n")
    return "".join(parts)