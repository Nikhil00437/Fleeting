"""Pydantic API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    id: str
    text: str
    done: bool = False


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


class CaptureTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    title: str = ""
    tags: list[str] = Field(default_factory=list)


class CaptureYouTubeIn(BaseModel):
    url: str = Field(min_length=5, max_length=2000)


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
    llm_provider: str | None = Field(default=None, pattern="^(ollama|lmstudio|none)$")
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_secs: int | None = Field(default=None, ge=5, le=600)
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
