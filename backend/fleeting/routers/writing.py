"""Writing assists: #446 rewrite, #447 titles, #451 style guide.

Deliberately small — three endpoints over one service. Everything else in the
writing cluster (#445 draft-from-notes, #448 assembler, #449 email) takes a
*set* of notes rather than one blob, so it belongs with the collection tools
rather than here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import writing

router = APIRouter(prefix="/api/writing", tags=["writing"])


class RewriteIn(BaseModel):
    text: str
    style: str


class TitlesIn(BaseModel):
    text: str
    current_title: str | None = None


def _guide(request: Request) -> str:
    return request.app.state.st.cfg.writing.style_guide


@router.get("/rewrite-styles")
def rewrite_styles() -> list[str]:
    """#446 the menu, so the UI cannot offer a style the service rejects."""
    return list(writing.REWRITE_STYLES)


@router.post("/rewrite")
async def rewrite(request: Request, body: RewriteIn) -> dict:
    """#446 rewrite text. Returns the text; the caller decides what to do with it.

    Nothing is persisted — a rewrite the user did not accept must not have
    replaced their words.
    """
    st = request.app.state.st
    try:
        out = await writing.rewrite(
            body.text, body.style, st.cfg.llm, style_guide=_guide(request)
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except writing.LLMUnavailable as exc:
        raise HTTPException(502, f"model unavailable: {exc}") from exc
    return {"text": out, "style": body.style}


@router.post("/titles")
async def titles(request: Request, body: TitlesIn) -> dict:
    """#447 alternative titles. Always 200 with a list, empty on any failure."""
    st = request.app.state.st
    out = await writing.suggest_titles(
        body.text,
        st.cfg.llm,
        style_guide=_guide(request),
        current_title=body.current_title,
    )
    return {"titles": out}
