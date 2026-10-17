"""#473 provenance, #475 a context snapshot, #478 live pointers.

Three small things that share one column, and the column is the whole design.

**`notes.provenance` is one short, queryable string.** `source` already holds a
JSON blob with the URL, the channel, the importer and the imported path — and a
JSON blob is not filterable. "Show me everything that came from a YouTube link"
is a question you cannot ask a JSON column, and #138's retention policies are
already keyed on `type`, which does not distinguish a note you dictated from
one a feed pushed at you.

**The value is derived once, from the note itself**, by `provenance_of`. A second
place that decides "what counts as a YouTube capture" is a second place that will
disagree with the first, and #459's lesson — decide once, reuse everywhere —
applies as much here as it did to the sensitive flag.

**#475 snapshots what you were doing when you captured.** The activity collector
already knows the project and branch on screen; without a snapshot at capture
time that context is gone by the time you want to write "why was I doing this".
The snapshot is taken *by the caller* — `provenance_of` stays a pure function of
the note, so it is testable without an activity collector.

**#478 is a pointer, not a copy.** A derived note keeps its `source.url` and gets
a rendered link back to whatever produced it. Storing the source's *content*
would make a change to the original invisible here, and a derived note that
silently diverges from its source is worse than one that points at it.
"""

from __future__ import annotations

from typing import Any

# The vocabulary. A closed set, because an open one turns into a taxonomy nobody
# can filter by — "youtube" and "YouTube" and "yt" are three filters for one
# thing.
YOUTUBE = "youtube"
VOICE = "voice"
TEXT = "text"
FILE = "file"
FEED = "rss"
PAGE = "url"
PDF = "pdf"
AUDIO = "audio"
MARKDOWN_IMPORT = "markdown"
VAULT = "vault"

SOURCES = (YOUTUBE, VOICE, TEXT, FILE, FEED, PAGE, PDF, AUDIO, MARKDOWN_IMPORT, VAULT)


def provenance_of(note: dict[str, Any]) -> str:
    """The one filterable provenance string for a note.

    Ordered by how *specific* the answer is, because `type` is the fallback and
    everything above it is a distinction worth making. A YouTube note and a
    dictated note are both "notes"; they are not the same provenance.
    """
    source = note.get("source") or {}
    if not isinstance(source, dict):
        source = {}

    imported = source.get("imported_from")
    if imported == "markdown-folder":
        return MARKDOWN_IMPORT
    if imported == "rss":
        return FEED
    if imported == "url":
        return PAGE
    if imported == "pdf":
        return PDF
    if imported == "audio":
        return AUDIO
    if source.get("feed"):
        return FEED
    if source.get("from_vault"):
        return VAULT
    if source.get("channel") and not source.get("url"):
        return VOICE

    note_type = str(note.get("type") or TEXT)
    if note_type == "youtube":
        return YOUTUBE
    if note_type == "voice":
        return VOICE
    if note_type == "file":
        return FILE
    return TEXT


def snapshot_context(activity_row: dict[str, Any] | None) -> dict[str, Any]:
    """#475: what the user was doing when the capture happened.

    A **snapshot**, deliberately. The activity collector keeps updating, so a
    live reference to "the current project" at read time would answer a question
    about *now* when the question was about the moment of capture. Six weeks
    later those are different answers.

    Empty rather than absent when there is no context: a note with `project: ""`
    is honest, and a missing key is indistinguishable from "we forgot to record
    it".
    """
    row = activity_row or {}
    return {
        "project": str(row.get("project") or ""),
        "branch": str(row.get("branch") or ""),
        "workspace": str(row.get("workspace") or ""),
        "app": str(row.get("app") or ""),
    }


def has_context(snapshot: dict[str, Any] | None) -> bool:
    """Is there anything worth showing? A snapshot of four empty strings is noise
    in a note's frontmatter."""
    return any(bool(v) for v in (snapshot or {}).values())


# ---- #478: pointers back to a source ---------------------------------------


def pointer_for(note: dict[str, Any]) -> dict[str, Any] | None:
    """Where this note came from, in a form worth rendering as a link.

    A **pointer, not a copy**: the source's content is not duplicated here, so a
    change to the original stays visible from the note that came out of it.
    """
    source = note.get("source") or {}
    if not isinstance(source, dict):
        return None
    url = str(source.get("url") or "").strip()
    feed = str(source.get("feed") or "").strip()
    path = str(source.get("imported_path") or "").strip()
    if url:
        return {"kind": "url", "label": _label(url), "target": url}
    if path:
        return {"kind": "file", "label": path.split("/")[-1], "target": path}
    if feed:
        return {"kind": "feed", "label": feed, "target": feed}
    return None


def _label(url: str) -> str:
    """A short host, so a link bar is readable rather than a wall of URLs."""
    from urllib.parse import urlparse

    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").replace("www.", "")
    if not host:
        return url[:60]
    return host + (parsed.path[:30] if parsed.path and parsed.path != "/" else "")