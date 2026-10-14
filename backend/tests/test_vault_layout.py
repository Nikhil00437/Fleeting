"""#114 frontmatter schema and #115 folder mapping rules.

Both are **configuration**, not code — the whole point is that a user who wants
every note under `Inbox/text/`, or a `project:` field in their frontmatter, does
not have to edit Python and wait for a release.

The properties that matter are almost all about not losing things, because these
two functions decide where files go and what goes in them:

1. **A slug is never empty.** `{{first_tag}}` on an untagged note must not produce
   the vault root. It goes to `untagged/` — a folder you can find and move — rather
   than a file loose in the root where the next untagged note also lands.
2. **Traversal is refused before slugging.** Slugifying `../../etc` yields `etc`,
   which is harmless but wrong; relying on the slug to neutralise a path is
   relying on a coincidence. Segments are checked individually because a template
   is several segments and a traversal that only works across a separator is
   otherwise invisible.
3. **Blank frontmatter is omitted, not written empty.** A block full of `status:`
   with nothing after it is noise every tool has to special-case, and it makes
   "which notes have a status" unanswerable by eye.
4. **The default folder template is unchanged.** `{{year}}` is what the mirror has
   always done, and silently relocating five years of notes is not a decision to
   make on someone's behalf.
5. **Tokens are an allow-list.** A template is user input; a deny-list is a list of
   things nobody thought of.
"""

from __future__ import annotations

import pytest

from fleeting.services.vault_layout import (
    DEFAULT_FOLDER_TEMPLATE,
    TOKENS,
    folder_for,
    frontmatter_lines,
    parse_schema,
    safe_segment,
    slug,
    validate_schema,
)


def note(**extra) -> dict:
    return {
        "id": "n1",
        "type": "text",
        "created_at": "2026-01-02T09:00:00+00:00",
        "tags": [],
        "frontmatter": {},
        **extra,
    }


# ---- folder rules ----------------------------------------------------------


def test_the_default_keeps_the_year_layout() -> None:
    """Silently relocating five years of notes is not a decision to make on
    someone's behalf."""
    assert DEFAULT_FOLDER_TEMPLATE == "{{year}}"
    assert folder_for(DEFAULT_FOLDER_TEMPLATE, note()) == "2026"


def test_a_type_folder_rule() -> None:
    assert folder_for("{{type}}", note(type="youtube")) == "youtube"


def test_a_tag_folder_rule() -> None:
    assert folder_for("{{first_tag}}", note(tags=["fleeting"])) == "fleeting"


def test_tags_combine_with_type() -> None:
    assert folder_for("{{first_tag}}/{{type}}", note(tags=["work"], type="text")) == "work/text"


def test_a_literal_prefix_keeps_its_case() -> None:
    """Someone who typed `Inbox/` wants `Inbox/`, and lowercasing it is a surprise
    with no security benefit — the segment holds no traversal."""
    assert folder_for("Inbox/{{first_tag}}", note(tags=["work"])) == "Inbox/work"


def test_an_untagged_note_gets_a_real_folder() -> None:
    """Not the vault root: an untagged note loose in the root is a file you
    cannot find, and the next untagged note lands there too."""
    assert folder_for("{{first_tag}}", note(tags=[])) == "untagged"


def test_an_empty_tag_list_is_handled() -> None:
    assert folder_for("{{first_tag}}", note(tags=None)) == "untagged"


def test_a_note_with_no_date_goes_somewhere() -> None:
    assert folder_for("{{year}}", note(created_at="", created=None)) == "undated"


def test_the_month_token_is_available() -> None:
    assert folder_for("{{year}}-{{month}}", note()) == "2026-2026-01"


# ---- traversal -------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    ["../../../etc", "..", ".", "a/b", "a\\b", "/absolute", "~/secrets"],
)
def test_a_traversal_cannot_escape_the_vault(hostile) -> None:
    """Checked before slugging: slugifying `../../etc` gives `etc`, which is
    harmless but wrong, and relying on the slug to neutralise a path is relying on
    a coincidence."""
    result = folder_for(hostile, note())
    assert ".." not in result.split("/")
    assert not result.startswith("/")


def test_a_hostile_tag_is_replaced_not_sanitised() -> None:
    """Tags come from speech recognition and from the model.

    Asserted against the *fallback*, not merely "no `..` in the result": slugifying
    `../../../etc` on its own yields `etc`, which contains no traversal and is
    still the wrong answer. The guard has to run before the slugifier.
    """
    from fleeting.services.vault_layout import TOKEN_FALLBACK

    assert folder_for("{{first_tag}}", note(tags=["../../../etc"])) == TOKEN_FALLBACK["first_tag"]


def test_every_segment_is_checked_separately() -> None:
    """A traversal that only works across a separator is otherwise invisible."""
    # A literal `..` is a typo, so it drops rather than becoming a placeholder:
    # the result is nearly what was asked for instead of a row of `untitled`.
    assert folder_for("safe/../../escape", note()) == "safe/escape"


def test_an_unknown_token_becomes_a_literal_folder() -> None:
    """Silently ignoring it would put the note somewhere the user did not ask for
    and say nothing."""
    assert folder_for("{{nonsense}}", note()) == "unknown-nonsense"


def test_tokens_are_an_allow_list() -> None:
    assert set(TOKENS) == {"year", "type", "first_tag", "month"}


def test_safe_segment_never_returns_empty() -> None:
    for hostile in ("", "   ", "---", "!!!", "🎉", "../", ".."):
        assert safe_segment(hostile, "fallback") == "fallback"


def test_a_token_fallback_names_its_own_field() -> None:
    """`untitled` in place of a tag tells you nothing; `untagged/` is a folder
    you can find and move."""
    from fleeting.services.vault_layout import TOKEN_FALLBACK

    assert folder_for("{{first_tag}}", note(tags=[".."])) == TOKEN_FALLBACK["first_tag"]
    assert folder_for("{{year}}", note(created_at="", created=None)) == TOKEN_FALLBACK["year"]


def test_slug_is_stable_and_readable() -> None:
    assert slug("Project Fleeting!") == "project-fleeting"
    assert slug("  Multiple   Spaces  ") == "multiple-spaces"


def test_slug_folds_accents() -> None:
    assert slug("café") == "cafe"


# ---- frontmatter schema ----------------------------------------------------


def test_no_schema_is_configured_by_default() -> None:
    """Notes keep the built-in frontmatter and nothing else."""
    assert validate_schema("")["fields"] == []


def test_a_schema_parses_in_order() -> None:
    """Order is the schema: frontmatter is read top to bottom, and an order that
    jumps around is one nobody can scan."""
    assert parse_schema("project, client, status") == ["project", "client", "status"]


def test_duplicate_fields_collapse() -> None:
    assert parse_schema("project, project") == ["project"]


@pytest.mark.parametrize("bad", ["1bad", "has space!", "-leading", "", "  "])
def test_invalid_field_names_are_dropped(bad) -> None:
    """A typo in a config file should not stop the app starting."""
    assert parse_schema(bad) == []


def test_a_dropped_field_is_reported() -> None:
    """Otherwise a policy that quietly does nothing is indistinguishable from one
    that is working."""
    described = validate_schema("project, 1bad")
    assert described["fields"] == ["project"]
    assert "1bad" in described["ignored"]


def test_one_bad_field_does_not_lose_the_good_ones() -> None:
    assert parse_schema("project, 1bad, client") == ["project", "client"]


# ---- rendering frontmatter -------------------------------------------------


def test_fields_render_in_schema_order() -> None:
    n = note(frontmatter={"status": "active", "project": "fleeting"})
    assert frontmatter_lines(n, ["project", "status"]) == [
        "project: fleeting",
        "status: active",
    ]


def test_a_note_without_the_field_renders_nothing_for_it() -> None:
    assert frontmatter_lines(note(frontmatter={"project": "x"}), ["project", "status"]) == [
        "project: x"
    ]


def test_a_blank_value_is_omitted() -> None:
    """A block full of `status:` with nothing after it is noise every tool has to
    special-case, and it makes 'which notes have a status' unanswerable by eye."""
    assert frontmatter_lines(note(frontmatter={"project": "", "client": "acme"}), ["project", "client"]) == [
        "client: acme"
    ]


def test_a_whitespace_only_value_is_omitted() -> None:
    assert frontmatter_lines(note(frontmatter={"status": "   "}), ["status"]) == []


def test_a_note_with_no_frontmatter_renders_nothing() -> None:
    assert frontmatter_lines(note(), ["project", "status"]) == []


def test_a_malformed_frontmatter_value_does_not_raise() -> None:
    """Every read path goes through the render, so raising here breaks sync."""
    assert frontmatter_lines(note(frontmatter="not a dict"), ["project"]) == []


def test_a_field_absent_from_the_schema_is_not_rendered() -> None:
    """The schema is the schema — a stray key in one note's JSON is not a licence
    to add a line only that note has."""
    n = note(frontmatter={"project": "x", "secret": "do not leak"})
    assert frontmatter_lines(n, ["project"]) == ["project: x"]


def test_describing_nothing_still_explains_itself() -> None:
    assert "built-in" in validate_schema("")["explains"]


# ---- the endpoints ---------------------------------------------------------


def test_the_schema_endpoint_reports_the_fields(client) -> None:
    body = client.get("/api/vault/frontmatter").json()
    assert body["schema"]["fields"] == []


def test_the_schema_can_be_set(client) -> None:
    r = client.put("/api/vault/frontmatter", json={"schema": "project, client"})
    assert r.status_code == 200, r.text
    assert client.get("/api/vault/frontmatter").json()["schema"]["fields"] == ["project", "client"]


def test_a_rejected_field_is_reported_rather_than_silently_dropped(client) -> None:
    body = client.put("/api/vault/frontmatter", json={"schema": "project, 1bad"}).json()
    assert "1bad" in body["schema"]["ignored"]


def test_the_folder_endpoint_reports_where_a_note_would_go(client) -> None:
    from conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "where does this go"}).json()["id"]
    wait_done(client, note_id)
    body = client.get(f"/api/vault/folder/{note_id}").json()
    assert body["folder"].endswith(body["year"])


def test_setting_a_folder_template_changes_where_notes_go(client) -> None:
    from conftest import wait_done

    client.put("/api/vault/folder-template", json={"template": "Inbox/{{type}}"})
    note_id = client.post("/api/capture/text", json={"text": "a note"}).json()["id"]
    wait_done(client, note_id)
    assert client.get(f"/api/vault/folder/{note_id}").json()["folder"] == "Inbox/text"


def test_a_hostile_folder_template_is_rejected(client) -> None:
    r = client.put("/api/vault/folder-template", json={"template": "../../etc"})
    assert r.status_code in (400, 422), r.text

# ---- persistence -----------------------------------------------------------
#
# The layout functions are pure, so none of the above proves the *column* works.
# These do — and two of them exist because mutation checking found that the
# tests were asserting the pure functions while the storage path had no
# coverage at all.


def test_frontmatter_round_trips_through_the_database(tmp_path) -> None:
    from fleeting.db import Database

    db = Database(str(tmp_path / "f.db"))
    db.migrate()
    db.insert_note({"id": "n1", "title": "t", "raw_text": "r", "frontmatter": {"project": "fleeting"}})
    db.commit()
    assert db.get_note("n1")["frontmatter"] == {"project": "fleeting"}


def test_provenance_round_trips_through_the_database(tmp_path) -> None:
    from fleeting.db import Database

    db = Database(str(tmp_path / "f.db"))
    db.migrate()
    db.insert_note({"id": "n1", "title": "t", "raw_text": "r", "provenance": "youtube"})
    db.commit()
    assert db.get_note("n1")["provenance"] == "youtube"


def test_a_note_with_neither_column_still_inserts(tmp_path) -> None:
    """sqlite3 binds named parameters strictly, so a column added to the INSERT
    without a default makes *every* insert that omits it raise. Both columns
    landed that way."""
    from fleeting.db import Database

    db = Database(str(tmp_path / "f.db"))
    db.migrate()
    db.insert_note({"id": "n1", "title": "t", "raw_text": "r"})
    db.commit()
    assert db.get_note("n1")["frontmatter"] == {}


def test_frontmatter_can_be_patched(tmp_path) -> None:
    """A dict bound straight through raises "type 'dict' is not supported", which
    looks like a validation error and is a missing encoder."""
    from fleeting.db import Database

    db = Database(str(tmp_path / "f.db"))
    db.migrate()
    db.insert_note({"id": "n1", "title": "t", "raw_text": "r"})
    db.commit()
    db.update_note("n1", {"frontmatter": {"project": "other"}})
    assert db.get_note("n1")["frontmatter"] == {"project": "other"}


def test_a_malformed_frontmatter_column_does_not_take_out_every_read(tmp_path) -> None:
    """`_row_to_note` is the read funnel for the whole app. A ValueError here
    breaks every list, every search and every report, not just this field."""
    from fleeting.db import Database

    db = Database(str(tmp_path / "f.db"))
    db.migrate()
    db.insert_note({"id": "n1", "title": "t", "raw_text": "r"})
    db.execute("UPDATE notes SET frontmatter = 'just a word' WHERE id = 'n1'")
    db.commit()
    assert db.get_note("n1")["frontmatter"] == {}
    assert db.get_note("n1")["title"] == "t"
