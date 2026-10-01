"""Local Git repository discovery service across configured watch directories."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("fleeting.repos")


def discover_git_repos(watch_dirs: str | None) -> list[dict]:
    """Scan configured watch_dirs for git repositories.

    Args:
        watch_dirs: Comma-separated list of directory paths (e.g. "~/Projects, ~/Documents").

    Returns:
        Sorted unique list of dicts: `[{"name": str.lower(), "path": str(abs_path)}]`.
    """
    if not watch_dirs or not str(watch_dirs).strip():
        return []

    repos: dict[str, dict] = {}

    for raw_dir in watch_dirs.split(","):
        trimmed = raw_dir.strip()
        if not trimmed:
            continue
        try:
            base_path = Path(trimmed).expanduser().resolve()
        except Exception:
            log.warning("failed to resolve watch_dir: %s", raw_dir, exc_info=True)
            continue

        if not base_path.exists() or not base_path.is_dir():
            continue

        # Check if the directory itself is a git repository (.git dir or worktree file)
        git_target = base_path / ".git"
        if git_target.exists():
            resolved_path = str(base_path)
            repos[resolved_path] = {
                "name": base_path.name.lower(),
                "path": resolved_path,
            }

        # Check immediate child directories
        try:
            for child in base_path.iterdir():
                try:
                    if child.is_dir() and (child / ".git").exists():
                        child_resolved = str(child.resolve())
                        repos[child_resolved] = {
                            "name": child.name.lower(),
                            "path": child_resolved,
                        }
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            log.debug("permission or os error reading %s", base_path)
            continue

    repo_list = list(repos.values())
    repo_list.sort(key=lambda r: (r["name"], r["path"]))
    return repo_list
