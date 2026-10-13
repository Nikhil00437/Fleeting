"""#455: counts and samples before anything bulk gets destroyed.

Added after `POST /api/trash/empty` was called as a probe and did exactly that:
one note, already in the trash, permanently gone. The endpoint was not dangerous
by design — emptying the trash is a real thing to want. The defect was that a
single POST destroyed data with no count, no sample, and nothing that made a
wrong call visible.

The shape is the same for every bulk destructive operation, so it lives here
once rather than being re-derived per endpoint:

- **`GET` the preview.** Asking what would happen never changes anything.
- **`POST` without `confirm` is a `409` carrying that preview.** Not a 400 and
  not a silent success — the caller asked a question and the answer is "here is
  what that costs, confirm first".
- **An empty result is not a prompt.** Nothing to delete means the operation
  succeeds and says zero. A dialog offering to delete nothing is how people
  learn to click through dialogs.

`require_confirm` raises with the preview attached, so a UI can render the
confirmation from the refusal alone and does not have to call twice.
"""

from __future__ import annotations

from typing import Any, Sequence

from fastapi import HTTPException

# How many rows a preview shows. Bounded because the preview is rendered in a
# dialog, and because an endpoint that returns every affected row turns itself
# into a data export.
PREVIEW_SAMPLES = 5


def preview(
    count: int, samples: Sequence[Any], **extra: Any
) -> dict[str, Any]:
    """The standard preview body, so both endpoints report the same shape."""
    return {"count": count, "samples": list(samples)[:PREVIEW_SAMPLES], **extra}


def require_confirm(body: Any, confirmed: bool, detail: dict[str, Any]) -> None:
    """Refuse a destructive bulk call that was not confirmed.

    Raises `409` with the preview inside `detail`, so the UI can show the
    confirmation from the refusal itself rather than issuing a second request
    that might disagree.
    """
    if confirmed or detail["count"] == 0:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "error": "confirmation_required",
            "message": (
                f"This would affect {detail['count']} item"
                f"{'s' if detail['count'] != 1 else ''}. Send confirm=true to go ahead."
            ),
            **detail,
        },
    )