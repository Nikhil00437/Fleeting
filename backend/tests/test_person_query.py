"""#418: `person:` in the shared query parser.

Operator syntax lands in `query_parser` and nowhere else (#313, #318), so
`person:Priya` has to work there or it will not work in the UI, in saved
queries or in MCP — and a second parser would be three operators that
disagree.
"""

from __future__ import annotations

import pytest

from fleeting.db import Database
from fleeting.services.query_parser import (
    build_fts_match,
    note_matches_parsed,
    parse_query,
)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


# ---- parsing -------------------------------------------------------------


def test_person_operator_parses() -> None:
    p = parse_query("person:Priya")
    assert p.people == ["Priya"]


def test_person_operator_is_case_insensitive_in_the_key() -> None:
    assert parse_query("PERSON:Priya").people == ["Priya"]


def test_a_two_word_person_is_kept_whole() -> None:
    assert parse_query('person:"Arjun Mehta"').people == ["Arjun Mehta"]


def test_an_unquoted_two_word_person_survives_the_quote_repair() -> None:
    assert parse_query("person:Arjun Mehta").people == ["Arjun Mehta"]


def test_person_does_not_leak_into_the_free_text() -> None:
    """The embedder must not be handed an operator as a word to rank."""
    p = parse_query("person:Priya router")
    assert "person" not in p.free_text().lower()
    assert "Priya" not in p.free_text()


def test_person_alone_is_a_valid_query() -> None:
    p = parse_query("person:Priya")
    assert p.has_constraints


def test_a_bare_person_operator_is_ignored() -> None:
    assert parse_query("person:").people == []


def test_person_combines_with_other_operators() -> None:
    p = parse_query("person:Priya after:2026-08-01")
    assert p.people == ["Priya"]
    assert p.after == "2026-08-01"


# ---- evaluation ----------------------------------------------------------


def _note(text: str, created: str = "2026-09-01T00:00:00+00:00") -> dict:
    return {"raw_text": text, "created_at": created, "tags": [], "type": "text"}


def test_a_note_naming_the_person_matches(db: Database) -> None:
    p = parse_query("person:Priya")
    assert note_matches_parsed(_note("Priya reviewed the router."), p) is True


def test_a_note_not_naming_the_person_is_excluded(db: Database) -> None:
    p = parse_query("person:Priya")
    assert note_matches_parsed(_note("Tom reviewed the router."), p) is False


def test_the_person_filter_does_not_match_a_stoplisted_capital() -> None:
    """'The bridge network' must not satisfy person:The."""
    p = parse_query("person:The")
    assert note_matches_parsed(_note("The bridge network broke."), p) is False


def test_matching_uses_the_whole_name_not_a_prefix(db: Database) -> None:
    p = parse_query("person:Priya")
    assert note_matches_parsed(_note("Priyanne left a comment."), p) is False


def test_person_composes_with_the_date_filter(db: Database) -> None:
    p = parse_query("person:Priya after:2026-08-01")
    assert note_matches_parsed(_note("Priya called.", "2026-09-01"), p) is True
    assert note_matches_parsed(_note("Priya called.", "2026-07-01"), p) is False


# ---- the FTS leg ---------------------------------------------------------


def test_the_name_participates_in_the_fts_match() -> None:
    """Ranking needs the name in the MATCH, not only in the post-filter."""
    match = build_fts_match(parse_query("person:Priya"))
    assert match is not None
    assert "Priya" in match


def test_fts_and_the_post_filter_agree(db: Database) -> None:
    p = parse_query("person:Priya")
    assert build_fts_match(p) is not None
    assert note_matches_parsed(_note("Priya reviewed."), p) is True


@pytest.mark.anyio
async def test_search_endpoint_finds_notes_by_person(client) -> None:
    client.post("/api/capture/text", json={"text": "Priya reviewed the router change."})
    client.post("/api/capture/text", json={"text": "Unrelated sourdough note."})
    r = client.get("/api/search", params={"q": "person:Priya"})
    assert r.status_code == 200
    bodies = [n.get("raw_text", "") for n in r.json()]
    assert any("Priya" in t for t in bodies)
    assert not any("sourdough" in t for t in bodies)
