"""#166 Weekly 'what shipped' view combining commits, tasks, and notes.

Aggregates everything finished and produced during a given week:
- Git commits across all watched repositories
- Tasks completed and closed
- Captured notes and research
Generates an executive changelog and structured summary.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from ..config import Config, expand_path
from ..db import Database, _row_to_task
from .files_activity import collect_git_subjects
from .weeklylog import current_week_start, week_start_for


def get_what_shipped(
    db: Database,
    cfg: Config,
    week_start: str | None = None,
) -> dict[str, Any]:
    if not week_start:
        week_start = current_week_start()
    else:
        try:
            d = date.fromisoformat(week_start)
            week_start = week_start_for(d)
        except ValueError:
            week_start = current_week_start()

    start_dt = datetime.fromisoformat(f"{week_start}T00:00:00").astimezone()
    end_dt = start_dt + timedelta(days=7)
    week_end = (end_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    # 1. Commits: Git repos + commits table
    commits: list[dict[str, Any]] = []
    seen_commits: set[tuple[str, str]] = set()

    # From watched directories
    dirs = [
        expand_path(p.strip())
        for p in (cfg.activity.watch_dirs or "").split(",")
        if p.strip()
    ]
    if dirs:
        try:
            git_subjects = collect_git_subjects(dirs, since=start_dt, until=end_dt)
            for repo_entry in git_subjects:
                repo_name = repo_entry.get("repo", "repo")
                for subj in repo_entry.get("subjects", []):
                    key = (repo_name.lower(), subj.strip())
                    if key not in seen_commits:
                        seen_commits.add(key)
                        commits.append(
                            {
                                "repo": repo_name,
                                "subject": subj.strip(),
                                "author": None,
                                "committed_at": None,
                            }
                        )
        except Exception:
            pass

    # From DB commits table
    try:
        db_commits = db.execute(
            """
            SELECT repo, subject, author, committed_at
            FROM commits
            WHERE committed_at >= ? AND committed_at < ?
            ORDER BY committed_at DESC
            """,
            (start_iso[:19], end_iso[:19]),
        ).fetchall()
        for r in db_commits:
            repo_name = r["repo"] or "repo"
            subj = r["subject"] or ""
            key = (repo_name.lower(), subj.strip())
            if key not in seen_commits:
                seen_commits.add(key)
                commits.append(
                    {
                        "repo": repo_name,
                        "subject": subj.strip(),
                        "author": r["author"],
                        "committed_at": r["committed_at"],
                    }
                )
    except Exception:
        pass

    # Group commits by repo
    commits_by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in commits:
        commits_by_repo[c["repo"]].append(c)

    # 2. Completed Tasks
    task_rows = db.execute(
        """
        SELECT * FROM tasks
        WHERE done = 1
          AND (
            (completed_at IS NOT NULL AND completed_at >= ? AND completed_at < ?)
            OR
            (completed_at IS NULL AND created_at >= ? AND created_at < ?)
          )
        ORDER BY completed_at DESC, created_at DESC
        """,
        (start_iso[:19], end_iso[:19], start_iso[:19], end_iso[:19]),
    ).fetchall()
    completed_tasks = [_row_to_task(r) for r in task_rows]

    # 3. Notes created during this week
    note_rows = db.execute(
        """
        SELECT id, type, title, tags, created_at, updated_at
        FROM notes
        WHERE trashed_at IS NULL AND archived = 0
          AND created_at >= ? AND created_at < ?
        ORDER BY created_at DESC
        """,
        (start_iso[:19], end_iso[:19]),
    ).fetchall()

    notes: list[dict[str, Any]] = []
    for r in note_rows:
        tags = []
        if r["tags"]:
            try:
                tags = json.loads(r["tags"])
            except Exception:
                tags = []
        notes.append(
            {
                "id": r["id"],
                "type": r["type"],
                "title": r["title"] or "Untitled Note",
                "tags": tags,
                "created_at": r["created_at"],
            }
        )

    # 4. Generate structured changelog markdown
    lines = [f"# What Shipped — Week of {week_start} ({week_start} to {week_end})", ""]

    if commits:
        lines += [f"## Git Commits ({len(commits)})", ""]
        for repo_name, repo_commits in sorted(commits_by_repo.items()):
            lines.append(f"### {repo_name}")
            for c in repo_commits:
                lines.append(f"- {c['subject']}")
            lines.append("")
    else:
        lines += ["## Git Commits", "- No git commits recorded in watched repositories.", ""]

    if completed_tasks:
        lines += [f"## Completed Tasks ({len(completed_tasks)})", ""]
        for t in completed_tasks:
            pri = f"[{t.get('priority', 'P2')}] " if t.get("priority") else ""
            repo = f" ({t['repo']})" if t.get("repo") else ""
            lines.append(f"- [x] {pri}**{t['text']}**{repo}")
        lines.append("")
    else:
        lines += ["## Completed Tasks", "- No completed tasks recorded.", ""]

    if notes:
        lines += [f"## Captures & Knowledge ({len(notes)})", ""]
        for n in notes:
            tag_str = f" (#{', #'.join(n['tags'])})" if n.get("tags") else ""
            lines.append(f"- **[{n['type']}]** {n['title']}{tag_str}")
        lines.append("")
    else:
        lines += ["## Captures & Knowledge", "- No notes captured.", ""]

    markdown = "\n".join(lines).strip()

    return {
        "week_start": week_start,
        "week_end": week_end,
        "commits": commits,
        "commits_by_repo": dict(commits_by_repo),
        "completed_tasks": completed_tasks,
        "notes": notes,
        "markdown": markdown,
        "counts": {
            "commits": len(commits),
            "tasks": len(completed_tasks),
            "notes": len(notes),
            "total": len(commits) + len(completed_tasks) + len(notes),
        },
    }
