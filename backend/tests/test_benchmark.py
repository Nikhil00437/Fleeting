"""#264 a local benchmark of models on your own past notes.

What this measures is faithfulness, and the name matters: a generated title is
scored on how much of it is actually supported by the note it describes, using
the same token-overlap rule #263 uses to hold a summary back. That is a real,
bounded, inspectable measure — not "is this good writing", which no local
heuristic can answer and an LLM judge cannot answer without its own bias.

Two things it is deliberately not:

- It never writes. A benchmark that rewrites your notes to compare them would
  destroy the corpus it is measuring.
- It never sends a sensitive note. #26 says those bodies do not leave the app,
  and a benchmark that quietly included them would breach it in the name of
  measuring your model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.benchmark import benchmark_models, sample_notes, score_output


@pytest.fixture
def env(tmp_path: Path):
    db = Database(str(tmp_path / "bench.db"))
    db.migrate()
    cfg = Config()
    cfg.paths.vault_dir = str(tmp_path / "vault")
    cfg.llm.provider = "ollama"
    cfg.llm.model = "current-model"
    cfg.llm.fallback_models = "other-model"
    return db, cfg, EventBus()


def _note(db: Database, text: str, **kw) -> str:
    return db.insert_note(
        {"title": "t", "raw_text": text, "status": "done", **kw}
    )["id"]


# ---- scoring -------------------------------------------------------------


def test_a_faithful_title_scores_higher_than_an_invented_one() -> None:
    source = "the router firmware upgrade failed and the wireless network dropped"
    faithful = score_output({"title": "Router firmware upgrade failed", "summary": ""}, source)
    invented = score_output({"title": "Quarterly tax planning session", "summary": ""}, source)
    assert faithful["score"] > invented["score"]


def test_the_score_is_bounded_and_explainable() -> None:
    out = score_output({"title": "Router upgrade failed", "summary": ""}, "the router upgrade failed")
    assert 0.0 <= out["score"] <= 1.0
    # Every number the score rests on is reported, not just the score.
    assert "title_ratio" in out and "ungrounded" in out


def test_an_empty_generation_does_not_score_perfectly() -> None:
    """A ratio over an empty numerator would report 100% for saying nothing."""
    assert score_output({"title": "", "summary": ""}, "some source text")["score"] == 0.0


def test_a_summary_is_scored_against_the_note_it_summarises() -> None:
    source = "Priya sent the q4 invoice numbers on tuesday"
    good = score_output(
        {"title": "", "summary": "Priya sent the q4 invoice numbers."}, source
    )
    bad = score_output({"title": "", "summary": "The landlord replaced the boiler."}, source)
    assert good["score"] > bad["score"]


# ---- sampling ------------------------------------------------------------


def test_only_notes_with_content_are_sampled(env) -> None:
    db, cfg, bus = env
    _note(db, "real content about routers and firmware here")
    _note(db, "")

    rows = sample_notes(db, limit=10)

    assert len(rows) == 1
    assert "routers" in rows[0]["raw_text"]


def test_sensitive_notes_are_never_sampled(env) -> None:
    """#26 applies here like everywhere else."""
    db, cfg, bus = env
    nid = _note(db, "private thoughts about my bank")
    db.update_note(nid, {"sensitive": 1})
    _note(db, "public note about routers")

    rows = sample_notes(db, limit=10)

    assert len(rows) == 1
    assert "routers" in rows[0]["raw_text"]


def test_trashed_and_archived_notes_are_not_sampled(env) -> None:
    db, cfg, bus = env
    _note(db, "live note about routers")
    db.update_note(_note(db, "archived note"), {"archived": 1})
    db.execute("UPDATE notes SET trashed_at = '2026-01-01' WHERE title = 't' AND raw_text LIKE 'live%'")
    db.commit()
    assert len(sample_notes(db, limit=10)) == 0


# ---- running it ----------------------------------------------------------


@pytest.mark.anyio
async def test_a_model_is_scored_against_the_real_notes(env, monkeypatch) -> None:
    db, cfg, bus = env
    _note(db, "the router firmware upgrade failed and the wireless network dropped")
    seen: list[str] = []

    async def fake_enrich(text, llm_cfg, **kw):
        seen.append(llm_cfg.model)
        return {"title": "Router firmware upgrade failed", "summary": "", "tags": []}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", fake_enrich)

    out = await benchmark_models(db, cfg, bus, models=["current-model"], sample=5)

    assert seen == ["current-model"]
    assert out["results"][0]["model"] == "current-model"
    assert out["results"][0]["notes"] == 1
    assert 0.0 <= out["results"][0]["mean_score"] <= 1.0


@pytest.mark.anyio
async def test_the_benchmark_never_writes_to_the_notes(env, monkeypatch) -> None:
    """Measuring a corpus by rewriting it would destroy the corpus."""
    db, cfg, bus = env
    nid = _note(db, "the router firmware upgrade failed", title="my own title")

    async def fake_enrich(text, llm_cfg, **kw):
        return {"title": "a completely different title", "summary": "", "tags": ["x"]}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", fake_enrich)

    await benchmark_models(db, cfg, bus, models=["current-model"], sample=5)

    note = db.get_note(nid)
    assert note["title"] == "my own title"
    assert note["tags"] == []


@pytest.mark.anyio
async def test_one_failing_model_does_not_lose_the_others(env, monkeypatch) -> None:
    db, cfg, bus = env
    _note(db, "the router firmware upgrade failed")

    async def fake_enrich(text, llm_cfg, **kw):
        if llm_cfg.model == "broken-model":
            raise Exception("model unreachable")
        return {"title": "Router firmware failed", "summary": "", "tags": []}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", fake_enrich)

    out = await benchmark_models(
        db, cfg, bus, models=["broken-model", "current-model"], sample=5
    )

    by_model = {r["model"]: r for r in out["results"]}
    assert by_model["broken-model"]["notes"] == 0
    assert by_model["broken-model"]["error"]
    assert by_model["current-model"]["notes"] == 1


@pytest.mark.anyio
async def test_no_llm_is_refused_rather_than_scoring_nothing(env) -> None:
    db, cfg, bus = env
    _note(db, "the router firmware upgrade failed")
    cfg.llm.provider = "none"

    out = await benchmark_models(db, cfg, bus, models=["current-model"], sample=5)

    assert out["results"] == []
    assert "llm" in out["error"].lower()


@pytest.mark.anyio
async def test_no_notes_is_an_empty_result_not_an_error(env, monkeypatch) -> None:
    db, cfg, bus = env

    out = await benchmark_models(db, cfg, bus, models=["current-model"], sample=5)

    assert out["results"]
    assert out["results"][0]["notes"] == 0


@pytest.mark.anyio
async def test_a_model_is_compared_on_the_same_notes(env, monkeypatch) -> None:
    """Different notes per model would make the numbers incomparable."""
    db, cfg, bus = env
    for i in range(4):
        _note(db, f"note number {i} about routers and firmware")

    seen: list[str] = []

    async def fake_enrich(text, llm_cfg, **kw):
        seen.append(llm_cfg.model)
        return {"title": "Router", "summary": "", "tags": []}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", fake_enrich)

    out = await benchmark_models(db, cfg, bus, models=["a", "b"], sample=3)

    assert seen.count("a") == seen.count("b") == 3
    assert {r["notes"] for r in out["results"]} == {3}


@pytest.mark.anyio
async def test_latency_is_reported_per_model(env, monkeypatch) -> None:
    db, cfg, bus = env
    _note(db, "the router firmware upgrade failed")

    async def fake_enrich(text, llm_cfg, **kw):
        return {"title": "Router", "summary": "", "tags": []}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", fake_enrich)

    out = await benchmark_models(db, cfg, bus, models=["current-model"], sample=1)

    assert out["results"][0]["ms_per_note"] >= 0


@pytest.mark.anyio
async def test_the_models_default_to_the_ones_already_configured(env, monkeypatch) -> None:
    """The models worth comparing are the ones the user already lists."""
    db, cfg, bus = env
    _note(db, "the router firmware upgrade failed")
    seen: list[str] = []

    async def fake_enrich(text, llm_cfg, **kw):
        seen.append(llm_cfg.model)
        return {"title": "Router", "summary": "", "tags": []}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", fake_enrich)

    out = await benchmark_models(db, cfg, bus, sample=1)

    assert "current-model" in seen
    assert "other-model" in seen
    assert len(out["results"]) == 2

# ---- the endpoint --------------------------------------------------------


@pytest.fixture()
def benchmark_on(client):
    """#195: behind `[experimental].benchmark`. These cover the endpoint's
    behaviour; the gate has its own tests."""
    client.app.state.st.cfg.experimental.benchmark = True
    return client


def test_the_endpoint_runs_the_configured_models(benchmark_on) -> None:
    client = benchmark_on
    r = client.post("/api/benchmark/run", json={"sample": 1})
    assert r.status_code in (200, 502)
    body = r.json()
    assert "results" in body
    # The fixture forces provider="none", so the honest answer here is the
    # refusal. With a model configured it carries the metric instead.
    if body["results"]:
        assert body["metric"]
    else:
        assert "llm" in body["error"].lower()


def test_the_endpoint_refuses_without_a_model(benchmark_on) -> None:
    client = benchmark_on
    r = client.post("/api/benchmark/run", json={"models": ["", "  "]})
    assert r.status_code == 422
