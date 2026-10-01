"""Unit tests for the offline enrichment fallback and JSON parsing."""

from __future__ import annotations

from fleeting.services.llm import _parse_json_loose, _sanitize, heuristic_enrich


def test_heuristic_title_and_tasks():
    text = (
        "Docker networking fix\n"
        "The bridge network broke after the upgrade.\n"
        "todo: recreate the bridge network\n"
        "remember to pin the docker version"
    )
    out = heuristic_enrich(text)
    assert out["title"].startswith("Docker networking fix")
    assert len(out["action_items"]) == 2
    assert any("bridge network" in t["text"] for t in out["action_items"])


def test_heuristic_empty_input():
    out = heuristic_enrich("   ")
    assert out["title"] == "Empty capture"


def test_heuristic_tags_from_frequent_words():
    out = heuristic_enrich("rust rust rust borrow checker borrow checker ownership")
    assert "rust" in out["tags"]


def test_parse_json_loose_plain():
    assert _parse_json_loose('{"title": "hi"}') == {"title": "hi"}


def test_parse_json_loose_fenced():
    content = "```json\n{\"title\": \"hi\", \"tags\": []}\n```"
    assert _parse_json_loose(content)["title"] == "hi"


def test_parse_json_loose_with_prose():
    content = 'Sure! Here is the result:\n{"title": "x"}\nHope that helps.'
    assert _parse_json_loose(content) == {"title": "x"}


def test_parse_json_loose_garbage():
    assert _parse_json_loose("no json at all") is None
    assert _parse_json_loose("") is None


def test_sanitize_tags():
    out = _sanitize(
        {"title": "  T  ", "summary": "s", "tags": ["#AI", "Machine Learning", "!!", "ai"], "action_items": "one task"}
    )
    assert out["tags"] == ["ai", "machine-learning"]
    assert out["action_items"] == ["one task"]
    assert out["title"] == "T"


def test_sanitize_long_title():
    out = _sanitize({"title": "x" * 200, "summary": "", "tags": [], "action_items": []})
    assert len(out["title"]) <= 80
