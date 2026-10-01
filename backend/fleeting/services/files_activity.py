"""Save-file activity scan for the daily report.

Window titles say *where* you were; recently-modified files (and git commit
subjects) say *what you actually produced*. This module scans configured watch
directories for files modified inside a time window and collects git commit
subjects from repos under those dirs — metadata only, never file contents.

Junk directories (caches, build output, dependency trees) are skipped and
results are capped so a scan stays fast.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

log = logging.getLogger("fleeting.files")

SKIP_DIR_NAMES = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", "target", ".next",
    ".cache", ".gradle", ".idea", ".vscode", ".zcode", "snap", ".postgres_data",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".swp", ".lock", ".DS_Store"}
MAX_FILES = 400
MAX_DEPTH = 6
MAX_GIT_REPOS = 12
MAX_SUBJECTS_PER_REPO = 8


def scan_recent_files(watch_dirs: list[Path], since: datetime, until: datetime | None = None) -> dict:
    """Find files modified inside [since, until]. Metadata only.

    Returns {"total": int, "groups": [{"label", "count", "exts", "samples"}]}
    where groups are keyed by the project folder (first component under the
    watch dir, or the dir name for loose files).
    """
    until = until or datetime.now().astimezone()
    cutoff = since.timestamp()
    ceiling = until.timestamp()
    found: list[Path] = []
    for root in watch_dirs:
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack and len(found) < MAX_FILES:
            current, depth = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if len(found) >= MAX_FILES:
                    break
                name = entry.name
                if entry.is_dir():
                    if name in SKIP_DIR_NAMES or depth >= MAX_DEPTH:
                        continue
                    stack.append((entry, depth + 1))
                else:
                    if Path(name).suffix.lower() in SKIP_SUFFIXES:
                        continue
                    try:
                        mtime = entry.stat().st_mtime
                        if cutoff <= mtime <= ceiling:
                            found.append(entry)
                    except OSError:
                        continue

    groups: dict[str, dict] = {}
    for path in found:
        label = _group_label(path, watch_dirs)
        g = groups.setdefault(label, {"count": 0, "exts": {}, "samples": []})
        g["count"] += 1
        ext = path.suffix.lower() or "(no ext)"
        g["exts"][ext] = g["exts"].get(ext, 0) + 1
        if len(g["samples"]) < 6:
            g["samples"].append(_display(path, watch_dirs))

    return {
        "total": len(found),
        "groups": [
            {
                "label": label,
                "count": g["count"],
                "exts": sorted(g["exts"].items(), key=lambda kv: -kv[1]),
                "samples": g["samples"],
            }
            for label, g in sorted(groups.items(), key=lambda kv: -kv[1]["count"])
        ],
    }


def collect_git_subjects(watch_dirs: list[Path], since: datetime, until: datetime | None = None) -> list[dict]:
    """Commit subjects from repos under the watch dirs, metadata only."""
    until = until or datetime.now().astimezone()
    repos: list[Path] = []
    for root in watch_dirs:
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack and len(repos) < MAX_GIT_REPOS:
            current, depth = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if not entry.is_dir() or entry.name in SKIP_DIR_NAMES:
                    continue
                if (entry / ".git").exists():
                    if len(repos) < MAX_GIT_REPOS:
                        repos.append(entry)
                elif depth < MAX_DEPTH - 1:
                    stack.append((entry, depth + 1))

    results: list[dict] = []
    since_arg = f"--since={since.isoformat()}"
    until_arg = f"--until={until.isoformat()}"
    for repo in repos:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), "log", since_arg, until_arg, "--pretty=%s", "--no-merges"],
                capture_output=True,
                timeout=10,
            )
            if proc.returncode != 0:
                continue
            subjects = [
                line.strip()
                for line in proc.stdout.decode(errors="replace").splitlines()
                if line.strip()
            ]
            if subjects:
                results.append({"repo": repo.name, "subjects": subjects[:MAX_SUBJECTS_PER_REPO]})
        except (subprocess.SubprocessError, OSError):
            continue
    return results


def render_files_activity(scan: dict, git: list[dict]) -> str:
    """Compact transcript block for the daily-report prompt."""
    if not scan["total"] and not git:
        return "Files touched: none found in the window."
    lines: list[str] = []
    if scan["total"]:
        lines.append(f"Files modified in the window ({scan['total']} total, by project):")
        for g in scan["groups"][:12]:
            exts = ", ".join(f"{ext}×{n}" for ext, n in g["exts"][:4])
            lines.append(f"- {g['label']}: {g['count']} files ({exts})")
            lines.append(f"    e.g. {g['samples'][0]}")
    if git:
        lines.append("")
        lines.append("Git commits in the window:")
        for r in git:
            lines.append(f"- {r['repo']}:")
            for s in r["subjects"]:
                lines.append(f"    · {s}")
    return "\n".join(lines)


def _group_label(path: Path, watch_dirs: list[Path]) -> str:
    """Project folder name: first component under the watch dir."""
    for root in watch_dirs:
        try:
            rel = path.relative_to(root)
            parts = rel.parts
            return parts[0] if len(parts) > 1 else f"{root.name}/ (loose files)"
        except ValueError:
            continue
    return path.parent.name


def _display(path: Path, watch_dirs: list[Path]) -> str:
    for root in watch_dirs:
        try:
            return "~/…/" + "/".join(path.relative_to(root).parts[-2:])
        except ValueError:
            continue
    return path.name
