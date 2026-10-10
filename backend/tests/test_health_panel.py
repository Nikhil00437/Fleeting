"""#94 LLM and embeddings health: latency, queue depth, last error, retry.

Almost all of this is already computed and thrown away — llm_traces records
the duration of every call, the processor knows its queue depth, and the
embedding path logs a downgrade the user never sees. This is the surface
that makes those legible.

The panel must be honest about *which* embeddings are in play: a silent
fallback to the local hash vector means semantic search is lexical-only,
and that is not a detail to bury.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.health import embedding_status, llm_health


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


# ---- latency -------------------------------------------------------------


def test_health_reports_average_latency(db: Database) -> None:
    for ms in (100, 200, 300):
        db.record_llm_trace(kind="chat", queries=["q"], context="c", ms=ms)
    assert llm_health(db)["avg_ms"] == 200


def test_health_reports_recent_latency_separately(db: Database) -> None:
    """One slow call should not flatter the average of the rest."""
    db.record_llm_trace(kind="chat", queries=["q"], context="c", ms=10)
    db.record_llm_trace(kind="chat", queries=["q"], context="c", ms=10)
    db.record_llm_trace(kind="chat", queries=["q"], context="c", ms=9000)
    health = llm_health(db)
    assert health["avg_ms"] < health["max_ms"]


def test_health_with_no_calls_is_unknown_not_zero(db: Database) -> None:
    """0ms would read as 'instantly fast', which is a different claim."""
    health = llm_health(db)
    assert health["avg_ms"] is None
    assert health["calls"] == 0


def test_health_counts_only_the_named_kind(db: Database) -> None:
    db.record_llm_trace(kind="chat", queries=["q"], context="c", ms=100)
    db.record_llm_trace(kind="enrich", queries=["q"], context="c", ms=400)
    assert llm_health(db, kind="enrich")["avg_ms"] == 400


def test_health_reports_the_error_rate(db: Database) -> None:
    for ok in (True, True, False):
        db.record_llm_trace(kind="chat", queries=["q"], context="c", ms=10, error=None if ok else "boom")
    assert llm_health(db)["errors"] == 1


def test_health_exposes_the_last_error(db: Database) -> None:
    db.record_llm_trace(kind="chat", queries=["q"], context="c", ms=10, error="ConnectError: refused")
    assert "ConnectError" in llm_health(db)["last_error"]


def test_health_with_no_error_reports_none(db: Database) -> None:
    db.record_llm_trace(kind="chat", queries=["q"], context="c", ms=10)
    assert llm_health(db)["last_error"] is None


# ---- embeddings ----------------------------------------------------------


def test_embedding_status_is_fine_when_the_provider_is_unused(db: Database) -> None:
    status = embedding_status(db, None)
    assert status["degraded"] is False
    assert status["model"] is None


def test_embedding_status_reports_a_downgrade(db: Database) -> None:
    status = embedding_status(db, "local-hash-384")
    assert status["degraded"] is True
    assert "lexical" in status["detail"].lower()


def test_embedding_status_is_fine_with_the_real_model(db: Database) -> None:
    assert embedding_status(db, "nomic-embed-text")["degraded"] is False


def test_embedding_status_reports_the_stored_dimension(db: Database) -> None:
    assert embedding_status(db, None)["dimensions"] == 0


# ---- the panel -----------------------------------------------------------


def test_health_endpoint_assembles_everything(client) -> None:
    r = client.get("/api/health-panel")
    assert r.status_code == 200
    body = r.json()
    assert {"llm", "embeddings", "queue"} <= set(body)


def test_health_endpoint_reports_queue_depth(client) -> None:
    body = client.get("/api/health-panel").json()
    assert body["queue"]["depth"] == 0
    assert body["queue"]["max"] > 0
    assert body["queue"]["inflight"] == 0


def test_health_endpoint_reflects_a_queued_capture(client) -> None:
    client.post("/api/capture/text", json={"text": "queued note"})
    assert client.get("/api/health-panel").json()["queue"]["depth"] >= 0


def test_health_endpoint_is_usable_without_a_provider(client) -> None:
    """The panel is most useful when something is broken."""
    body = client.get("/api/health-panel").json()
    assert body["llm"]["calls"] == 0


def test_a_downgraded_embedding_is_visible_on_the_panel(client) -> None:
    """#94's whole point: a silent lexical fallback the user can see."""
    st = client.app.state.st
    st.db.kv_set("embedding_model_used", "local-hash-384")
    body = client.get("/api/health-panel").json()
    assert body["embeddings"]["degraded"] is True
    assert "lexical" in body["embeddings"]["detail"]


def test_a_fresh_trace_records_the_fallback_error(client, monkeypatch) -> None:
    """A degraded answer that looks identical to a real one must be visible."""
    from fleeting.services.llm import LLMUnavailable

    client.app.state.st.cfg.llm.provider = "ollama"

    async def boom(*a, **kw):
        raise LLMUnavailable("connection refused")

    monkeypatch.setattr("fleeting.services.assistant.request_chat", boom)
    client.post("/api/assistant/chat", json={
        "messages": [{"role": "user", "content": "what did I do today?"}]
    })

    traces = client.get("/api/assistant/traces", params={"kind": "chat"}).json()
    assert traces[0]["error"]
    assert client.get("/api/health-panel").json()["llm"]["errors"] == 1


def test_retry_re_probes_the_provider(client, monkeypatch) -> None:
    """#94 one-click retry: re-run the probe, return the fresh answer."""
    async def fake(cfg):
        return {"ok": True, "models": ["m"], "hidden": 0}

    monkeypatch.setattr("fleeting.services.llm.check_llm", fake)
    r = client.post("/api/health-panel/retry")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_retry_reports_a_failure_rather_than_raising(client, monkeypatch) -> None:
    async def fake(cfg):
        return {"ok": False, "detail": "connection refused", "models": []}

    monkeypatch.setattr("fleeting.services.llm.check_llm", fake)
    r = client.post("/api/health-panel/retry")
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["detail"] == "connection refused"
