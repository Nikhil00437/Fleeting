"""Assistant chat and suggestions router."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..events import EventBus, sse_format

from ..models import AssistantChatIn, AssistantChatOut, AssistantSuggestionsOut
from ..services import chatlog
from ..services.actions import undo_action
from ..services.assistant import (
    SLASH_COMMANDS,
    ask_assistant,
    ask_assistant_stream,
    build_assistant_context,
    get_assistant_suggestions,
)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatOut)
async def chat(request: Request, body: AssistantChatIn) -> AssistantChatOut:
    """Chat with the grounded Ask Fleeting assistant."""
    st = request.app.state.st
    result = await ask_assistant(
        [m.model_dump() for m in body.messages],
        st.db,
        st.cfg,
        bus=getattr(st, "bus", None),
        repo=body.repo,
        filter_type=body.type,
        confirm=body.confirm,
    )
    return AssistantChatOut(**result)


@router.post("/chat/stream")
async def chat_stream(request: Request, body: AssistantChatIn) -> StreamingResponse:
    """Streaming variant of /chat — SSE deltas, then a final done event."""
    st = request.app.state.st

    async def gen():
        try:
            async for event in ask_assistant_stream(
                [m.model_dump() for m in body.messages],
                st.db,
                st.cfg,
                bus=getattr(st, "bus", None),
                repo=body.repo,
                filter_type=body.type,
                confirm=body.confirm,
            ):
                yield sse_format(json.dumps(event))
        except Exception as exc:  # never leave the client hanging
            yield sse_format(json.dumps({"type": "error", "detail": str(exc)}))

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ChatHistoryIn(BaseModel):
    messages: list[dict] = Field(default_factory=list)


class ChatPinIn(BaseModel):
    pinned: bool


class UndoIn(BaseModel):
    undo: str


@router.get("/history")
def chat_history(
    request: Request,
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
    pinned_only: bool = False,
) -> list[dict]:
    """#111 conversation history, newest first, pinned on top."""
    return chatlog.list_chats(request.app.state.st.db, q=q, limit=limit, pinned_only=pinned_only)


@router.post("/history/{chat_id}")
def save_chat_history(request: Request, chat_id: str, body: ChatHistoryIn) -> dict:
    """The client posts the thread it already has; upsert keyed by its id."""
    return chatlog.save_chat(request.app.state.st.db, chat_id, body.messages)


@router.patch("/history/{chat_id}")
def pin_chat_history(request: Request, chat_id: str, body: ChatPinIn) -> dict:
    row = chatlog.set_pinned(request.app.state.st.db, chat_id, body.pinned)
    if row is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return row


@router.delete("/history/{chat_id}", status_code=204)
def delete_chat_history(request: Request, chat_id: str) -> None:
    if not chatlog.delete_chat(request.app.state.st.db, chat_id):
        raise HTTPException(status_code=404, detail="conversation not found")


@router.get("/context-preview")
def context_preview(
    request: Request,
    q: str = "",
    repo: str | None = None,
    type: str | None = None,
) -> dict:
    """#453: the exact context that would be sent, without calling the model.

    The same function the assistant calls, so the preview cannot drift from the
    real request. Nothing is stored — a preview is a read.
    """
    st = request.app.state.st
    queries: list[str] = []
    context_text, sources, context_used = build_assistant_context(
        q, st.db, st.cfg, repo=repo, filter_type=type, queries=queries
    )
    return {
        "query": q,
        "context": context_text,
        "sources": sources,
        "context_used": context_used,
        "queries": queries or ([q] if q else []),
    }


@router.get("/traces")
def llm_traces(
    request: Request,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    """#112: what each recent LLM call actually looked at."""
    return request.app.state.st.db.list_llm_traces(kind=kind, limit=limit)


@router.post("/undo")
async def undo(request: Request, body: UndoIn) -> dict:
    """#103: reverse one previously-executed assistant action by its token."""
    st = request.app.state.st
    return await undo_action(body.undo, st.db, st.cfg, getattr(st, "bus", None) or EventBus())


@router.get("/slash-commands")
def slash_commands() -> list[dict]:
    """#102 so the composer can show hints without hardcoding them."""
    return SLASH_COMMANDS


@router.get("/suggestions", response_model=AssistantSuggestionsOut)
def suggestions(request: Request) -> AssistantSuggestionsOut:
    """Get dynamic starter prompt suggestions based on current database state."""
    st = request.app.state.st
    prompts = get_assistant_suggestions(st.db, st.cfg)
    return AssistantSuggestionsOut(suggestions=prompts)
