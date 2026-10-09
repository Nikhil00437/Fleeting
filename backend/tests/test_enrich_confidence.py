"""#96 confidence flags on enrichment, #255 a thumb that records a verdict.

A confidence number that the app invents is worse than none: it would look
authoritative and mean nothing. So the model supplies it, the sanitizer
clamps it, and an absent or nonsensical value stays absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.config import LLMConfig
from fleeting.db import Database
from fleeting.services.llm import _sanitize, heuristic_enrich


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


# ---- #96 confidence ------------------------------------------------------


def test_sanitize_keeps_a_reported_confidence() -> None:
    out = _sanitize({"title": "t", "summary": "s", "tags": [], "action_items": [], "confidence": 0.82})
    assert out["confidence"] == pytest.approx(0.82)


def test_sanitize_clamps_confidence_above_one() -> None:
    out = _sanitize({"title": "t", "summary": "s", "tags": [], "action_items": [], "confidence": 4.2})
    assert out["confidence"] == 1.0


def test_sanitize_clamps_negative_confidence() -> None:
    out = _sanitize({"title": "t", "summary": "s", "tags": [], "action_items": [], "confidence": -1})
    assert out["confidence"] == 0.0


def test_sanitize_drops_a_confidence_that_is_not_a_number() -> None:
    """A model that answered 'high' did not report a confidence."""
    out = _sanitize({"title": "t", "summary": "s", "tags": [], "action_items": [], "confidence": "high"})
    assert out["confidence"] is None


def test_sanitize_reports_none_when_the_model_omits_it() -> None:
    out = _sanitize({"title": "t", "summary": "s", "tags": [], "action_items": []})
    assert out["confidence"] is None


def test_heuristic_enrichment_claims_no_confidence() -> None:
    """Deterministic extraction is not uncertain — it is simply not a model."""
    assert heuristic_enrich("todo: buy milk")["confidence"] is None


@pytest.mark.anyio
async def test_processing_stores_the_reported_confidence(client, monkeypatch) -> None:
    from fleeting.services import llm as llm_svc

    async def fake_chain(text, cfg, prompt=None, few_shot="", tag_vocab="", template=""):
        return {
            "title": "Router notes",
            "summary": "s",
            "tags": ["homelab"],
            "action_items": [],
            "confidence": 0.91,
        }

    monkeypatch.setattr(llm_svc, "enrich_chain", fake_chain)
    monkeypatch.setattr("fleeting.process.llm.enrich_chain", fake_chain)

    note_id = client.post("/api/capture/text", json={"text": "The router runs OpenWrt."}).json()["id"]
    from tests.conftest import wait_done

    note = wait_done(client, note_id)
    assert note["enrich_confidence"] == pytest.approx(0.91)


@pytest.mark.anyio
async def test_heuristic_processing_leaves_confidence_null(client) -> None:
    note_id = client.post("/api/capture/text", json={"text": "Plain capture, no provider."}).json()["id"]
    from tests.conftest import wait_done

    note = wait_done(client, note_id)
    assert note["enrich_confidence"] is None


# ---- #255 feedback -------------------------------------------------------


def test_feedback_is_stored_on_the_note(db: Database) -> None:
    note = db.insert_note({"title": "t", "raw_text": "x"})
    db.update_note(note["id"], {"enrich_feedback": -1})
    assert db.get_note(note["id"])["enrich_feedback"] == -1


def test_feedback_does_not_create_a_version_entry(db: Database) -> None:
    """A thumb is a verdict, not an edit — it must not pollute note history."""
    note = db.insert_note({"title": "t", "raw_text": "x"})
    before = db.note_versions(note["id"])
    db.update_note(note["id"], {"enrich_feedback": 1})
    assert db.note_versions(note["id"]) == before


def test_feedback_endpoint_records_a_thumb(client) -> None:
    note_id = client.post("/api/capture/text", json={"text": "Rate me"}).json()["id"]
    r = client.patch(f"/api/notes/{note_id}/enrich-feedback", json={"feedback": -1})
    assert r.status_code == 200
    assert client.get(f"/api/notes/{note_id}").json()["enrich_feedback"] == -1


def test_feedback_endpoint_clears_a_thumb(client) -> None:
    note_id = client.post("/api/capture/text", json={"text": "Rate me"}).json()["id"]
    client.patch(f"/api/notes/{note_id}/enrich-feedback", json={"feedback": 1})
    r = client.patch(f"/api/notes/{note_id}/enrich-feedback", json={"feedback": 0})
    assert r.json()["enrich_feedback"] == 0


def test_feedback_endpoint_rejects_a_nonsense_value(client) -> None:
    note_id = client.post("/api/capture/text", json={"text": "Rate me"}).json()["id"]
    r = client.patch(f"/api/notes/{note_id}/enrich-feedback", json={"feedback": 7})
    assert r.status_code == 422
