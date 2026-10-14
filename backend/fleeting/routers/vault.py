"""Vault endpoints: planning, conflicts and health.

Separate from `notes` because these are about the *mirror*, not about a note.
The distinction matters for a boring reason: `/api/notes/{id}` treats the first
path segment as an id, so anything vault-shaped filed under it collides with a
note called "vault".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.post("/dry-run")
def vault_dry_run(request: Request) -> dict:
    """#122: what the vault sync would do, without doing any of it.

    Computed fresh on every call rather than remembered from a previous one: a
    plan that recorded conclusions and applied them later is stale by the time it
    acts, and that window is the one that matters.
    """
    from ..services.vault_dryrun import plan_all

    st = request.app.state.st
    return plan_all(st.cfg.paths, st.db)


class ResolveIn(BaseModel):
    """#113. Three choices, and deliberately no text merge.

    A three-way merge needs the content before either side changed, which means
    storing a second copy of every note somewhere that is not the note. The sync
    log keeps a hash — enough to tell the sides apart, not enough to blend them.
    """

    resolution: str


@router.get("/conflicts")
def vault_conflicts_list(request: Request) -> dict:
    """Re-derived on every call rather than read from the log, so a conflict that
    was resolved last week does not stay on the list forever."""
    from ..services.vault_conflicts import detect

    st = request.app.state.st
    return {"conflicts": detect(st.cfg.paths, st.db)}


@router.post("/conflicts/{note_id}")
def vault_conflicts_resolve(note_id: str, body: ResolveIn, request: Request) -> dict:
    """Apply one resolution. Every outcome is audited: six months later, with no
    memory of enabling anything."""
    from ..services.vault_conflicts import resolve

    st = request.app.state.st
    try:
        return resolve(st.cfg.paths, st.db, note_id, body.resolution, bus=getattr(st, "bus", None))
    except LookupError as exc:
        raise HTTPException(404, {"error": "no_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, {"error": "unknown_resolution", "message": str(exc)}) from exc
