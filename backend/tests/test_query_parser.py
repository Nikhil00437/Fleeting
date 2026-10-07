"""Query parser tests: operator syntax (#313) and phrase/proximity search (#318).

Unit tests pin the parse tree and the generated FTS5 MATCH strings; the db
tests prove those strings execute against the real FTS table and that the
structured filters behave identically on the FTS and non-FTS scan paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.query_parser import (
    build_fts_match,
    note_matches_parsed,
    parse_query,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_empty_query_parses_to_nothing() -> None:
    p = parse_query("")
    assert not p.has_constraints
    assert build_fts_match(p) is None
    assert p.free_text() == ""


def test_plain_terms_and_prefix_matching() -> None:
    p = parse_query("Router Setup")
    assert p.terms == ["Router", "Setup"]
    assert build_fts_match(p) == '"Router"* "Setup"*'


def test_quoted_phrase_is_exact_not_prefix() -> None:
    p = parse_query('"borrow checker" rust')
    assert p.phrases == ["borrow checker"]
    assert p.terms == ["rust"]
    assert build_fts_match(p) == '"rust"* "borrow checker"'
    assert p.free_text() == "borrow checker rust"


def test_exclusion_operator() -> None:
    p = parse_query("meeting -draft")
    assert p.terms == ["meeting"]
    assert p.excluded == ["draft"]
    assert build_fts_match(p) == '("meeting"*) NOT ("draft"*)'
    assert p.free_text() == "meeting"


def test_excluded_phrase() -> None:
    p = parse_query("router -\"firmware update\"")
    assert p.terms == ["router"]
    assert p.excluded_phrases == ["firmware update"]
    assert build_fts_match(p) == '("router"*) NOT ("firmware update")'


def test_internal_hyphens_are_terms_not_exclusions() -> None:
    p = parse_query("state-of-mind")
    assert p.terms == ["state-of-mind"]
    assert p.excluded == []


def test_tag_operator_strips_hash_and_lowercases() -> None:
    p = parse_query("tag:Work tag:#infra")
    assert p.tags == ["work", "infra"]
    assert p.terms == []


def test_type_operator_is_repeatable_or() -> None:
    p = parse_query("type:voice type:youtube")
    assert p.types == ["voice", "youtube"]


def test_unknown_operator_degrades_to_term() -> None:
    p = parse_query("foo:bar planning")
    assert p.terms == ["foobar", "planning"]
    assert build_fts_match(p) == '"foobar"* "planning"*'


def test_invalid_dates_are_dropped_not_embedded() -> None:
    p = parse_query("before:notadate after:2026-13-45 router")
    assert p.before is None
    assert p.after is None
    assert p.terms == ["router"]


def test_valid_dates_are_kept() -> None:
    p = parse_query("after:2026-01-01 before:2026-02-01")
    assert p.after == "2026-01-01"
    assert p.before == "2026-02-01"


def test_starred_and_audio_flags() -> None:
    p = parse_query("is:starred has:audio")
    assert p.starred is True
    assert p.has_audio is True


def test_near_groups_the_two_preceding_units() -> None:
    p = parse_query('"wireless setup" router near:5')
    assert p.near == ("wireless setup", "router", 5)
    assert p.phrases == []
    assert p.terms == []
    assert build_fts_match(p) == 'NEAR("wireless setup" "router", 5)'


def test_near_with_one_unit_becomes_a_term() -> None:
    p = parse_query("solo near:3")
    assert p.near is None
    assert p.terms == ["solo", "near3"]


def test_exclusions_and_filters_count_as_constraints() -> None:
    p = parse_query("-draft")
    assert p.has_constraints
    assert not p.has_positive
    p = parse_query("tag:work")
    assert p.has_constraints


# ---------------------------------------------------------------------------
# db.search integration — FTS path
# ---------------------------------------------------------------------------


def _seed(db: Database) -> dict[str, str]:
    a = db.insert_note({
        "title": "Router firmware update",
        "raw_text": "The wireless setup guide for the router and its firmware.",
        "tags": ["work", "infra"],
        "type": "text",
    })
    b = db.insert_note({
        "title": "Pasta recipe",
        "raw_text": "Boil water, add pasta, draft a shopping list for tomatoes.",
        "tags": ["#cooking"],
        "type": "text",
    })
    c = db.insert_note({
        "title": "Voice memo about the router",
        "raw_text": "Remember to reset the router password.",
        "tags": ["home"],
        "type": "voice",
        "audio_path": "/data/audio/x.webm",
    })
    return {"a": a["id"], "b": b["id"], "c": c["id"]}


def test_search_exclusion_via_fts(db: Database) -> None:
    ids = _seed(db)
    hits = db.search("router -firmware")
    assert [h["id"] for h in hits] == [ids["c"]]


def test_search_exact_phrase_beats_prefix(db: Database) -> None:
    ids = _seed(db)
    # Prefix "firmware" alone matches note a; the exact phrase "wireless
    # setup" also only lives in note a — but "reset the router" as a phrase
    # must match only the voice note (prefix mode would still match note a's
    # "router and..." — actually prefix matches only on word boundaries, so
    # assert the phrase is found at all and the non-matching note is absent).
    hits = db.search('"reset the router password"')
    assert [h["id"] for h in hits] == [ids["c"]]
    # And a phrase that exists nowhere finds nothing, proving exactness.
    assert db.search('"router password reset"') == []


def test_search_tag_filter(db: Database) -> None:
    ids = _seed(db)
    hits = db.search("tag:work")
    assert {h["id"] for h in hits} == {ids["a"]}
    # Tags stored with a leading '#' still match.
    hits = db.search("tag:cooking")
    assert {h["id"] for h in hits} == {ids["b"]}


def test_search_type_filter(db: Database) -> None:
    ids = _seed(db)
    hits = db.search("type:voice")
    assert {h["id"] for h in hits} == {ids["c"]}


def test_search_has_audio_filter(db: Database) -> None:
    ids = _seed(db)
    hits = db.search("has:audio")
    assert {h["id"] for h in hits} == {ids["c"]}


def test_search_date_range_filter(db: Database) -> None:
    ids = _seed(db)
    # All three notes were created "now" (UTC); a window that ends yesterday
    # excludes everything, one that starts yesterday includes everything.
    assert db.search("before:2020-01-01") == []
    hits = db.search("after:2020-01-01 before:2999-01-01")
    assert {h["id"] for h in hits} == set(ids.values())


def test_search_filters_only_scan_path(db: Database) -> None:
    ids = _seed(db)
    # No positive text units: filters alone drive the non-FTS scan.
    hits = db.search("tag:work has:audio")
    assert hits == []
    hits = db.search("type:voice tag:home")
    assert {h["id"] for h in hits} == {ids["c"]}
    # Exclusions alone are a valid query.
    hits = db.search("-router")
    assert {h["id"] for h in hits} == {ids["b"]}


def test_search_near_requires_proximity(db: Database) -> None:
    # FTS5's NEAR window N must be >= the number of tokens strictly between
    # the two phrases (verified empirically): gap 0 matches N=1, gap 1
    # matches N=1, gap 6 needs N>=6.
    adj_note = db.insert_note({
        "title": "Adjacent",
        "raw_text": "router wifi adjacent pair.",
    })
    near_note = db.insert_note({
        "title": "Near",
        "raw_text": "The router and wifi work together.",
    })
    far_note = db.insert_note({
        "title": "Far",
        "raw_text": "The router sits in the hallway while the wifi repeater is upstairs.",
    })
    assert {h["id"] for h in db.search("router wifi near:1")} == {adj_note["id"], near_note["id"]}
    assert {h["id"] for h in db.search("router wifi near:4")} == {adj_note["id"], near_note["id"]}
    assert {h["id"] for h in db.search("router wifi near:6")} == {
        adj_note["id"],
        near_note["id"],
        far_note["id"],
    }
    # Proximity must not leak into semantic free text weirdly — it is text.
    assert parse_query("router wifi near:4").free_text() == "router wifi"


# ---------------------------------------------------------------------------
# Python-side filter (semantic leg)
# ---------------------------------------------------------------------------


def test_note_matches_parsed_mirrors_sql_filters(db: Database) -> None:
    ids = _seed(db)
    note_c = db.get_note(ids["c"])

    assert note_matches_parsed(note_c, parse_query("type:voice"))
    assert not note_matches_parsed(note_c, parse_query("type:text"))
    assert note_matches_parsed(note_c, parse_query("has:audio tag:home"))
    assert not note_matches_parsed(note_c, parse_query("tag:work"))
    assert note_matches_parsed(note_c, parse_query("-grocery"))
    assert not note_matches_parsed(note_c, parse_query("-password -reset"))
    assert note_matches_parsed(note_c, parse_query("after:2020-01-01"))
    assert not note_matches_parsed(note_c, parse_query("before:2020-01-01"))
    assert not note_matches_parsed(note_c, parse_query("is:starred"))
