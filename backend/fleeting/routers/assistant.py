"""Assistant chat and suggestions router."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..events import sse_format

from ..models import AssistantChatIn, AssistantChatOut, AssistantSuggestionsOut
from ..services import chatlog
from ..services.assistant import (
    ask_assistant,
    ask_assistant_stream,
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


@router.get("/suggestions", response_model=AssistantSuggestionsOut)
def suggestions(request: Request) -> AssistantSuggestionsOut:
    """Get dynamic starter prompt suggestions based on current database state."""
    st = request.app.state.st
    prompts = get_assistant_suggestions(st.db, st.cfg)
    return AssistantSuggestionsOut(suggestions=prompts)
