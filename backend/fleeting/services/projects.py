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
# A path segment that looks like a project: starts with a letter, has no dot
# (rules out filenames), no spaces.
_NAME_RE = re.compile(r"(?<![\w.-])([A-Za-z][\w-]{1,40})(?![\w.-/])")

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

    # A bare project name only counts when it opens the title (a tab or
    # window name), otherwise "fleeting" in a sentence would match everything.
    m = _NAME_RE.fullmatch(head)
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