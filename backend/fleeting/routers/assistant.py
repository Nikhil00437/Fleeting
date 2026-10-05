"""Assistant chat and suggestions router."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..events import sse_format

from ..models import AssistantChatIn, AssistantChatOut, AssistantSuggestionsOut
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


@router.get("/suggestions", response_model=AssistantSuggestionsOut)
def suggestions(request: Request) -> AssistantSuggestionsOut:
    """Get dynamic starter prompt suggestions based on current database state."""
    st = request.app.state.st
    prompts = get_assistant_suggestions(st.db, st.cfg)
    return AssistantSuggestionsOut(suggestions=prompts)
