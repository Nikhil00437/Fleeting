"""#453 "what will the LLM see?" preview and #112 tool-use trace.

Both hang off the same fact: `build_assistant_context` already knows every
query it issued and every row it pulled. It threw that away, so the answer
"what did you actually look at?" was unanswerable after the fact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database, now_iso
from fleeting.services.assistant import build_assistant_context


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


def _seed(db: Database) -> None:
    db.insert_note({
        "title": "Router notes",
        "type": "text",
        "summary": "Homelab router firmware notes.",
        "raw_text": "The router runs OpenWrt on a GL.iNet.",
        "type": "text",
    })
    db.insert_note({
        "title": "Sourdough",
        "type": "text",
        "summary": "Starter maintenance log.",
        "raw_text": "Feed the starter every twelve hours.",
    })


def test_build_assistant_context_records_the_queries_it_ran(db: Database, cfg: Config) -> None:
    _seed(db)
    queries: list[str] = []

    build_assistant_context("router firmware", db, cfg, queries=queries)

    assert "router firmware" in queries


def test_trace_is_empty_without_a_collector(db: Database, cfg: Config) -> None:
    """Callers that don't ask for a trace must not be forced to pass one."""
    _seed(db)
    context_text, sources, _used = build_assistant_context("router", db, cfg)
    assert sources
    assert context_text


def test_context_preview_returns_exactly_what_the_assistant_would_send(
    client, db: Database
) -> None:
    _seed(db)
    r = client.get("/api/assistant/context-preview", params={"q": "router firmware"})
    assert r.status_code == 200
    data = r.json()
    assert "OpenWrt" in data["context"]
    assert data["sources"], "preview must list the rows the model will see"


def test_chat_records_a_trace(db: Database, cfg: Config) -> None:
    import asyncio

    from fleeting.services.assistant import ask_assistant

    _seed(db)
    asyncio.run(ask_assistant([{"role": "user", "content": "router firmware"}], db, cfg))

    traces = db.list_llm_traces(kind="chat")
    assert len(traces) == 1
    assert "router firmware" in traces[0]["queries"]
    assert traces[0]["ms"] >= 0


def test_sensitive_note_body_never_reaches_the_model(db: Database, cfg: Config) -> None:
    """#26: sensitive notes stay out of the context sent to the chat model.

    The filter used to run only when building the `sources` citation list, while
    the context sections were rendered from the raw notes — so the note body
    left the machine even though the UI showed no citation for it.
    """
    db.insert_note({
        "title": "Router password",
        "type": "text",
        "summary": "Router admin credentials.",
        "raw_text": "The router password is hunter2.",
        "sensitive": True,
    })
    context_text, sources, _used = build_assistant_context("router password", db, cfg)
    assert "hunter2" not in context_text
    assert sources == []


def test_trashed_note_body_never_reaches_the_model(db: Database, cfg: Config) -> None:
    db.insert_note({
        "title": "Deleted idea",
        "type": "text",
        "summary": "An idea that was trashed.",
        "raw_text": "The trashed secret is swordfish.",
        "trashed_at": now_iso(),
    })
    context_text, _sources, _used = build_assistant_context("trashed secret", db, cfg)
    assert "swordfish" not in context_text


def test_preview_excludes_sensitive_notes(client, db: Database) -> None:
    """A preview must not become a side door around #26's exclusion."""
    db.insert_note({
        "title": "Router password",
        "type": "text",
        "summary": "Router admin credentials.",
        "raw_text": "The router password is hunter2.",
        "sensitive": True,
    })
    r = client.get("/api/assistant/context-preview", params={"q": "router password"})
    assert "hunter2" not in r.json()["context"]


def test_traces_endpoint_lists_recorded_calls(client) -> None:
    client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "anything"}]})
    r = client.get("/api/assistant/traces", params={"kind": "chat"})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_traces_are_listed_newest_first(db: Database) -> None:
    for i in range(3):
        db.record_llm_trace(kind="chat", queries=[f"q{i}"], context="c", ms=i)
    traces = db.list_llm_traces(kind="chat")
    assert [t["queries"] for t in traces] == [["q2"], ["q1"], ["q0"]]
