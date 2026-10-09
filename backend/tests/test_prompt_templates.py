"""#93 prompt editor for enrichment and reports, with reset to default.

The trap here is not storage, it is substitution. A user-editable template
goes through `str.format`, so any stray brace in someone's prompt would
raise KeyError at generation time — turning a typo in settings into a broken
daily report for every day after.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.prompt_templates import (
    TARGETS,
    default_template,
    get_template,
    is_default,
    reset_template,
    set_template,
    substitute,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


# ---- shape ---------------------------------------------------------------


def test_both_targets_exist() -> None:
    assert set(TARGETS) == {"enrich", "daily_report"}


def test_an_untouched_template_is_the_default() -> None:
    assert default_template("enrich")
    assert default_template("daily_report")


def test_get_returns_the_default_before_anything_is_saved(db: Database) -> None:
    text, meta = get_template(db, "enrich")
    assert text == default_template("enrich")
    assert meta["is_default"] is True


def test_a_saved_template_replaces_the_default(db: Database) -> None:
    set_template(db, "enrich", "Do it my way.")
    text, meta = get_template(db, "enrich")
    assert text == "Do it my way."
    assert meta["is_default"] is False


def test_saved_templates_survive_a_reopen(db: Database) -> None:
    set_template(db, "enrich", "Persisted.")
    # A second connection to the same file: templates must not be cached.
    assert get_template(Database(db.path), "enrich")[0] == "Persisted."


def test_reset_restores_the_default(db: Database) -> None:
    set_template(db, "enrich", "Do it my way.")
    reset_template(db, "enrich")
    assert get_template(db, "enrich")[0] == default_template("enrich")


def test_targets_do_not_share_storage(db: Database) -> None:
    set_template(db, "enrich", "Mine.")
    assert get_template(db, "daily_report")[0] == default_template("daily_report")


def test_an_empty_saved_template_is_rejected(db: Database) -> None:
    with pytest.raises(ValueError):
        set_template(db, "enrich", "   ")


def test_an_unknown_target_is_refused(db: Database) -> None:
    with pytest.raises(ValueError):
        set_template(db, "transcription", "x")


def test_reset_of_an_unknown_target_is_refused(db: Database) -> None:
    with pytest.raises(ValueError):
        reset_template(db, "nope")


# ---- substitution --------------------------------------------------------


def test_the_date_placeholder_is_filled() -> None:
    assert "2026-10-09" in substitute("Digest for {date}", "daily_report", date="2026-10-09")


def test_the_today_placeholder_is_filled() -> None:
    assert "2026-10-09" in substitute("Today is {today_iso}", "enrich", today_iso="2026-10-09")


def test_a_stray_brace_does_not_crash() -> None:
    """The whole point: a typo in settings must not break report generation."""
    out = substitute("Use {} for emphasis. Digest for {date}", "daily_report", date="2026-10-09")
    assert "2026-10-09" in out


def test_a_named_brace_the_template_does_not_know_is_left_alone() -> None:
    out = substitute("Keep {name} as written for {date}", "daily_report", date="2026-10-09")
    assert "{name}" in out
    assert "2026-10-09" in out


def test_an_unclosed_brace_does_not_crash() -> None:
    assert substitute("Broken {date", "daily_report", date="2026-10-09")


def test_substitution_on_an_unknown_target_still_fills_nothing_safely() -> None:
    assert substitute("plain text", "nope", date="2026-10-09") == "plain text"


# ---- the templates actually feed the generators ---------------------------


@pytest.mark.anyio
async def test_the_saved_enrichment_template_reaches_the_model(db: Database, monkeypatch) -> None:
    from fleeting.config import LLMConfig
    from fleeting.services import llm as llm_svc

    set_template(db, "enrich", "House rules: never invent a tag.\nToday is {today_iso}.")
    seen: list[dict] = []

    async def fake(url, payload, timeout, headers=None):
        seen.append(payload)
        return '{"title": "t", "summary": "s", "tags": [], "action_items": []}'

    monkeypatch.setattr(llm_svc, "_post_chat", fake)

    # enrich_chain has no db handle, so the caller resolves the template.
    from fleeting.services.prompt_templates import template_for

    await llm_svc.enrich_chain(
        "text",
        LLMConfig(provider="ollama", model="m", timeout_secs=10),
        few_shot="",
        template=template_for(db, "enrich", today_iso="2026-10-09"),
    )
    assert "House rules" in seen[0]["messages"][0]["content"]


def test_the_saved_report_template_reaches_the_digest(db: Database) -> None:
    from fleeting.services.dailylog import build_effective_prompt

    set_template(db, "daily_report", "House rules for reports. Digest for {date}.")
    prompt = build_effective_prompt("2026-10-09", db=db)
    assert "House rules for reports" in prompt
    assert "2026-10-09" in prompt


def test_the_report_template_still_composes_with_a_per_run_override(db: Database) -> None:
    """#348's per-run override and #93's base template must both apply."""
    from fleeting.services.dailylog import build_effective_prompt

    set_template(db, "daily_report", "Base template for {date}.")
    prompt = build_effective_prompt(
        "2026-10-09", db=db, prompt_override="Just this once: mention the outage."
    )
    assert "Base template" in prompt
    assert "mention the outage" in prompt


def test_a_reset_report_template_is_the_shipped_default(db: Database) -> None:
    from fleeting.services.dailylog import build_effective_prompt

    set_template(db, "daily_report", "Mine.")
    reset_template(db, "daily_report")
    prompt = build_effective_prompt("2026-10-09", db=db)
    assert "STRICT RULES" in prompt


# ---- endpoints -----------------------------------------------------------


def test_template_endpoints(client) -> None:
    st = client.app.state.st
    listed = client.get("/api/prompt-templates")
    assert listed.status_code == 200
    assert {t["target"] for t in listed.json()} == {"enrich", "daily_report"}

    saved = client.put("/api/prompt-templates/enrich", json={"body": "Mine."})
    assert saved.status_code == 200
    assert client.get("/api/prompt-templates/enrich").json()["is_default"] is False

    assert client.delete("/api/prompt-templates/enrich").status_code == 200
    assert client.get("/api/prompt-templates/enrich").json()["is_default"] is True


def test_saving_an_empty_template_over_the_api_is_422(client) -> None:
    assert client.put("/api/prompt-templates/enrich", json={"body": "  "}).status_code == 422


def test_an_unknown_target_over_the_api_is_404(client) -> None:
    assert client.put("/api/prompt-templates/nope", json={"body": "x"}).status_code == 404
