"""#257: a preferred tag vocabulary the enricher is held to.

Steering the prompt alone is not control — a model asked to prefer
"homelab" still answers "homelab-router" often enough that the tag list
stays a mess. The vocabulary has to be enforced after the fact as well.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.tags_vocab import apply_preferred_tags, preferred_tags, tag_prompt


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def test_prompt_lists_the_preferred_tags() -> None:
    block = tag_prompt(["homelab", "baking"])
    assert "homelab" in block
    assert "baking" in block


def test_prompt_is_empty_without_a_vocabulary() -> None:
    assert tag_prompt([]) == ""


def test_prompt_tells_the_model_to_stop_inventing() -> None:
    assert "invent" in tag_prompt(["homelab"]).lower()


def test_no_preferred_tags_leaves_the_model_output_alone() -> None:
    assert apply_preferred_tags(["homelab-router", "baking"], []) == ["homelab-router", "baking"]


def test_an_exact_preferred_tag_is_kept() -> None:
    assert apply_preferred_tags(["homelab"], ["homelab", "baking"]) == ["homelab"]


def test_a_near_miss_snaps_to_the_preferred_tag() -> None:
    assert apply_preferred_tags(["homelab-router"], ["homelab"]) == ["homelab"]


def test_an_unrelated_tag_is_left_to_the_model() -> None:
    """Vocabulary control must not collapse every tag into the nearest word."""
    assert apply_preferred_tags(["sourdough"], ["homelab", "baking"]) == ["sourdough"]


def test_snapping_never_produces_duplicates() -> None:
    """Two different model tags can collapse onto one preferred tag."""
    out = apply_preferred_tags(["homelab-router", "homelab", "homelab-router"], ["homelab"])
    assert out == ["homelab"]


def test_an_unseparated_concatenation_is_left_alone() -> None:
    """Over-merging is worse than a messy tag: 'homelabrouters' is not 'homelab'."""
    assert apply_preferred_tags(["homelabrouters"], ["homelab"]) == ["homelabrouters"]


def test_order_is_preserved() -> None:
    assert apply_preferred_tags(["baking", "sourdough"], ["baking"]) == ["baking", "sourdough"]


def test_preferred_tags_read_the_config(db: Database) -> None:
    from fleeting.config import Config

    cfg = Config()
    cfg.llm.preferred_tags = " homelab , baking ,, "
    assert preferred_tags(cfg) == ["homelab", "baking"]


@pytest.mark.anyio
async def test_a_capture_is_tagged_from_the_vocabulary(client, monkeypatch) -> None:
    from fleeting.services import llm as llm_svc

    async def fake_chain(text, cfg, prompt=None, few_shot="", tag_vocab=""):
        # The model ignored the instruction; enforcement has to catch it.
        return {
            "title": "Router",
            "summary": "s",
            "tags": ["homelab-router"],
            "action_items": [],
            "confidence": 0.9,
        }

    monkeypatch.setattr("fleeting.process.llm.enrich_chain", fake_chain)
    # The client fixture builds its own Config; patch the read rather than
    # reaching into app.state.
    monkeypatch.setattr("fleeting.process.preferred_tags", lambda cfg: ["homelab"])

    from tests.conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "the router again"}).json()["id"]
    note = wait_done(client, note_id)
    assert note["tags"] == ["homelab"]
