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
    parent_id: str | None = None
    blocked_by: str | None = None
    estimate_min: int | None = None
    spent_min: int | None = None
    list: str = "inbox"
    context: str | None = None
    waiting_for: str | None = None
    follow_up_at: str | None = None
    recurrence: str | None = None
    sort_order: float = 0.0
    # #31: 'manual' priorities survive re-inference
    priority_source: str | None = None
    # #34: the app/window where this task can be done
    app_hint: str | None = None


def _coerce_blocked_by(v: Any) -> Any:
    """Accept a CSV string or a list of ids; the db layer stores CSV."""
    if isinstance(v, (list, tuple)):
        return ",".join(str(p).strip() for p in v if str(p).strip())
    return v


def _validate_plan_date(field: str):
    @field_validator(field, mode="before")
    @classmethod
    def _check(cls, v: Any) -> str | None:
        if not v:
            return None
        v_str = str(v).strip()
        try:
            datetime.strptime(v_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"{field} must be in 'YYYY-MM-DD' format")
        return v_str

    return _check


def _validate_minutes(field: str):
    @field_validator(field, mode="before")
    @classmethod
    def _check(cls, v: Any) -> int | None:
        if v in (None, ""):
            return None
        try:
            n = int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a whole number of minutes")
        if n < 0:
            raise ValueError(f"{field} must not be negative")
        return n

    return _check


class TaskCreateIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    priority: Literal["P1", "P2", "P3"] = "P2"
    due_date: str | None = None
    repo: str | None = None
    note_id: str | None = None
    parent_id: str | None = None
    blocked_by: str | None = None
    estimate_min: int | None = None
    spent_min: int | None = None
    list: Literal["inbox", "someday"] = "inbox"
    context: str | None = None
    waiting_for: str | None = None
    follow_up_at: str | None = None
    recurrence: str | None = Field(default=None, max_length=120)
    # #31: set when the caller picked the priority by hand
    priority_source: Literal["inferred", "manual"] | None = None
    # #34: where this task can be done ("firefox", "Terminal", a window title)
    app_hint: str | None = Field(default=None, max_length=200)

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

    @field_validator("blocked_by", mode="before")
    @classmethod
    def normalize_blocked_by(cls, v: Any) -> str | None:
        return _coerce_blocked_by(v) or None

    @field_validator("context", mode="before")
    @classmethod
    def normalize_context(cls, v: Any) -> str | None:
        if v is None:
            return None
        v_str = str(v).strip().lstrip("@").strip().lower()
        return v_str[:64] or None

    _check_estimate = _validate_minutes("estimate_min")
    _check_spent = _validate_minutes("spent_min")
    _check_follow_up = _validate_plan_date("follow_up_at")


class QuickAddIn(BaseModel):
    """#278: one line of natural language; explicit fields beat parsed ones."""

    text: str = Field(min_length=1, max_length=2000)
    note_id: str | None = None
    priority: Literal["P1", "P2", "P3"] | None = None
    due_date: str | None = None
    repo: str | None = None
    context: str | None = None
    list: Literal["inbox", "someday"] = "inbox"


class QuickAddParseView(BaseModel):
    text: str
    due_date: str | None = None
    context: str | None = None
    repo: str | None = None
    priority: str | None = None


class TodayLoad(BaseModel):
    estimated_min: int
    spent_min: int
    capacity_min: int


class TaskExportIn(BaseModel):
    """#40: choose the format and whether the file lands in the vault."""

    format: Literal["todo", "markdown"] = "markdown"
    include_done: bool = True


class TaskExportOut(BaseModel):
    content: str
    filename: str
    path: str | None = None


class WeeklyReview(BaseModel):
    """#38 weekly review: what slipped, what landed, what to decide about."""

    week_start: str
    today: str
    carry_over: list[TaskOut]
    this_week: list[TaskOut]
    completed: list[TaskOut]
    stats: dict[str, int | float]


class FocusIn(BaseModel):
    """#280: log real minutes spent. `minutes` is added to spent_min."""

    minutes: int = Field(ge=1, le=24 * 60)
    note: str | None = Field(default=None, max_length=200)


class PlanDay(BaseModel):
    day: str
    workday: bool
    capacity_min: int
    planned_min: int
    task_ids: list[str] = []


class PlanTotals(BaseModel):
    """#442 capacity gauge: planned minutes against available minutes."""

    capacity_min: int
    planned_min: int
    over_capacity: bool
    utilization: float


class WeekPlan(BaseModel):
    """#284 weekly planner."""

    week_start: str
    days: list[PlanDay]
    unscheduled: list[str] = []
    totals: PlanTotals


class StreakDay(BaseModel):
    day: str
    count: int


class StreakOut(BaseModel):
    """#39 completion streaks + heatmap."""

    current_streak: int
    best_streak: int
    active_days: int
    cells: list[StreakDay] = []


class TodayOut(BaseModel):
    """#30 Today view / #33 next action — one backend ranking, two views."""

    day: str
    overdue: list[TaskOut]
    due_today: list[TaskOut]
    waiting: list[TaskOut]
    completed_today: list[TaskOut]
    next_action: TaskOut | None = None
    up_next: list[TaskOut] = []
    load: TodayLoad
    streak: StreakOut | None = None


class QuickAddOut(BaseModel):
    task: TaskOut
    parsed: QuickAddParseView


class TaskUpdateIn(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    done: bool | None = None
    priority: Literal["P1", "P2", "P3"] | None = None
    due_date: str | None = None
    repo: str | None = None
    parent_id: str | None = None
    blocked_by: str | None = None
    estimate_min: int | None = None
    spent_min: int | None = None
    list: Literal["inbox", "someday", None] = None
    context: str | None = None
    waiting_for: str | None = None
    follow_up_at: str | None = None
    recurrence: str | None = Field(default=None, max_length=120)
    sort_order: float | None = None
    priority_source: Literal["inferred", "manual"] | None = None
    app_hint: str | None = Field(default=None, max_length=200)

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

    @field_validator("blocked_by", mode="before")
    @classmethod
    def normalize_blocked_by(cls, v: Any) -> str | None:
        return _coerce_blocked_by(v) or None

    @field_validator("context", mode="before")
    @classmethod
    def normalize_context(cls, v: Any) -> str | None:
        if v is None:
            return None
        v_str = str(v).strip().lstrip("@").strip().lower()
        return v_str[:64] or None

    _check_estimate = _validate_minutes("estimate_min")
    _check_spent = _validate_minutes("spent_min")
    _check_follow_up = _validate_plan_date("follow_up_at")


REVIEW_STATES = ("raw", "enriched", "reviewed", "final")


class RegenerateIn(BaseModel):
    """#20: re-run title/summary/tags enrichment. Model overrides the default."""

    model: str | None = Field(default=None, max_length=120)


class SnoozeIn(BaseModel):
    """#14 snooze: preset name, YYYY-MM-DD, full ISO stamp, or null to wake now."""

    until: str | None = Field(default=None, max_length=64)


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
    starred: bool = False
    trashed_at: str | None = None
    color: str | None = None
    fields: dict = Field(default_factory=dict)
    sensitive: bool = False
    review_state: str = "enriched"
    snoozed_until: str | None = None


class CaptureTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    capture_id: str | None = Field(default=None, max_length=64)
    source_title: str | None = Field(default=None, max_length=300)
    # #1/#427: capture template name + HUD output mode
    template: str | None = Field(default=None, max_length=64)
    mode: str | None = Field(default=None, max_length=16)


class CaptureYouTubeIn(BaseModel):
    url: str = Field(min_length=5, max_length=2000)
    capture_id: str | None = Field(default=None, max_length=64)
    source_title: str | None = Field(default=None, max_length=300)
    template: str | None = Field(default=None, max_length=64)
    mode: str | None = Field(default=None, max_length=16)


class NoteUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    # #435: correcting a voice transcript teaches whisper new words
    raw_text: str | None = Field(default=None, max_length=200_000)
    tags: list[str] | None = None
    pinned: bool | None = None
    archived: bool | None = None
    starred: bool | None = None
    # Empty string clears the colour; None (unset) leaves it alone. This keeps
    # PATCH semantics unambiguous without an exclude-null dance in the router.
    color: str | None = Field(default=None, max_length=32)
    # Replaces the whole typed-fields object — the editor sends what it sees.
    fields: dict | None = None
    sensitive: bool | None = None
    review_state: Literal["raw", "enriched", "reviewed", "final"] | None = None
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
    transcribe_vocabulary: str | None = None
    transcribe_translate: bool | None = None
    transcribe_cleanup_audio: bool | None = None
    transcribe_keep_audio: bool | None = None
    transcribe_voice_punctuation: bool | None = None
    transcribe_auto_format: bool | None = None
    transcribe_replacements: str | None = None
    transcribe_diarize: bool | None = None
    transcribe_hf_token: str | None = None
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

