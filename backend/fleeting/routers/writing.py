"""Writing assists: #445-#449 composition, #446 rewrite, #447 titles,
#451 style guide, #105 saved prompts.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..services import writing
from ..services.prompts import create_prompt, delete_prompt, list_prompts, update_prompt

router = APIRouter(prefix="/api/writing", tags=["writing"])

# #105 lives under its own prefix but ships with this router: a saved prompt
# is a writing prompt, and splitting it would only add a file.
prompts_router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptIn(BaseModel):
    name: str
    body: str


@prompts_router.get("")
def all_prompts(request: Request, q: str = "") -> list[dict]:
    """#105. Newest first, searchable by name or by body."""
    return list_prompts(request.app.state.st.db, q=q)


@prompts_router.post("")
def add_prompt(request: Request, body: PromptIn) -> dict:
    try:
        return create_prompt(request.app.state.st.db, body.name, body.body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@prompts_router.patch("/{prompt_id}")
def edit_prompt(prompt_id: str, request: Request, body: PromptIn) -> dict:
    try:
        row = update_prompt(request.app.state.st.db, prompt_id, name=body.name, body=body.body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "prompt not found")
    return row


@prompts_router.delete("/{prompt_id}")
def remove_prompt(prompt_id: str, request: Request) -> None:
    if not delete_prompt(request.app.state.st.db, prompt_id):
        raise HTTPException(404, "prompt not found")


class RewriteIn(BaseModel):
    text: str
    style: str


class TitlesIn(BaseModel):
    text: str
    current_title: str | None = None


class ComposeIn(BaseModel):
    """A set of notes. #448 also accepts a tag to resolve the set from."""

    note_ids: list[str] = Field(default_factory=list)
    tag: str | None = None
    mode: str = "outline"
    kind: str = "blog"


def _collect(request: Request, body: ComposeIn) -> list[dict]:
    """Resolve the source notes, refusing the set rather than guessing.

    A tag resolves through the same search path as a saved query, so an
    assembler over "everything tagged homelab" sees exactly what search would.
    """
    st = request.app.state.st
    notes = [st.db.get_note(nid) for nid in body.note_ids]
    if body.tag:
        # Same entry point the search box uses, so an assembler over
        # "everything tagged homelab" sees exactly what search would.
        from ..services.semantic_search import hybrid_search

        found = hybrid_search(
            st.db, f"tag:{body.tag.lstrip('#')}", st.cfg, mode="keyword", limit=50
        )
        have = {n["id"] for n in notes if n}
        notes.extend(n for n in found if n["id"] not in have)
    return [n for n in notes if n]


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


@router.post("/draft")
async def draft(request: Request, body: ComposeIn) -> dict:
    """#445 an outline or first draft from a set of notes.

    422 when nothing usable survives the filter — a silent empty draft would
    look like a successful generation.
    """
    st = request.app.state.st
    try:
        out = await writing.draft_from_notes(
            _collect(request, body), st.cfg.llm,
            mode=body.mode, style_guide=_guide(request),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except writing.LLMUnavailable as exc:
        raise HTTPException(502, f"model unavailable: {exc}") from exc
    return {"markdown": out, "mode": body.mode}


@router.post("/assemble")
async def assemble(request: Request, body: ComposeIn) -> dict:
    """#448 a blog post or newsletter from a set of notes or a tag."""
    st = request.app.state.st
    try:
        out = await writing.assemble_post(
            _collect(request, body), st.cfg.llm,
            kind=body.kind, style_guide=_guide(request),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except writing.LLMUnavailable as exc:
        raise HTTPException(502, f"model unavailable: {exc}") from exc
    return {"markdown": out, "kind": body.kind}


@router.post("/email")
async def email(request: Request, body: TitlesIn) -> dict:
    """#449 turn text into an email. No recipient is ever invented."""
    st = request.app.state.st
    try:
        out = await writing.to_email(body.text, st.cfg.llm, style_guide=_guide(request))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except writing.LLMUnavailable as exc:
        raise HTTPException(502, f"model unavailable: {exc}") from exc
    return out
