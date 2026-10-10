"""#109: natural-language bulk edits, previewed before anything is written.

The contract that matters is the one that is easy to get wrong: a bulk edit
that names the wrong notes is not recoverable by editing them back, because
you cannot see which ones were wrong. So the first call never writes, the
second writes exactly what the first showed, and undo puts every touched
field back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.actions import execute_action, undo_action
from fleeting.services.assistant import _format_action_result


@pytest.fixture
def env(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    cfg = Config()
    cfg.paths.vault_dir = str(tmp_path / "vault")
    bus = EventBus()
    return db, cfg, bus


def _note(db: Database, title: str, body: str = "", **kw) -> str:
    return db.insert_note({"title": title, "raw_text": body or title, "status": "done", **kw})[
        "id"
    ]


def _tags(db: Database, note_id: str) -> list[str]:
    note = db.get_note(note_id)
    return sorted(str(t) for t in (note.get("tags") or []))


# ---- phase one writes nothing ---------------------------------------------


@pytest.mark.anyio
async def test_the_first_call_only_previews(env):
    db, cfg, bus = env
    _note(db, "router notes", "the router needs a reflash")

    res = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )

    assert res["ok"] is True
    assert res["count"] == 1
    assert res["matches"][0]["title"] == "router notes"
    assert res["preview_token"]


@pytest.mark.anyio
async def test_previewing_does_not_change_a_single_note(env):
    db, cfg, bus = env
    nid = _note(db, "router notes", "the router needs a reflash")

    await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )

    assert _tags(db, nid) == []


@pytest.mark.anyio
async def test_a_blank_query_is_refused(env):
    db, cfg, bus = env
    _note(db, "anything")

    res = await execute_action(
        "bulk_edit", {"query": "   ", "operation": "add_tag", "value": "x"}, db, cfg, bus
    )

    assert res["ok"] is False
    assert "query" in res["error"].lower()


@pytest.mark.anyio
async def test_a_query_matching_too_many_notes_is_refused_not_truncated(env):
    """Silently editing the first 200 of 5000 is worse than refusing."""
    db, cfg, bus = env
    for i in range(205):
        _note(db, f"router note {i}", "router")

    res = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )

    assert res["ok"] is False
    assert "200" in res["error"] or "many" in res["error"].lower()


# ---- phase two writes what the preview showed -----------------------------


@pytest.mark.anyio
async def test_confirming_applies_the_edit(env):
    db, cfg, bus = env
    nid = _note(db, "router notes", "the router needs a reflash")

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    res = await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    assert res["ok"] is True
    assert res["count"] == 1
    assert "homelab" in _tags(db, nid)


@pytest.mark.anyio
async def test_confirming_edits_the_frozen_set_not_a_fresh_query(env):
    """The user approved three notes. A note written since must not be caught."""
    db, cfg, bus = env
    approved = _note(db, "router one", "router")
    _note(db, "router two", "router")
    _note(db, "router three", "router")

    preview = await execute_action(
        "bulk_edit",
        {"query": "router one", "operation": "add_tag", "value": "homelab"},
        db,
        cfg,
        bus,
    )
    assert preview["count"] == 1

    late = _note(db, "router four", "router")
    res = await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "value": "something else", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    assert res["ok"] is True
    assert _tags(db, late) == []
    assert _tags(db, approved) == ["homelab"]


@pytest.mark.anyio
async def test_an_unknown_preview_token_is_refused(env):
    db, cfg, bus = env
    _note(db, "router", "router")

    res = await execute_action(
        "bulk_edit", {"operation": "add_tag", "preview_token": "made-up"}, db, cfg, bus
    )

    assert res["ok"] is False


@pytest.mark.anyio
async def test_a_preview_cannot_be_replayed_twice(env):
    db, cfg, bus = env
    nid = _note(db, "router one", "router")

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )
    again = await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    assert again["ok"] is False
    assert _tags(db, nid) == ["homelab"]


@pytest.mark.anyio
async def test_a_tag_is_never_added_twice(env):
    db, cfg, bus = env
    nid = _note(db, "router", "router", tags=["homelab"])

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    res = await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    assert res["ok"] is True
    assert res["changed"] == 0
    assert _tags(db, nid) == ["homelab"]


# ---- the other operations -------------------------------------------------


@pytest.mark.anyio
async def test_remove_tag(env):
    db, cfg, bus = env
    nid = _note(db, "router", "router", tags=["homelab", "network"])

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "remove_tag", "value": "homelab"}, db, cfg, bus
    )
    await execute_action(
        "bulk_edit",
        {"operation": "remove_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    assert _tags(db, nid) == ["network"]


@pytest.mark.anyio
async def test_archive(env):
    db, cfg, bus = env
    nid = _note(db, "router", "router")

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "archive"}, db, cfg, bus
    )
    await execute_action(
        "bulk_edit", {"operation": "archive", "preview_token": preview["preview_token"]}, db, cfg, bus
    )

    assert db.get_note(nid)["archived"] == 1


@pytest.mark.anyio
async def test_pin(env):
    db, cfg, bus = env
    nid = _note(db, "router", "router")

    preview = await execute_action("bulk_edit", {"query": "router", "operation": "pin"}, db, cfg, bus)
    await execute_action(
        "bulk_edit", {"operation": "pin", "preview_token": preview["preview_token"]}, db, cfg, bus
    )

    assert db.get_note(nid)["pinned"] == 1


@pytest.mark.anyio
async def test_an_unknown_operation_is_refused(env):
    db, cfg, bus = env
    _note(db, "router", "router")

    res = await execute_action("bulk_edit", {"query": "router", "operation": "rm -rf"}, db, cfg, bus)

    assert res["ok"] is False


@pytest.mark.anyio
async def test_a_tag_operation_without_a_value_is_refused(env):
    db, cfg, bus = env
    _note(db, "router", "router")

    res = await execute_action("bulk_edit", {"query": "router", "operation": "add_tag"}, db, cfg, bus)

    assert res["ok"] is False


# ---- tags obey the #257 vocabulary ----------------------------------------


@pytest.mark.anyio
async def test_a_tag_snaps_to_the_existing_tag_it_extends(env):
    """Same containment rule as enrichment output, so both agree.

    'homelab-router' starts with the 'homelab' already in use, so it snaps
    onto it — the direction `closest_tag` actually implements.
    """
    db, cfg, bus = env
    nid = _note(db, "router", "router")
    cfg.llm.preferred_tags = "homelab"

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab-router"},
        db, cfg, bus,
    )
    await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    assert _tags(db, nid) == ["homelab"]


@pytest.mark.anyio
async def test_a_tag_no_vocabulary_claims_is_left_alone(env):
    """Over-merging is worse than a messy tag, so nothing snaps when unsure."""
    db, cfg, bus = env
    nid = _note(db, "router", "router")

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "sourdough"},
        db, cfg, bus,
    )
    await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    assert _tags(db, nid) == ["sourdough"]


# ---- undo and live updates ------------------------------------------------


@pytest.mark.anyio
async def test_undo_puts_the_tags_back(env):
    db, cfg, bus = env
    nid = _note(db, "router one", "router", tags=["network"])

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    res = await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    undone = await undo_action(res["undo"], db, cfg, bus)
    assert undone["ok"] is True
    assert _tags(db, nid) == ["network"]


@pytest.mark.anyio
async def test_undo_puts_the_archive_flag_back(env):
    db, cfg, bus = env
    nid = _note(db, "router", "router")

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "archive"}, db, cfg, bus
    )
    res = await execute_action(
        "bulk_edit", {"operation": "archive", "preview_token": preview["preview_token"]}, db, cfg, bus
    )

    await undo_action(res["undo"], db, cfg, bus)
    assert db.get_note(nid)["archived"] == 0


@pytest.mark.anyio
async def test_every_changed_note_announces_itself(env):
    """A view that does not hear about it stays stale until navigation."""
    db, cfg, bus = env
    _note(db, "router one", "router")
    _note(db, "router two", "router")

    events: list[dict] = []
    bus.subscribe("note.updated", lambda data: events.append(data))

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )

    assert len(events) == 2

# ---- the confirm turn the assistant actually takes ------------------------
#
# The UI does not echo the tool call. It re-sends the user's original prompt
# with confirm=true and lets the model call the tool again, so these two tests
# describe the real flow rather than a convenient one.


@pytest.mark.anyio
async def test_confirming_without_a_preview_token_applies_the_previewed_set(env):
    db, cfg, bus = env
    nid = _note(db, "router one", "router")

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    # Exactly what the UI sends: the same params, plus confirm, no token.
    res = await execute_action(
        "bulk_edit",
        {"query": "router", "operation": "add_tag", "value": "homelab", "confirm": True},
        db,
        cfg,
        bus,
    )

    assert preview["preview_token"]
    assert res["ok"] is True
    assert _tags(db, nid) == ["homelab"]


@pytest.mark.anyio
async def test_a_confirm_with_no_preview_does_not_edit_anything(env):
    """A confirm on an edit the user never saw must preview, not apply."""
    db, cfg, bus = env
    nid = _note(db, "router one", "router")

    res = await execute_action(
        "bulk_edit",
        {"query": "router", "operation": "add_tag", "value": "homelab", "confirm": True},
        db,
        cfg,
        bus,
    )

    assert res["ok"] is True
    assert res["preview"] is True
    assert _tags(db, nid) == []


@pytest.mark.anyio
async def test_a_confirm_for_a_different_edit_previews_instead_of_applying(env):
    """The model coming back with other parameters must not reuse a preview."""
    db, cfg, bus = env
    nid = _note(db, "router one", "router", tags=["network"])

    await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    res = await execute_action(
        "bulk_edit",
        {"query": "router", "operation": "add_tag", "value": "work", "confirm": True},
        db,
        cfg,
        bus,
    )

    assert res["preview"] is True
    assert _tags(db, nid) == ["network"]


@pytest.mark.anyio
async def test_the_confirm_turn_is_undoable(env):
    db, cfg, bus = env
    nid = _note(db, "router one", "router", tags=["network"])

    await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    res = await execute_action(
        "bulk_edit",
        {"query": "router", "operation": "add_tag", "value": "homelab", "confirm": True},
        db,
        cfg,
        bus,
    )

    assert res.get("undo")
    assert (await undo_action(res["undo"], db, cfg, bus))["ok"] is True
    assert _tags(db, nid) == ["network"]


# ---- what the user is shown ------------------------------------------------


@pytest.mark.anyio
async def test_the_preview_message_names_the_notes_not_just_the_count(env):
    db, cfg, bus = env
    _note(db, "router alpha", "router")
    _note(db, "router beta", "router")

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    msg = _format_action_result("bulk_edit", {}, preview)

    assert "router alpha" in msg and "router beta" in msg
    assert "homelab" in msg
    # It must be obvious that nothing has happened yet.
    assert "Not changed anything yet" in msg


@pytest.mark.anyio
async def test_the_applied_message_says_how_many_actually_changed(env):
    db, cfg, bus = env
    _note(db, "router one", "router")
    _note(db, "router two", "router", tags=["homelab"])

    preview = await execute_action(
        "bulk_edit", {"query": "router", "operation": "add_tag", "value": "homelab"}, db, cfg, bus
    )
    res = await execute_action(
        "bulk_edit",
        {"operation": "add_tag", "preview_token": preview["preview_token"]},
        db,
        cfg,
        bus,
    )
    msg = _format_action_result("bulk_edit", {}, res)

    assert "1 of 2" in msg
