"""#136: the panic button. See `services/forget.py` for why it only deletes what
was *created* in the window."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..services.forget import forget

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
