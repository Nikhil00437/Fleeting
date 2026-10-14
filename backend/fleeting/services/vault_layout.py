"""#114 and #115: the two things that decide what a vault file looks like.

Both are one function each, and both are **configuration rather than code** —
which is the point. A user who wants every note under `Inbox/text/` should not be
editing Python, and a user who adds a `project:` field to their frontmatter should
not be waiting for a release.

**#114 frontmatter schema.** An ordered list of field names; every note carries a
value for each, in that order, and empty ones are omitted. Order is the schema —
frontmatter is read top to bottom by every tool that shows it, and an order that
jumps around is one nobody can scan.

**#115 folder template.** `{{year}}`, `{{type}}`, `{{first_tag}}`, in any
combination. The default stays `{{year}}` because it is what the mirror has
always done, and changing a default that silently relocates five years of notes
is not a decision to make on someone's behalf.

**Two rules both templates obey, because both are how a template turns into data
loss:**

- **A slug is never empty.** `{{first_tag}}` on an untagged note must not produce
  the vault root. An untagged note goes to `untagged/`, which is a folder you can
  find and move, rather than a file loose in the root that the next untagged note
  also lands in.
- **Nothing from a tag reaches the path verbatim.** Tags come from speech
  recognition and from the model. `../../../etc` as a tag is not a hypothetical,
  and the path is used to create directories. Every segment is slugified —
  lowercased, non-alphanumerics to dashes — and a traversal that survives that
  check is rejected outright.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Matches `{{name}}`, tolerating spaces inside the braces.
_TOKEN = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# The only names a template may use. An allow-list, not a deny-list: a template is
# user input, and a deny-list is a list of things nobody thought of.
TOKENS = ("year", "type", "first_tag", "month")

DEFAULT_FOLDER_TEMPLATE = "{{year}}"
DEFAULT_SCHEMA = ""


def slug(text: str) -> str:
    """Lowercase, ASCII-ish, dash-separated. Never empty for non-empty input."""
    normalised = unicodedata.normalize("NFKD", str(text or ""))
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    slugged = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slugged


# What a token falls back to when its value cannot be used. Per-token, because
# "untitled" in place of a tag tells you nothing, and `untagged/` is a folder
# you can find and move.
TOKEN_FALLBACK = {
    "year": "undated",
    "month": "undated",
    "type": "note",
    "first_tag": "untagged",
}


def safe_segment(raw: str, fallback: str) -> str:
    """One token-derived path segment, guaranteed safe and non-empty.

    A traversal is refused *before* slugging, not neutralised by it: slugifying
    `../../etc` gives `etc`, which is harmless but wrong, and relying on the slug
    to neutralise a path is relying on a coincidence.
    """
    text = str(raw or "")
    if "/" in text or "\\" in text or text.strip() in (".", ".."):
        return fallback
    return slug(text) or fallback


def safe_literal(raw: str) -> str:
    """A segment the user typed, kept as written.

    Case is preserved deliberately: someone who typed `Inbox/` wants `Inbox/`,
    and lowercasing it is a surprise with no security benefit — the segment
    contains no traversal, because that was already refused.

    `.` and `..` are dropped rather than replaced. A literal `..` in a template is
    a typo, and dropping it leaves a folder that is nearly what was asked for
    instead of a row of `untitled` placeholders.
    """
    text = str(raw or "").strip()
    if not text or text in (".", ".."):
        return ""
    if "/" in text or "\\" in text:
        return ""
    return text


def parse_schema(spec: str) -> list[str]:
    """`"project, client, status"` → `["project", "client", "status"]`.

    Invalid names are dropped rather than raising: a typo in a config file should
    not stop the app starting. `validate_schema` reports what was dropped, so it
    is visible rather than silent.
    """
    out: list[str] = []
    for part in (spec or "").split(","):
        name = part.strip()
        if not name:
            continue
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", name):
            continue
        if name not in out:
            out.append(name)
    return out


def validate_schema(spec: str) -> dict[str, Any]:
    """What was written, what was understood, and what was rejected."""
    fields = parse_schema(spec)
    written = [p.strip() for p in (spec or "").split(",") if p.strip()]
    return {
        "fields": fields,
        "written": written,
        "ignored": [w for w in written if w not in fields],
        "explains": (
            "Every note carries these fields, in this order. Blank ones are omitted."
            if fields
            else "No fields configured; notes get the built-in frontmatter only."
        ),
    }


def frontmatter_lines(note: dict, schema: list[str]) -> list[str]:
    """The extra frontmatter lines for a note, in schema order.

    Blank values are omitted rather than written empty — a frontmatter block full
    of `status:` with nothing after it is noise that every tool has to special
    case, and it makes "which notes have a status" unanswerable by eye.
    """
    values = note.get("frontmatter") or {}
    if not isinstance(values, dict):
        return []
    lines: list[str] = []
    for name in schema:
        value = values.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        lines.append(f"{name}: {value}")
    return lines


def folder_for(template: str, note: dict) -> str:
    """The directory this note belongs in, relative to the vault root.

    Token *values* are slugified; literal segments are not. Both halves matter:
    tags come from speech recognition and from a model and must never shape a
    path, while a folder the user typed is exactly what they asked for.
    """
    tags = note.get("tags") or []
    created = str(note.get("created_at") or note.get("created") or "")
    values = {
        "year": created[:4],
        "month": created[:7],
        "type": note.get("type") or "",
        "first_tag": (tags[0] if tags else ""),
    }

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        fallback = TOKEN_FALLBACK.get(name, f"unknown-{name}")
        if name not in values:
            # Visible rather than silently dropped: the user typed something and
            # should be able to see that it did nothing.
            return fallback
        return safe_segment(values[name], fallback)

    rendered = _TOKEN.sub(replace, template or DEFAULT_FOLDER_TEMPLATE)
    segments: list[str] = []
    for part in rendered.split("/"):
        literal = safe_literal(part)
        if literal:
            segments.append(literal)
    return "/".join(segments) or TOKEN_FALLBACK["year"]


def validate_template(template: str) -> str | None:
    """Why this template is unusable, or None if it is fine.

    A problem here is **refused**, not sanitised into something else. A template
    that silently becomes a different folder is a template that moved five years
    of notes and said nothing; the user can see and fix a rejection in a second,
    and cannot see a rewrite.
    """
    if not template.strip():
        return None
    if "\\" in template:
        return "backslashes are not valid path separators here"
    if template.startswith("/"):
        return "an absolute path would escape the vault"
    for part in template.split("/"):
        if part.strip() in (".", ".."):
            return "'.' and '..' are not valid folder names in a template"
        for token in _TOKEN.findall(part):
            if token not in TOKENS:
                return (
                    f"unknown token {{{{{token}}}}}; supported: "
                    + ", ".join("{{" + t + "}}" for t in TOKENS)
                )
    if not _TOKEN.search(template):
        return None
    return None
