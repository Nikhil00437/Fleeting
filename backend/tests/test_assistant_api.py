"""Unit and integration tests for Ask Fleeting assistant service and REST endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from fleeting.config import Config
from fleeting.db import Database, now_iso
from fleeting.models import AssistantChatIn, AssistantChatOut, AssistantSuggestionsOut, ChatMessage
from fleeting.services.assistant import (
    _extractive_heuristic_answer,
    ask_assistant,
    build_assistant_context,
    get_assistant_suggestions,
    match_fast_intent,
)
from fleeting.services.embeddings import embed_note
from fleeting.services.llm import LLMUnavailable


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config()
    c.llm.provider = "none"
    c.paths.vault_dir = str(tmp_path / "vault")
    return c


# ============================================================================
# 1. Context Assembler Tests
# ============================================================================


def test_build_assistant_context_empty(db: Database, cfg: Config) -> None:
    context_text, sources, context_used = build_assistant_context("", db, cfg)
    assert context_text == "" or "Relevant Notes" not in context_text
    assert sources == []
    assert context_used["notes_count"] == 0
    assert context_used["logs_count"] == 0


def test_build_assistant_context_with_notes(db: Database, cfg: Config) -> None:
    note = db.insert_note({
        "title": "Quantum Algorithms",
        "type": "text",
        "summary": "Notes on Shor's and Grover's quantum algorithms.",
        "raw_text": "Detailed content about quantum gates, superposition, and speedups.",
        "tags": ["quantum", "physics"],
    })
    embed_note(note, db, cfg)

    context_text, sources, context_used = build_assistant_context("quantum algorithms", db, cfg)
    assert "=== Relevant Notes ===" in context_text
    assert f"[[note:{note['id']}|Quantum Algorithms]]" in context_text
    assert context_used["notes_count"] >= 1
    assert any(s["id"] == note["id"] and s["kind"] == "note" for s in sources)

    note_src = next(s for s in sources if s["id"] == note["id"])
    assert note_src["title"] == "Quantum Algorithms"
    assert note_src["type"] == "text"
    assert len(note_src["snippet"]) > 0
    assert "quantum" in note_src["snippet"].lower()


def test_build_assistant_context_with_tasks(db: Database, cfg: Config) -> None:
    note = db.insert_note({
        "title": "Project Roadmap",
        "type": "text",
        "summary": "Quarterly planning.",
        "raw_text": "Roadmap planning.",
    })
    task = db.insert_task({
        "note_id": note["id"],
        "text": "Refactor database migrations",
        "priority": "P1",
        "due_date": "2026-10-15",
        "repo": "fleeting",
    })

    context_text, sources, context_used = build_assistant_context("database migrations", db, cfg)
    assert "=== Active Tasks ===" in context_text
    assert f"[[task:{task['id']}|Refactor database migrations]]" in context_text
    assert "[Priority: P1]" in context_text
    assert context_used["tasks_count"] >= 1

    task_src = next(s for s in sources if s["id"] == task["id"])
    assert task_src["kind"] == "task"
    assert task_src["title"] == "Refactor database migrations"
    assert "Priority P1" in task_src["snippet"]
    assert "Due 2026-10-15" in task_src["snippet"]


def test_build_assistant_context_with_daily_logs(db: Database, cfg: Config) -> None:
    db.execute(
        "INSERT INTO daily_logs (day, summary_md, created_at) VALUES (?, ?, ?)",
        ("2026-10-02", "Implemented semantic vector search and hybrid RRF ranking.", now_iso()),
    )
    db.commit()

    context_text, sources, context_used = build_assistant_context("What work was done today?", db, cfg)
    assert "=== Recent Activity Logs ===" in context_text
    assert "Implemented semantic vector search" in context_text
    assert context_used["logs_count"] >= 1

    log_src = next(s for s in sources if s["kind"] == "log")
    assert log_src["id"] == "2026-10-02"
    assert "Implemented semantic vector search" in log_src["snippet"]


def test_build_assistant_context_filtering(db: Database, cfg: Config) -> None:
    note1 = db.insert_note({
        "title": "Frontend App",
        "type": "text",
        "summary": "React UI components.",
        "raw_text": "React UI components and details.",
        "tags": ["frontend"],
    })
    embed_note(note1, db, cfg)
    task1 = db.insert_task({
        "note_id": note1["id"],
        "text": "Build chat UI widget",
        "priority": "P2",
        "repo": "frontend",
    })

    note2 = db.insert_note({
        "title": "Backend API",
        "type": "text",
        "summary": "FastAPI routes.",
        "raw_text": "FastAPI routes.",
        "tags": ["backend"],
    })
    embed_note(note2, db, cfg)
    db.insert_task({
        "note_id": note2["id"],
        "text": "Add database index",
        "priority": "P2",
        "repo": "backend",
    })

    # Filter by repo="frontend"
    _, sources, _ = build_assistant_context("components", db, cfg, repo="frontend")
    note_ids = [s["id"] for s in sources if s["kind"] == "note"]
    task_ids = [s["id"] for s in sources if s["kind"] == "task"]

    assert note1["id"] in note_ids
    assert note2["id"] not in note_ids
    assert task1["id"] in task_ids


# ============================================================================
# 2. Extractive Heuristic Fallback Tests
# ============================================================================


def test_extractive_heuristic_answer_no_sources() -> None:
    answer = _extractive_heuristic_answer("What is the meaning of life?", "", [])
    assert "couldn't find" in answer.lower()


def test_extractive_heuristic_answer_with_citations() -> None:
    sources = [
        {
            "id": "note-123",
            "title": "Deploy Checklist",
            "type": "text",
            "kind": "note",
            "snippet": "Run tests before tagging release.",
        },
        {
            "id": "task-456",
            "title": "Tag v1.0.0 release",
            "type": "task",
            "kind": "task",
            "snippet": "Priority P1, Due 2026-10-10",
        },
    ]

    answer = _extractive_heuristic_answer("What are my release tasks?", "", sources)
    assert "[[task:task-456|Tag v1.0.0 release]]" in answer
    assert "[[note:note-123|Deploy Checklist]]" in answer
    assert "Priority P1" in answer


# ============================================================================
# 3. Assistant Orchestrator Tests
# ============================================================================


@pytest.mark.anyio
async def test_ask_assistant_offline(db: Database, cfg: Config) -> None:
    note = db.insert_note({
        "title": "Kubernetes Clusters",
        "type": "text",
        "summary": "Cluster management guidelines.",
        "raw_text": "Always verify kubectl context before apply.",
        "tags": ["devops"],
    })
    embed_note(note, db, cfg)

    messages = [{"role": "user", "content": "How do I manage Kubernetes clusters?"}]
    res = await ask_assistant(messages, db, cfg)

    assert res["message"]["role"] == "assistant"
    assert f"[[note:{note['id']}|Kubernetes Clusters]]" in res["message"]["content"]
    assert any(s["id"] == note["id"] for s in res["sources"])
    assert res["context_used"]["notes_count"] >= 1


@pytest.mark.anyio
async def test_ask_assistant_no_user_query(db: Database, cfg: Config) -> None:
    messages = [{"role": "system", "content": "You are helpful."}]
    res = await ask_assistant(messages, db, cfg)
    assert res["message"]["role"] == "assistant"
    assert "How can I help you today?" in res["message"]["content"]
    assert res["sources"] == []


@pytest.mark.anyio
async def test_ask_assistant_llm_fallback_on_error(db: Database) -> None:
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://localhost:11434"
    cfg.llm.model = "llama3"

    note = db.insert_note({
        "title": "Rust Lifetimes",
        "type": "text",
        "summary": "Borrow checker lifetimes explained.",
        "raw_text": "Lifetimes prevent dangling references.",
    })
    embed_note(note, db, cfg)

    messages = [{"role": "user", "content": "Explain Rust lifetimes"}]

    with patch("fleeting.services.assistant.request_chat", side_effect=LLMUnavailable("server offline")):
        res = await ask_assistant(messages, db, cfg)

    assert res["message"]["role"] == "assistant"
    assert f"[[note:{note['id']}|Rust Lifetimes]]" in res["message"]["content"]
    assert any(s["id"] == note["id"] for s in res["sources"])


@pytest.mark.anyio
async def test_ask_assistant_llm_success(db: Database) -> None:
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://localhost:11434"
    cfg.llm.model = "llama3"

    note = db.insert_note({
        "title": "Rust Lifetimes",
        "type": "text",
        "summary": "Borrow checker lifetimes explained.",
        "raw_text": "Lifetimes prevent dangling references.",
    })
    embed_note(note, db, cfg)

    messages = [{"role": "user", "content": "Explain Rust lifetimes"}]
    mock_llm_content = f"Based on [[note:{note['id']}|Rust Lifetimes]], lifetimes prevent dangling references."

    with patch("fleeting.services.assistant.request_chat", new=AsyncMock(return_value=mock_llm_content)):
        res = await ask_assistant(messages, db, cfg)

    assert res["message"]["role"] == "assistant"
    assert res["message"]["content"] == mock_llm_content
    assert any(s["id"] == note["id"] for s in res["sources"])


# ============================================================================
# 4. Assistant Suggestions Tests
# ============================================================================


def test_get_assistant_suggestions_empty_db(db: Database, cfg: Config) -> None:
    suggestions = get_assistant_suggestions(db, cfg)
    assert isinstance(suggestions, list)
    assert 3 <= len(suggestions) <= 5
    assert all(isinstance(s, str) and len(s) > 0 for s in suggestions)


def test_get_assistant_suggestions_with_p1_tasks(db: Database, cfg: Config) -> None:
    note = db.insert_note({"title": "Incident", "raw_text": "Incident response."})
    db.insert_task({
        "note_id": note["id"],
        "text": "Restore database replica",
        "priority": "P1",
    })

    suggestions = get_assistant_suggestions(db, cfg)
    assert "What urgent P1 tasks do I have?" in suggestions


def test_get_assistant_suggestions_with_daily_log(db: Database, cfg: Config) -> None:
    db.execute(
        "INSERT INTO daily_logs (day, summary_md, created_at) VALUES (?, ?, ?)",
        ("2026-10-02", "Sprint planning and bug triaging.", now_iso()),
    )
    db.commit()

    suggestions = get_assistant_suggestions(db, cfg)
    assert "What did I work on recently?" in suggestions


# ============================================================================
# 5. REST API Endpoint Tests via TestClient
# ============================================================================


def test_api_chat_endpoint(client: TestClient) -> None:
    # 1. Create a note via capture API
    r_capture = client.post(
        "/api/capture/text",
        json={"text": "Researching vector databases and reciprocal rank fusion for Fleeting."},
    )
    assert r_capture.status_code == 200
    note_id = r_capture.json()["id"]

    # 2. Chat with assistant
    payload = {
        "messages": [
            {"role": "user", "content": "What was I researching about vector databases?"}
        ]
    }
    r = client.post("/api/assistant/chat", json=payload)
    assert r.status_code == 200
    data = r.json()

    # Validate response schema
    out = AssistantChatOut(**data)
    assert out.message.role == "assistant"
    assert len(out.message.content) > 0
    assert isinstance(out.sources, list)
    assert "notes_count" in out.context_used
    assert "tasks_count" in out.context_used
    assert "logs_count" in out.context_used


def test_api_chat_endpoint_with_filters(client: TestClient) -> None:
    payload = {
        "messages": [
            {"role": "user", "content": "What tasks need attention?"}
        ],
        "repo": "fleeting",
        "type": "text",
    }
    r = client.post("/api/assistant/chat", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["message"]["role"] == "assistant"
    assert isinstance(data["sources"], list)


def test_api_suggestions_endpoint(client: TestClient) -> None:
    r = client.get("/api/assistant/suggestions")
    assert r.status_code == 200
    data = r.json()

    out = AssistantSuggestionsOut(**data)
    assert 3 <= len(out.suggestions) <= 5
    assert all(isinstance(s, str) for s in out.suggestions)


# ============================================================================
# 6. Fast Intent Matching & Action Execution Tests
# ============================================================================


def test_match_fast_intent_patterns() -> None:
    # Delete all tasks patterns
    assert match_fast_intent("delete all the tasks") == ("delete_tasks", {"all": True})
    assert match_fast_intent("delete all tasks") == ("delete_tasks", {"all": True})
    assert match_fast_intent("clear all tasks") == ("delete_tasks", {"all": True})
    assert match_fast_intent("clear all the tasks") == ("delete_tasks", {"all": True})
    assert match_fast_intent("delete all active tasks") == ("delete_tasks", {"all": True})

    # Delete specific task
    assert match_fast_intent("delete task 123") == ("delete_tasks", {"ids": ["123"]})
    assert match_fast_intent("delete task [[task:abc-456|Refactor]]") == ("delete_tasks", {"ids": ["abc-456"]})
    assert match_fast_intent("remove task 789") == ("delete_tasks", {"ids": ["789"]})
    assert match_fast_intent("remove task [[task:xyz-999|Fix bug]]") == ("delete_tasks", {"ids": ["xyz-999"]})

    # Toggle task
    assert match_fast_intent("mark task 123 as done") == ("toggle_task", {"task_id": "123"})
    assert match_fast_intent("mark task [[task:abc-456|Test]] as done") == ("toggle_task", {"task_id": "abc-456"})
    assert match_fast_intent("complete task 123") == ("toggle_task", {"task_id": "123"})
    assert match_fast_intent("toggle task 123") == ("toggle_task", {"task_id": "123"})

    # Daily digest
    assert match_fast_intent("generate today's digest") == ("generate_daily_digest", {"rolling": True})
    assert match_fast_intent("generate todays digest") == ("generate_daily_digest", {"rolling": True})
    assert match_fast_intent("generate digest") == ("generate_daily_digest", {"rolling": True})
    assert match_fast_intent("create daily digest") == ("generate_daily_digest", {"rolling": True})

    # Pause / resume activity
    assert match_fast_intent("pause activity tracking") == ("pause_activity", {"paused": True})
    assert match_fast_intent("pause activity") == ("pause_activity", {"paused": True})
    assert match_fast_intent("resume activity tracking") == ("pause_activity", {"paused": False})
    assert match_fast_intent("resume activity") == ("pause_activity", {"paused": False})

    # Non-intents should return None
    assert match_fast_intent("what are my tasks for today?") is None
    assert match_fast_intent("tell me about the project") is None
    assert match_fast_intent("delete the files") is None


@pytest.mark.anyio
async def test_assistant_fast_intent_delete_all_tasks(db: Database, cfg: Config) -> None:
    # 1. Create notes and tasks in DB
    note = db.insert_note({"title": "Tasks Note", "raw_text": "Work items"})
    db.insert_task({"note_id": note["id"], "text": "Task Alpha", "priority": "P1"})
    db.insert_task({"note_id": note["id"], "text": "Task Beta", "priority": "P2"})

    assert len(db.list_tasks(status="all")) == 2

    # 2. Ask assistant to delete all tasks
    messages = [{"role": "user", "content": "delete all the tasks"}]
    res = await ask_assistant(messages, db, cfg)

    # 3. Verify tasks are deleted from DB
    assert len(db.list_tasks(status="all")) == 0

    # 4. Result message confirms deletion and sources are provided
    assert "Deleted 2 active tasks" in res["message"]["content"]
    assert len(res["sources"]) >= 2
    assert any(s["title"] == "Task Alpha" for s in res["sources"])
    assert any(s["title"] == "Task Beta" for s in res["sources"])


@pytest.mark.anyio
async def test_assistant_fast_intent_generate_digest(db: Database, cfg: Config) -> None:
    messages = [{"role": "user", "content": "generate today's digest"}]

    mock_row = {"day": "2026-10-03", "summary_md": "Daily work summary generated."}
    with patch("fleeting.services.actions.dailylog.generate_daily_log", new=AsyncMock(return_value=mock_row)) as mock_gen:
        res = await ask_assistant(messages, db, cfg)
        assert mock_gen.called

    assert "Generated daily digest" in res["message"]["content"]
    assert res["message"]["role"] == "assistant"
    assert any(s["kind"] == "log" for s in res["sources"])


@pytest.mark.anyio
async def test_assistant_model_action_block_execution(db: Database, cfg: Config) -> None:
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://localhost:11434"
    cfg.llm.model = "llama3"

    note = db.insert_note({"title": "Test Note", "raw_text": "Content"})
    db.insert_task({"note_id": note["id"], "text": "Do cleanup", "priority": "P1"})
    assert len(db.list_tasks(status="all")) == 1

    messages = [{"role": "user", "content": "Clean up my tasks please."}]
    model_response = (
        "```action\n"
        '{"tool": "delete_tasks", "parameters": {"all": true}}\n'
        "```\n"
        "I have deleted all your active tasks."
    )

    with patch("fleeting.services.assistant.request_chat", new=AsyncMock(return_value=model_response)):
        res = await ask_assistant(messages, db, cfg)

    assert len(db.list_tasks(status="all")) == 0
    assert "```action" not in res["message"]["content"]
    assert res["message"]["content"] == "I have deleted all your active tasks."


@pytest.mark.anyio
async def test_assistant_fast_intent_toggle_task(db: Database, cfg: Config) -> None:
    note = db.insert_note({"title": "Action List", "raw_text": "items"})
    task = db.insert_task({"note_id": note["id"], "text": "Deploy staging", "priority": "P1"})
    assert task["done"] == 0

    messages = [{"role": "user", "content": f"mark task {task['id']} as done"}]
    res = await ask_assistant(messages, db, cfg)

    updated = db.get_task(task["id"])
    assert updated["done"] == 1
    assert "completed" in res["message"]["content"].lower()


@pytest.mark.anyio
async def test_assistant_fast_intent_pause_activity(db: Database, cfg: Config) -> None:
    # 1. Pause
    messages = [{"role": "user", "content": "pause activity tracking"}]
    res_pause = await ask_assistant(messages, db, cfg)
    assert db.kv_get("activity_paused") == "1"
    assert "paused" in res_pause["message"]["content"].lower()

    # 2. Resume
    messages = [{"role": "user", "content": "resume activity"}]
    res_resume = await ask_assistant(messages, db, cfg)
    assert db.kv_get("activity_paused") == "0"
    assert "resumed" in res_resume["message"]["content"].lower()


def test_api_chat_endpoint_fast_intent(client: TestClient) -> None:
    # 1. Create a task directly in DB
    client.app.state.st.db.insert_task({"text": "Urgent review task", "priority": "P1"})

    # 2. Chat with fast intent to delete all tasks
    payload = {
        "messages": [
            {"role": "user", "content": "delete all tasks"}
        ]
    }
    r = client.post("/api/assistant/chat", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "Deleted" in data["message"]["content"]
    assert "task" in data["message"]["content"].lower()
    assert len(client.app.state.st.db.list_tasks(status="all")) == 0

