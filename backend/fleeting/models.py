"""Pydantic API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ActionItem(BaseModel):
    id: str
    text: str
    done: bool = False
    priority: Literal["P1", "P2", "P3"] = "P2"
    due_date: str | None = None
    repo: str | None = None
    completed_at: str | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> str:
        if v is None:
            return "P2"
        v_str = str(v).strip().upper()
        if v_str in ("P1", "P2", "P3"):
            return v_str
        raise ValueError("priority must be one of 'P1', 'P2', 'P3'")

    @field_validator("repo", mode="before")
    @classmethod
    def normalize_repo(cls, v: Any) -> str | None:
        if v is None:
            return None
        v_str = str(v).strip().lower()
        return v_str or None

    @field_validator("due_date", mode="before")
    @classmethod
    def normalize_due_date(cls, v: Any) -> str | None:
        if not v:
            return None
        v_str = str(v).strip()
        try:
            datetime.strptime(v_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError("due_date must be in 'YYYY-MM-DD' format")
        return v_str


class TaskOut(ActionItem):
    note_id: str
    note_title: str = ""
    created_at: str


class TaskCreateIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    priority: Literal["P1", "P2", "P3"] = "P2"
    due_date: str | None = None
    repo: str | None = None
    note_id: str | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> str:
        if v is None:
            return "P2"
        v_str = str(v).strip().upper()
        if v_str in ("P1", "P2", "P3"):
            return v_str
        raise ValueError("priority must be one of 'P1', 'P2', 'P3'")

    @field_validator("repo", mode="before")
    @classmethod
    def normalize_repo(cls, v: Any) -> str | None:
        if v is None:
            return None
        v_str = str(v).strip().lower()
        return v_str or None

    @field_validator("due_date", mode="before")
    @classmethod
    def normalize_due_date(cls, v: Any) -> str | None:
        if not v:
            return None
        v_str = str(v).strip()
        try:
            datetime.strptime(v_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError("due_date must be in 'YYYY-MM-DD' format")
        return v_str


class TaskUpdateIn(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    done: bool | None = None
    priority: Literal["P1", "P2", "P3"] | None = None
    due_date: str | None = None
    repo: str | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> str | None:
        if v is None:
            return None
        v_str = str(v).strip().upper()
        if v_str in ("P1", "P2", "P3"):
            return v_str
        raise ValueError("priority must be one of 'P1', 'P2', 'P3'")

    @field_validator("repo", mode="before")
    @classmethod
    def normalize_repo(cls, v: Any) -> str | None:
        if v is None:
            return None
        v_str = str(v).strip().lower()
        return v_str or None

    @field_validator("due_date", mode="before")
    @classmethod
    def normalize_due_date(cls, v: Any) -> str | None:
        if not v:
            return None
        v_str = str(v).strip()
        try:
            datetime.strptime(v_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError("due_date must be in 'YYYY-MM-DD' format")
        return v_str


class NoteOut(BaseModel):
    id: str
    type: str
    title: str
    summary: str
    raw_text: str
    tags: list[str]
    action_items: list[ActionItem]
    source: dict
    audio_path: str | None = None
    status: str
    error: str | None = None
    pinned: bool
    archived: bool
    created_at: str
    updated_at: str
    processed_at: str | None = None
    snippet: str | None = None  # only present on search results
    score: float | None = None
    match_type: str | None = None
    capture_id: str | None = None
    source_title: str | None = None


class CaptureTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    capture_id: str | None = Field(default=None, max_length=64)
    source_title: str | None = Field(default=None, max_length=300)


class CaptureYouTubeIn(BaseModel):
    url: str = Field(min_length=5, max_length=2000)
    capture_id: str | None = Field(default=None, max_length=64)
    source_title: str | None = Field(default=None, max_length=300)


class NoteUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None
    pinned: bool | None = None
    archived: bool | None = None
    action_items: list[ActionItem] | None = None


class SettingsIn(BaseModel):
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    vault_dir: str | None = None
    vault_sync: bool | None = None
    llm_provider: str | None = Field(default=None, pattern="^(ollama|lmstudio|custom|none)$")
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_secs: int | None = Field(default=None, ge=5, le=600)
    # Absent or null keeps the stored key; an empty string clears it. The stored
    # value is never returned by GET, so the UI cannot accidentally echo it back.
    llm_api_key: str | None = None
    transcribe_model: str | None = Field(default=None, pattern="^(tiny|base|small|medium)$")
    transcribe_language: str | None = None
    yt_transcribe_fallback: bool | None = None
    yt_max_duration_min: int | None = Field(default=None, ge=5, le=240)
    desktop_notifications: bool | None = None
    activity_enabled: bool | None = None
    activity_poll_secs: int | None = Field(default=None, ge=5, le=300)
    activity_idle_after_min: int | None = Field(default=None, ge=1, le=60)
    activity_excluded_apps: str | None = Field(default=None, max_length=500)
    activity_auto_daily_log: bool | None = None
    activity_watch_dirs: str | None = Field(default=None, max_length=1000)
    activity_mirror_daily_log: bool | None = None
    activity_auto_weekly_log: bool | None = None
    activity_retention_days: int | None = Field(default=None, ge=1, le=3650)


class ChatMessage(BaseModel):
    role: str  # 'user' | 'assistant' | 'system'
    content: str


class SourceRef(BaseModel):
    id: str
    title: str
    type: str
    kind: str = "note"  # 'note' | 'task' | 'log'
    snippet: str = ""


class LLMProbeIn(BaseModel):
    """Optional overrides so the UI can probe values the user has not saved yet."""

    provider: str | None = Field(default=None, pattern="^(ollama|lmstudio|custom|none)$")
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class AssistantChatIn(BaseModel):
    messages: list[ChatMessage]
    repo: str | None = None
    type: str | None = None
    confirm: bool = False


class AssistantChatOut(BaseModel):
    message: ChatMessage
    sources: list[SourceRef]
    context_used: dict[str, int]
    pending_action: dict | None = None


class AssistantSuggestionsOut(BaseModel):
    suggestions: list[str]

