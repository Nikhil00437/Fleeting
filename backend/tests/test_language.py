"""#262 per-language enrichment prompts with automatic language detection.

The note's own language is detected from its script, deterministically, and
turned into one instruction added to the enrichment prompt. No model call to
detect a language, because detecting a language is pattern matching and the
model is the slowest, least reliable way to do it.

Deliberately an instruction and not a separate template per language. Per-task
templates already exist (#92) and a second axis multiplying them is a matrix
nobody will maintain. What actually goes wrong without this is the model
answering a note in the language of the *instruction* rather than the note,
and one sentence in the prompt fixes that.

Script detection is coarse on purpose. It can tell CJK from Latin from
Cyrillic from Arabic, and it will confidently call a mixed note by its dominant
script. That is the honest ceiling: it is a script detector wearing a language
detector's name, and the wording should not pretend otherwise.
"""

from __future__ import annotations

import pytest

from fleeting.config import LLMConfig
from fleeting.services.language import (
    detect_language,
    language_instruction,
)


def _cfg() -> LLMConfig:
    return LLMConfig(provider="ollama", model="m")


# ---- detection -----------------------------------------------------------


def test_a_english_note_is_english() -> None:
    assert detect_language("call the dentist about the appointment").name == "English"


def test_a_chinese_note_is_chinese() -> None:
    zh = "我需要重新配置路由器的固件，因为升级之后无线网络就不能用了"
    assert detect_language(zh).name == "Chinese"


def test_a_japanese_note_is_japanese() -> None:
    assert detect_language("明日の朝までに路由器の設定を直してください").name == "Japanese"


def test_a_cyrillic_note_is_russian() -> None:
    assert detect_language("настроить маршрутизатор перед обновлением").name == "Russian"


def test_an_empty_note_is_unknown_rather_than_guessed() -> None:
    """A default would put "write in English" into every unknown note."""
    assert detect_language("").name == "Unknown"
    assert detect_language("   ").name == "Unknown"


def test_punctuation_only_is_unknown() -> None:
    assert detect_language("... --- !!!").name == "Unknown"


def test_a_mixed_note_goes_by_its_dominant_script() -> None:
    """Priya's name inside a Chinese note must not flip the whole note."""
    text = "Priya 说要在下周一之前把路由器配置好"
    assert detect_language(text).name == "Chinese"


def test_a_mostly_english_note_with_a_name_is_english() -> None:
    assert detect_language("ask Priya about the invoice").name == "English"


# ---- the instruction -----------------------------------------------------


def test_an_english_note_gets_no_language_instruction() -> None:
    """The enrichment prompt is already English; saying so is noise."""
    assert language_instruction(detect_language("call the dentist")) == ""


def test_a_chinese_note_is_told_to_stay_chinese() -> None:
    instruction = language_instruction(detect_language("我喜欢吃麻烦龙"))
    assert instruction
    assert "Chinese" in instruction


def test_the_instruction_says_to_keep_names_intact() -> None:
    """The names are the one thing that must not be transliterated."""
    instruction = language_instruction(detect_language("我喜欢吃麻烦龙"))
    assert "name" in instruction.lower()


def test_an_unknown_note_gets_no_instruction() -> None:
    assert language_instruction(detect_language("")) == ""


# ---- the prompt ----------------------------------------------------------


# ---- reaching the prompt -------------------------------------------------


def _capture_system(monkeypatch) -> list[str]:
    """enrich_chain posts inline, so the prompt is read off the wire."""

    from fleeting.services import llm as llm_svc

    seen: list[str] = []

    async def fake_post(url, payload, timeout, headers=None):
        seen.append(payload["messages"][0]["content"])
        return '{"title":"t","summary":"s","tags":[]}'

    monkeypatch.setattr(llm_svc, "_post_chat", fake_post)
    return seen


@pytest.mark.anyio
async def test_the_language_line_reaches_the_enrichment_prompt(monkeypatch) -> None:
    from fleeting.services import llm as llm_svc

    seen = _capture_system(monkeypatch)

    await llm_svc.enrich_chain(
        "x", _cfg(), language=language_instruction(detect_language("我喜欢吃麻烦龙"))
    )

    assert seen and "Chinese" in seen[0]


@pytest.mark.anyio
async def test_an_english_note_adds_nothing_to_the_prompt(monkeypatch) -> None:
    from fleeting.services import llm as llm_svc

    seen = _capture_system(monkeypatch)

    await llm_svc.enrich_chain(
        "x", _cfg(), language=language_instruction(detect_language("call the dentist"))
    )

    assert seen and "Chinese" not in seen[0]
