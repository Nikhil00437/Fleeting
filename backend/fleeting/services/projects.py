"""#53 project detection and time-per-project.

Detection runs at write time, so reports and the timeline never re-guess a
title that may since have changed. Precedence: a git repo the window is
sitting in is ground truth, then a path under a watched root, then a
recognisable `owner/repo` or bare project name in the title.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import Database

# `owner/repo` or `owner / repo` in a title — GitHub, a terminal prompt, a
# browser tab. Requires a slash and a word character on both sides.
_SLASH_REPO_RE = re.compile(r"\b([\w.-]+)\s*/\s*([\w.-]+)\b")
# "project: something" / "project — something" — a labelled window title.
_LABELLED_RE = re.compile(r"^([A-Za-z][\w-]{1,40})\s*[—\-:|]\s*\S")

_STOPWORDS = frozenset(
    """inbox new tab window untitled document file folder settings home desktop
    downloads documents projects github gitlab terminal emulator text editor
    page search mail calendar notes todo readme src lib app apps backend
    frontend node_modules users tmp var usr etc opt www public private build
    dist target""".split()
)


def _root_spellings(roots: tuple[str, ...] | list[str]) -> list[tuple[str, str]]:
    """[(expanded, as-it-appears-in-a-title)] for every configured root."""
    out: list[tuple[str, str]] = []
    home = os.path.expanduser("~")
    for raw in roots:
        raw = (raw or "").strip()
        if not raw:
            continue
        expanded = os.path.expanduser(raw)
        out.append((expanded, expanded))
        if expanded.startswith(home + "/"):
            out.append((expanded, "~" + expanded[len(home):]))
    return out


def detect_project(
    title: str, *, repo: str | None = None, roots: tuple[str, ...] | list[str] = ()
) -> str | None:
    """Best guess at the project a window belongs to, or None."""
    if repo:
        return repo
    text = (title or "").strip()
    if not text:
        return None

    # Window titles keep the literal "~" a shell would print, while watch_dirs
    # are configured expanded — match both spellings of the same root.
    for root, spelled in _root_spellings(roots):
        idx = text.find(spelled)
        if idx == -1:
            continue
        rest = text[idx + len(spelled):].strip(" /\\:-—")
        if not rest:
            continue
        # A file sitting directly in a watched root names the project too:
        # ~/Documents/taxes.ods is project "taxes".
        first = re.split(r"[ /\\]", rest)[0].split(".")[0]
        if first and first.lower() not in _STOPWORDS:
            return first

    # Only the leading window-title part can be an owner/repo — a full path in
    # the same shape ("/home/me/notes") would otherwise read as one.
    head = re.split(r"[—\-:|]", text)[0].strip()
    m = _SLASH_REPO_RE.fullmatch(head)
    if m and m.group(2).lower() not in _STOPWORDS:
        return m.group(2)

    # A bare project name only counts in the "project: file — app" shape. A
    # title that is just one word ("vim", "Inbox") names no project.
    m = _LABELLED_RE.match(text)
    if m and m.group(1).lower() not in _STOPWORDS:
        return m.group(1)
    return None


def project_seconds(db: Database, day: str, *, include_empty: bool = False) -> list[dict]:
    """Seconds per project for a day, heaviest first.

    Unlabelled time is dropped unless `include_empty` — a day that is 40%
    "no project" is a detection problem the user should see, not a bucket.
    """
    rows = db.execute(
        # LOWER in SQL so "Fleeting" from a title and "fleeting" from a repo
        # land in the same bucket instead of splitting the day's time.
        "SELECT LOWER(project) AS project, SUM(seconds) AS seconds FROM activity"
        " WHERE day = ? AND seconds >= 1 AND (? = 1 OR project IS NOT NULL)"
        " GROUP BY LOWER(project) ORDER BY seconds DESC",
        (day, 1 if include_empty else 0),
    ).fetchall()
    return [{"project": r["project"], "seconds": r["seconds"] or 0} for r in rows]


def list_projects_summary(db: Database) -> list[dict]:
    """#167 all known projects with summary metrics across activity history."""
    rows = db.execute(
        """
        SELECT LOWER(project) AS project,
               SUM(seconds) AS total_seconds,
               COUNT(DISTINCT day) AS active_days,
               MAX(day) AS last_active
        FROM activity
        WHERE project IS NOT NULL AND length(trim(project)) > 0 AND seconds >= 1
        GROUP BY LOWER(project)
        ORDER BY total_seconds DESC
        """
    ).fetchall()
    return [
        {
            "project": r["project"],
            "total_seconds": r["total_seconds"] or 0,
            "active_days": r["active_days"] or 0,
            "last_active": r["last_active"],
        }
        for r in rows
    ]


def get_project_dashboard(db: Database, project: str, *, days: int = 30) -> dict:
    """#167 complete dashboard for a project: time, apps, branches, commits, tasks and notes."""
    import json

    norm = (project or "").strip().lower()
    if not norm:
        return {
            "project": "",
            "total_seconds": 0,
            "window_seconds": 0,
            "active_days": 0,
            "last_active": None,
            "daily_breakdown": [],
            "apps": [],
            "branches": [],
            "recent_sessions": [],
            "commits": [],
            "tasks": {"total": 0, "completed": 0, "pending": 0, "items": []},
            "notes": [],
        }

    # 1. Lifetime totals
    tot_row = db.execute(
        """
        SELECT SUM(seconds) AS total_seconds,
               COUNT(DISTINCT day) AS active_days,
               MAX(day) AS last_active
        FROM activity
        WHERE LOWER(project) = ? AND seconds >= 1
        """,
        (norm,),
    ).fetchone()
    total_seconds = (tot_row["total_seconds"] or 0) if tot_row else 0
    active_days = (tot_row["active_days"] or 0) if tot_row else 0
    last_active = tot_row["last_active"] if tot_row else None

    # 2. Daily breakdown
    daily_rows = db.execute(
        """
        SELECT day, SUM(seconds) AS seconds
        FROM activity
        WHERE LOWER(project) = ? AND seconds >= 1
        GROUP BY day
        ORDER BY day ASC
        """,
        (norm,),
    ).fetchall()
    daily_breakdown = [
        {"day": r["day"], "seconds": r["seconds"] or 0} for r in daily_rows
    ]
    if days > 0 and len(daily_breakdown) > days:
        daily_breakdown = daily_breakdown[-days:]
    window_seconds = sum(d["seconds"] for d in daily_breakdown)

    # 3. Top apps
    app_rows = db.execute(
        """
        SELECT app_class, SUM(seconds) AS seconds
        FROM activity
        WHERE LOWER(project) = ? AND seconds >= 1
        GROUP BY app_class
        ORDER BY seconds DESC
        """,
        (norm,),
    ).fetchall()
    apps = [
        {
            "app": r["app_class"],
            "seconds": r["seconds"] or 0,
            "percent": round(100.0 * (r["seconds"] or 0) / total_seconds, 1)
            if total_seconds > 0
            else 0.0,
        }
        for r in app_rows
    ]

    # 4. Active branches
    branch_rows = db.execute(
        """
        SELECT branch, SUM(seconds) AS seconds
        FROM activity
        WHERE LOWER(project) = ? AND branch IS NOT NULL AND length(trim(branch)) > 0 AND seconds >= 1
        GROUP BY branch
        ORDER BY seconds DESC
        """,
        (norm,),
    ).fetchall()
    branches = [
        {"branch": r["branch"], "seconds": r["seconds"] or 0} for r in branch_rows
    ]

    # 5. Recent sessions
    session_rows = db.execute(
        """
        SELECT id, title, app_class, seconds, day, first_seen
        FROM activity
        WHERE LOWER(project) = ? AND seconds >= 1
        ORDER BY first_seen DESC
        LIMIT 15
        """,
        (norm,),
    ).fetchall()
    recent_sessions = [
        {
            "id": r["id"],
            "title": r["title"],
            "app_class": r["app_class"],
            "seconds": r["seconds"],
            "day": r["day"],
            "first_seen": r["first_seen"],
        }
        for r in session_rows
    ]

    # 6. Commits
    commit_rows = db.execute(
        """
        SELECT repo, subject, author, committed_at
        FROM commits
        WHERE LOWER(repo) = ? OR LOWER(repo) LIKE ?
        ORDER BY committed_at DESC
        LIMIT 20
        """,
        (norm, f"%/{norm}"),
    ).fetchall()
    commits = [
        {
            "repo": r["repo"],
            "subject": r["subject"],
            "author": r["author"],
            "committed_at": r["committed_at"],
        }
        for r in commit_rows
    ]

    # 7. Tasks
    task_rows = db.execute(
        """
        SELECT id, text, done, priority, due_date, estimate_min, spent_min, repo, created_at, completed_at
        FROM tasks
        WHERE LOWER(repo) = ? OR LOWER(text) LIKE ?
        ORDER BY done ASC, priority ASC, created_at DESC
        """,
        (norm, f"%#{norm}%"),
    ).fetchall()
    tasks_items = [
        {
            "id": r["id"],
            "text": r["text"],
            "done": r["done"],
            "priority": r["priority"],
            "due_date": r["due_date"],
            "estimate_min": r["estimate_min"],
            "spent_min": r["spent_min"],
            "repo": r["repo"],
            "created_at": r["created_at"],
            "completed_at": r["completed_at"],
        }
        for r in task_rows
    ]
    tasks_completed = sum(1 for t in tasks_items if t["done"])
    tasks_total = len(tasks_items)

    # 8. Notes
    note_rows = db.execute(
        """
        SELECT id, title, created_at, tags, raw_text
        FROM notes
        WHERE EXISTS (
            SELECT 1 FROM json_each(notes.tags) je
            WHERE LOWER(je.value) = ? OR LOWER(je.value) = ?
        ) OR LOWER(raw_text) LIKE ?
        ORDER BY created_at DESC
        LIMIT 15
        """,
        (norm, f"#{norm}", f"%#{norm}%"),
    ).fetchall()
    notes = [
        {
            "id": r["id"],
            "title": r["title"] or "Untitled",
            "created_at": r["created_at"],
            "tags": json.loads(r["tags"] or "[]"),
        }
        for r in note_rows
    ]

    return {
        "project": norm,
        "total_seconds": total_seconds,
        "window_seconds": window_seconds,
        "active_days": active_days,
        "last_active": last_active,
        "daily_breakdown": daily_breakdown,
        "apps": apps,
        "branches": branches,
        "recent_sessions": recent_sessions,
        "commits": commits,
        "tasks": {
            "total": tasks_total,
            "completed": tasks_completed,
            "pending": tasks_total - tasks_completed,
            "items": tasks_items,
        },
        "notes": notes,
    }