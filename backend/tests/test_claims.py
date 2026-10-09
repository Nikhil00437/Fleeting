"""#263: every summary sentence says where it came from, or admits it didn't.

A hallucination guard that asks the model "which sentence did this come
from?" would be trusting the thing it is meant to check. Grounding is
therefore deterministic: token overlap between the claim and the source it
was generated from. That is testable, and it cannot be talked into agreeing
with itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.claims import supported_ratio, verify_claims


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


# ---- the matcher ---------------------------------------------------------


def test_an_identical_sentence_is_fully_supported() -> None:
    assert supported_ratio("The router runs OpenWrt.", "The router runs OpenWrt.") == 1.0


def test_a_sentence_of_pure_stopwords_is_not_measured() -> None:
    """'it is what it is' shares no content, so a ratio would be meaningless."""
    assert supported_ratio("it is what it is", "completely different words here") == 0.0


def test_a_claim_absent_from_the_source_scores_zero() -> None:
    assert supported_ratio(
        "The invoice was paid on Tuesday.",
        "The router runs OpenWrt on a GL.iNet device.",
    ) == 0.0


# ---- claims --------------------------------------------------------------


def test_every_summary_sentence_becomes_a_claim() -> None:
    claims = verify_claims(
        "The router runs OpenWrt. The bridge network broke.",
        "The router runs OpenWrt on a GL.iNet. The bridge network broke after the upgrade.",
    )
    assert len(claims) == 2
    assert claims[0]["text"] == "The router runs OpenWrt."


def test_a_grounded_claim_carries_its_source_span() -> None:
    claims = verify_claims(
        "The router runs OpenWrt.",
        "The router runs OpenWrt on a GL.iNet.",
    )
    assert claims[0]["supported"] is True
    assert "OpenWrt" in claims[0]["span"]


def test_an_invented_claim_is_marked_unsupported_with_no_span() -> None:
    claims = verify_claims(
        "We replaced the router in March.",
        "The router runs OpenWrt on a GL.iNet device.",
    )
    assert claims[0]["supported"] is False
    assert claims[0]["span"] is None


def test_a_partial_overlap_is_not_supported() -> None:
    """Three shared words out of a long sentence is a guess, not a citation."""
    claims = verify_claims(
        "The router runs OpenWrt firmware version 24.06 with the new bridge configuration.",
        "The router runs OpenWrt.",
    )
    assert claims[0]["supported"] is False


def test_a_paraphrase_with_the_same_content_words_is_supported() -> None:
    """Summaries restate; demanding verbatim quotes would flag every one."""
    claims = verify_claims(
        "The router is running OpenWrt.",
        "Note that the router is running OpenWrt right now.",
    )
    assert claims[0]["supported"] is True


def test_no_summary_yields_no_claims() -> None:
    assert verify_claims("", "some source text") == []


def test_claims_ignore_markdown_headers_and_bullets() -> None:
    """A generated summary is full of structure that is not a factual claim."""
    claims = verify_claims(
        "## Focus\n\n- The router runs OpenWrt.\n- The invoice was paid on Tuesday.",
        "The router runs OpenWrt on a GL.iNet.",
    )
    assert len(claims) == 2
    assert all(not c["text"].startswith("#") for c in claims)


def test_a_bullet_without_words_is_not_a_claim() -> None:
    assert verify_claims("- \n- ---", "source text") == []


# ---- persistence ---------------------------------------------------------


def test_claims_are_stored_on_the_note(db: Database) -> None:
    note = db.insert_note({"title": "t", "raw_text": "x"})
    claims = [{"text": "c", "supported": True, "span": "x"}]
    db.update_note(note["id"], {"claims": claims})
    assert db.get_note(note["id"])["claims"] == claims


def test_a_reprocess_clears_stale_claims(db: Database) -> None:
    """Yesterday's citations must not survive onto today's summary."""
    note = db.insert_note({
        "title": "t",
        "raw_text": "x",
        "claims": [{"text": "old", "supported": True, "span": "x"}],
    })
    db.update_note(note["id"], {"claims": None})
    assert db.get_note(note["id"])["claims"] is None


@pytest.mark.anyio
async def test_an_unsupported_claim_sends_the_note_back_to_review(client, monkeypatch) -> None:
    from fleeting.services import llm as llm_svc

    async def fake_chain(text, cfg, prompt=None, few_shot="", tag_vocab="", template=""):
        return {
            "title": "Router",
            "summary": "We replaced the router in March for the outage.",
            "tags": [],
            "action_items": [],
            "confidence": 0.9,
        }

    monkeypatch.setattr("fleeting.process.llm.enrich_chain", fake_chain)

    from tests.conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "The router runs OpenWrt."}).json()["id"]
    note = wait_done(client, note_id)

    assert note["review_state"] == "raw", "an ungrounded summary must not claim to be enriched"
    assert note["claims"][0]["supported"] is False


@pytest.mark.anyio
async def test_a_fully_grounded_summary_stays_enriched(client, monkeypatch) -> None:
    from fleeting.services import llm as llm_svc

    async def fake_chain(text, cfg, prompt=None, few_shot="", tag_vocab="", template=""):
        return {
            "title": "Router",
            "summary": "The router runs OpenWrt.",
            "tags": [],
            "action_items": [],
            "confidence": 0.9,
        }

    monkeypatch.setattr("fleeting.process.llm.enrich_chain", fake_chain)

    from tests.conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "The router runs OpenWrt."}).json()["id"]
    note = wait_done(client, note_id)

    assert note["review_state"] == "enriched"
    assert note["claims"][0]["supported"] is True
