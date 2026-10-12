"""#392 golden snapshots for the LLM prompts.

A prompt is behaviour. Reordering two clauses or dropping the line that tells
the model which language to answer in does not raise, does not fail a type
check, and does not break a single existing test — it just quietly makes every
enrichment slightly worse, and nothing notices for weeks.

These are golden files rather than inline expected strings for exactly that
reason: the prompt is 25 lines of prose that has to be *read* when it changes,
and a diff against a separate file is easier to review than a wall of quoted
text in the test body. Regenerate deliberately:

    REGEN_SNAPSHOTS=1 uv run pytest tests/test_prompt_snapshots.py

The composed prompts matter more than the base ones. What the model actually
sees is the base template plus up to four appended blocks, and the *order*
they are appended in is the contract — the user's own corrected enrichments
(#256) have to outrank the tag vocabulary (#257), which has to outrank the
language instruction (#262), with the capture template's own instruction last
because it is the most specific of the four.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest

from fleeting.services.dailylog import DAILY_LOG_SYSTEM, build_effective_prompt
from fleeting.services.llm import (
    ENRICH_SYSTEM_TEMPLATE,
    PRIORITY_SYSTEM_PROMPT,
    build_enrich_system_prompt,
)

GOLDEN_DIR = Path(__file__).parent / "snapshots"

# Frozen so the goldens do not change every midnight. The real call passes
# today's date; here the substitution itself is what is under test.
TODAY = "2026-10-11"


def assert_prompt_snapshot(name: str, actual: str) -> None:
    """Compare against `snapshots/<name>.txt`, or write it when asked to.

    Deliberately fails when the golden is missing rather than creating one:
    a snapshot that materialises on first sight has never been reviewed, which
    is the failure mode snapshots exist to prevent.
    """
    path = GOLDEN_DIR / f"{name}.txt"
    if os.environ.get("REGEN_SNAPSHOTS"):
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(actual)
        return
    if not path.exists():
        pytest.fail(
            f"missing golden {path.name}. Read the prompt above, then run:\n"
            f"  REGEN_SNAPSHOTS=1 uv run pytest tests/test_prompt_snapshots.py"
        )
    expected = path.read_text()
    if actual != expected:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(), actual.splitlines(), "golden", "actual", lineterm=""
            )
        )
        pytest.fail(f"{path.name} changed. Intentional?\n{diff}")


# ---- enrichment -----------------------------------------------------------


def test_enrich_system_base() -> None:
    assert_prompt_snapshot(
        "enrich_system_base", build_enrich_system_prompt(today_iso=TODAY)
    )


def test_enrich_system_with_every_block() -> None:
    """All four optional blocks, in the order they are appended."""
    assert_prompt_snapshot(
        "enrich_system_composed",
        build_enrich_system_prompt(
            today_iso=TODAY,
            few_shot="Corrected examples from this user's history.",
            tag_vocab="Tags this user actually uses: homelab, infra.",
            language="Answer in the same language as the note.",
            prompt="Emphasise anything about the router.",
        ),
    )


def test_an_empty_block_adds_nothing() -> None:
    """A blank block must not leave a double newline behind.

    `build_effective_prompt` guards each of its five with an `if`; a block
    that appends `"\n\n"` unconditionally would be invisible in review and
    would show up as stray blank lines in every prompt.
    """
    prompt = build_enrich_system_prompt(today_iso=TODAY)
    assert not prompt.endswith("\n\n")
    assert "Capture-template instruction" not in prompt
    assert "few_shot" not in prompt


def test_blocks_do_not_accumulate_across_calls() -> None:
    """Composition must not mutate the module-level template.

    `ENRICH_SYSTEM` is built once at import. If the composer appended to it in
    place, a second enrichment would carry the first one's instructions.
    """
    # A token that cannot occur in the prose. An earlier version asserted
    # `"one" not in second`, which matched inside "mentioned".
    marker = "ZZcapture-template-markerZZ"
    first = build_enrich_system_prompt(today_iso=TODAY, prompt=marker)
    second = build_enrich_system_prompt(today_iso=TODAY)
    assert f"Capture-template instruction: {marker}" in first
    assert marker not in second
    assert ENRICH_SYSTEM_TEMPLATE not in (first, second)


def test_priority_system() -> None:
    assert_prompt_snapshot("priority_system", PRIORITY_SYSTEM_PROMPT)


# ---- daily digest ---------------------------------------------------------


def test_daily_log_system() -> None:
    assert_prompt_snapshot("daily_log_system", DAILY_LOG_SYSTEM.replace("{date}", TODAY))


def test_daily_log_with_every_option() -> None:
    assert_prompt_snapshot(
        "daily_log_composed",
        build_effective_prompt(
            TODAY,
            tone="punchy",
            highlights_only=True,
            questions_for_tomorrow=True,
            custom_sections=[{"title": "Reading"}, {"title": "Gym"}],
            prompt_override="Mention the router work.",
        ),
    )
