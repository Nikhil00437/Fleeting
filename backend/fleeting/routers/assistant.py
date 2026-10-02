"""Assistant chat and suggestions router."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..models import AssistantChatIn, AssistantChatOut, AssistantSuggestionsOut
from ..services.assistant import ask_assistant, get_assistant_suggestions

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatOut)
async def chat(request: Request, body: AssistantChatIn) -> AssistantChatOut:
    """Chat with the grounded Ask Fleeting assistant."""
    st = request.app.state.st
    result = await ask_assistant(
        [m.model_dump() for m in body.messages],
        st.db,
        st.cfg,
        repo=body.repo,
        filter_type=body.type,
    )
    return AssistantChatOut(**result)


@router.get("/suggestions", response_model=AssistantSuggestionsOut)
def suggestions(request: Request) -> AssistantSuggestionsOut:
    """Get dynamic starter prompt suggestions based on current database state."""
    st = request.app.state.st
    prompts = get_assistant_suggestions(st.db, st.cfg)
    return AssistantSuggestionsOut(suggestions=prompts)
