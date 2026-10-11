"""Assistant chat and suggestions router."""

from __future__ import annotations

from datetime import datetime

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..events import EventBus, sse_format

from ..models import AssistantChatIn, AssistantChatOut, AssistantSuggestionsOut, PinNoteIn, ScheduleJobIn, ScheduleToggleIn
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
        chat_id=body.chat_id,
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
                chat_id=body.chat_id,
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


@router.get("/note-suggestions")
def note_suggestions(request: Request, note_id: str = Query(..., min_length=1)) -> list[str]:
    """#108 questions worth asking about one note.

    Empty for a sensitive (#26) or trashed note — see note_suggestions.
    """
    from ..services.assistant import note_suggestions as build

    return build(request.app.state.st.db, note_id)


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


@router.get("/chats/{chat_id}/context")
def pinned_context(chat_id: str, request: Request) -> dict:
    """#101 the notes pinned into this thread, so the panel can render them."""
    from ..services.pinned_context import pinned_notes

    notes = pinned_notes(request.app.state.st.db, chat_id)
    return {
        "chat_id": chat_id,
        "items": [
            {"id": n["id"], "title": n.get("title") or "(untitled)",
             "snippet": (n.get("summary") or n.get("raw_text") or "")[:160]}
            for n in notes
        ],
    }


@router.post("/chats/{chat_id}/context")
def pin_into_context(chat_id: str, body: PinNoteIn, request: Request) -> dict:
    """#101 attach a note to a thread, so it is in context whether or not a
    query would ever rank it."""
    from ..services.pinned_context import pin_note

    try:
        ids = pin_note(request.app.state.st.db, chat_id, body.note_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "ids": ids}


@router.delete("/chats/{chat_id}/context/{note_id}")
def unpin_from_context(chat_id: str, note_id: str, request: Request) -> dict:
    """#101 detach a note again."""
    from ..services.pinned_context import unpin_note

    return {"ok": True, "ids": unpin_note(request.app.state.st.db, chat_id, note_id)}


@router.get("/jobs")
def list_scheduled_jobs(request: Request) -> list[dict]:
    """#106 the scheduled jobs, with when each next runs."""
    from ..services.schedules import list_jobs, next_run_after

    now = datetime.now().astimezone()
    out = []
    for sched in list_jobs(request.app.state.st.db):
        row = sched.to_dict()
        row["next_run"] = next_run_after(sched, now) if sched.enabled else None
        out.append(row)
    return out


@router.post("/jobs")
def create_scheduled_job(body: ScheduleJobIn, request: Request) -> dict:
    """#106 create a job. A schedule it cannot read is refused, not guessed."""
    from ..services.schedules import create_job

    try:
        sched = create_job(request.app.state.st.db, body.prompt, body.schedule)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return sched.to_dict()


@router.post("/jobs/{job_id}/toggle")
def toggle_scheduled_job(job_id: str, body: ScheduleToggleIn, request: Request) -> dict:
    from ..services.schedules import set_enabled

    sched = set_enabled(request.app.state.st.db, job_id, body.enabled)
    if not sched:
        raise HTTPException(404, "job not found")
    return sched.to_dict()


@router.delete("/jobs/{job_id}")
def remove_scheduled_job(job_id: str, request: Request) -> dict:
    from ..services.schedules import delete_job

    delete_job(request.app.state.st.db, job_id)
    return {"deleted": job_id}
