"""Vault endpoints: planning, conflicts and health.

Separate from `notes` because these are about the *mirror*, not about a note.
The distinction matters for a boring reason: `/api/notes/{id}` treats the first
path segment as an id, so anything vault-shaped filed under it collides with a
note called "vault".
"""

from __future__ import annotations

from fastapi import APIRouter, Request

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
