"""#136: the panic button. See `services/forget.py` for why it only deletes what
was *created* in the window."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..services.forget import forget
from ..services.retention import parse_policies

router = APIRouter(prefix="/api", tags=["privacy"])


class ForgetIn(BaseModel):
    minutes: int = Field(default=15, ge=1, le=60 * 24 * 7)
    confirm: bool = False


@router.post("/forget")
def forget_endpoint(body: ForgetIn, request: Request) -> dict:
    st = request.app.state.st
    return forget(
        st.db,
        body.minutes,
        body.confirm,
        bus=getattr(st, "bus", None),
        on_note_delete=lambda row: _drop_side_files(st, row["id"]),
    )


def _drop_side_files(st, note_id: str) -> None:
    """Audio, attachments and the vault export for a note that is going away.

    Called before the row is deleted because `delete_note` needs the row's own
    paths — it looks them up, and after the fact they are gone.
    """
    from ..services import markdown

    note = st.db.get_note(note_id)
    if not note:
        return
    try:
        markdown.remove_note(st.cfg.paths, note)
    except Exception:
        # A stray vault file must not stop the delete it belongs to.
        import logging

        logging.getLogger("fleeting.forget").warning(
            "could not remove vault file for %s", note_id, exc_info=True
        )


class PruneIn(BaseModel):
    """#138. `policies` is passed per call so the preview and the run cannot
    disagree about what is configured."""

    policies: str | None = None
    confirm: bool = False


@router.get("/retention")
def retention_status(request: Request) -> dict:
    """#138: what is configured, what was understood, and what is due.

    `ignored` is the point of the first field: a typo in a config file should
    not stop the app starting, but it should not also be invisible.
    """
    from ..services.retention import describe_policies, preview_due

    spec = request.app.state.st.cfg.notes.retention_by_source
    return {**describe_policies(spec), "due": preview_due(request.app.state.st.db, parse_policies(spec))}


@router.post("/retention/prune")
def prune_retention(body: PruneIn, request: Request) -> dict:
    """Age out what is due, into the trash. Guarded like every other bulk
    destructive call, and audited (#140) — a policy firing on a timer is exactly
    the sort of thing you want in the audit six months later."""
    from ..services.retention import prune

    st = request.app.state.st
    spec = body.policies if body.policies is not None else st.cfg.notes.retention_by_source
    return prune(st.db, spec, body.confirm, bus=getattr(st, "bus", None))
