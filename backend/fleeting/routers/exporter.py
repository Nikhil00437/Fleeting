"""#143: a redacted export.

An export is the moment notes stop being private, and "share my notes with a
colleague" and "share my notes with a model I do not control" are the same
request. So `{"redact": true}` runs every note through `services/redact` on the
way out and returns what was found alongside it.

Nothing is written back. The export renders markdown from the database and
redacts that string — re-saving the redacted text would quietly destroy the
original while claiming to have shared a copy, and there is a test for it.

A limit is applied because an export is a synchronous response: a database with
tens of thousands of notes would otherwise be one very long request. The count
that came back says how many were included, so a truncated export is visible
rather than silently partial.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..services.markdown import render_note_md
from ..services.redact import redact

router = APIRouter(prefix="/api", tags=["export"])
log = logging.getLogger("fleeting.export")

# An export is a synchronous response. Beyond this the caller should page.
MAX_NOTES = 2000


class ExportIn(BaseModel):
    redact: bool = False
    #: Names the caller knows, because no regex can find them.
    names: list[str] = Field(default_factory=list, max_length=200)
    limit: int = Field(default=MAX_NOTES, ge=1, le=MAX_NOTES)


@router.post("/export")
def export_notes(body: ExportIn, request: Request) -> dict:
    st = request.app.state.st
    notes = st.db.list_notes(limit=body.limit)
    if not notes:
        return {"markdown": "", "notes": 0, "redacted": {}}

    totals: dict[str, int] = {}
    parts: list[str] = []
    for note in notes:
        text = render_note_md(note)
        if body.redact:
            text, hits = redact(text, body.names)
            for label, n in hits.items():
                totals[label] = totals.get(label, 0) + n
        parts.append(text)

    if len(notes) >= body.limit:
        log.info("export truncated at the %d note limit", body.limit)
    return {
        "markdown": "\n\n---\n\n".join(parts),
        "notes": len(notes),
        "redacted": totals,
    }