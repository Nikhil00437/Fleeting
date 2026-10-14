"""#122: the vault sync dry run.

The mirror writes on every note change. That is right most of the time and
alarming the rest — a folder-mapping rule looks, until you look, exactly like a
sync about to scatter a few thousand files. The first sign of a mistake is a
folder full of misplaced notes, so "check first" has to be an operation.

**The two outcomes that matter are only distinguishable with the sync log.**
`rewrite` means "this file predates us or came from elsewhere"; `conflict` means
"this is our file and a person has edited it since". Without a recorded hash of
what we last wrote, both look identical — and the second is the one where
applying the plan destroys something somebody typed. The test that pins this
writes a file by hand and changes nothing else.

**The plan is computed, never remembered.** A dry run that records conclusions and
applies them later is stale by the time it acts, and the window between "looked
fine" and "was fine" is the window that matters.
"""

from __future__ import annotations

import pytest

from fleeting.services import markdown
from fleeting.services.vault_dryrun import ACTIONS, classify, plan, plan_all


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "v.db"))
    database.migrate()
    return database


@pytest.fixture()
def cfg(tmp_path):
    from fleeting.config import PathsConfig

    return PathsConfig(vault_dir=str(tmp_path / "vault"))


def note(note_id: str = "n1", title: str = "A note", **extra) -> dict:
    return {
        "id": note_id,
        "title": title,
        "type": "text",
        "created_at": "2026-01-02T09:00:00+00:00",
        "tags": [],
        "action_items": [],
        "source": {},
        **extra,
    }


def sync(cfg, db, note_: dict):
    return markdown.sync_note(cfg, note_, db)


# ---- the five outcomes -----------------------------------------------------


def test_a_note_with_no_file_would_be_created(cfg, db) -> None:
    assert classify(cfg, note(), db)["action"] == "create"


def test_an_unchanged_note_is_left_alone(cfg, db) -> None:
    """Most notes, most of the time. Rewriting them is churn, and a vault full
    of touched files breaks every incremental tool the user owns."""
    n = note()
    sync(cfg, db, n)
    assert classify(cfg, n, db)["action"] == "unchanged"


def test_a_changed_note_would_be_rewritten(cfg, db) -> None:
    """Ours, edited in the app, not yet synced."""
    sync(cfg, db, note())
    assert classify(cfg, note(title="Edited in the app"), db)["action"] == "rewrite"


def test_a_file_we_never_wrote_is_a_rewrite_not_a_conflict(cfg, db) -> None:
    """It predates us or came from elsewhere. Not somebody editing our file."""
    path = markdown.vault_path_for(cfg, note())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("a file someone put here themselves\n", encoding="utf-8")
    assert classify(cfg, note(), db)["action"] == "rewrite"


def test_an_edited_file_is_a_conflict(cfg, db) -> None:
    """The distinction the whole feature rests on: ours, and changed since."""
    n = note()
    sync(cfg, db, n)
    path = markdown.vault_path_for(cfg, n)
    path.write_text(path.read_text(encoding="utf-8") + "\ntyped in Obsidian\n", encoding="utf-8")
    assert classify(cfg, n, db)["action"] == "conflict"


def test_a_sensitive_note_is_skipped(cfg, db) -> None:
    """#26: it never becomes plain text on disk, so there is nothing to plan."""
    assert classify(cfg, note(sensitive=1), db)["action"] == "skip"


def test_every_outcome_is_one_of_the_five(cfg, db) -> None:
    """A sixth action appearing later must not be silently reported as a
    rewrite."""
    sync(cfg, db, note())
    assert classify(cfg, note(), db)["action"] in ACTIONS


def test_the_reason_is_always_given(cfg, db) -> None:
    """"3 conflicts" is a decision; "here are twelve hundred rows" is not."""
    assert classify(cfg, note(), db)["why"]


# ---- the plan --------------------------------------------------------------


def test_the_plan_counts_each_action(cfg, db) -> None:
    n = note()
    sync(cfg, db, n)
    path = markdown.vault_path_for(cfg, n)
    path.write_text("hand edited\n", encoding="utf-8")
    result = plan(cfg, [note("a", "fresh"), n], db)
    assert result["counts"]["create"] == 1
    assert result["counts"]["conflict"] == 1


def test_the_plan_reports_the_total(cfg, db) -> None:
    assert plan(cfg, [note("a"), note("b")], db)["total"] == 2


def test_the_plan_samples_each_action(cfg, db) -> None:
    """Recognisability: a count with no names gives you nothing to search for."""
    result = plan(cfg, [note("a"), note("b")], db)
    assert len(result["samples"]["create"]) == 2
    assert result["samples"]["create"][0]["note_id"] == "a"


def test_the_samples_are_bounded(cfg, db) -> None:
    """A plan listing every note is a wall of text."""
    from fleeting.services.vault_dryrun import PLAN_SAMPLE

    result = plan(cfg, [note(f"n{i}") for i in range(PLAN_SAMPLE * 2)], db)
    assert len(result["samples"]["create"]) == PLAN_SAMPLE
    assert result["total"] == PLAN_SAMPLE * 2


def test_a_plan_with_conflicts_is_not_safe_to_apply(cfg, db) -> None:
    """The one number that decides whether this can be applied unattended."""
    n = note()
    sync(cfg, db, n)
    path = markdown.vault_path_for(cfg, n)
    path.write_text("hand edited\n", encoding="utf-8")
    assert plan(cfg, [n], db)["safe_to_apply"] is False


def test_a_clean_plan_is_safe_to_apply(cfg, db) -> None:
    assert plan(cfg, [note("a")], db)["safe_to_apply"] is True


def test_an_empty_plan_is_safe_to_apply(cfg, db) -> None:
    """An empty room is not a risk."""
    assert plan(cfg, [], db)["safe_to_apply"] is True


# ---- planning against the database -----------------------------------------


def test_planning_the_whole_database(cfg, db) -> None:
    db.insert_note(note("a", "one"))
    db.insert_note(note("b", "two"))
    db.commit()
    result = plan_all(cfg, db)
    assert result["total"] == 2
    assert result["scanned"] == 2
    assert result["truncated"] is False


def test_planning_admits_when_it_stopped_early(cfg, db) -> None:
    """A plan that silently covers the first N and says 'total: N' is worse than
    one that admits it."""
    for i in range(5):
        db.insert_note(note(f"n{i}"))
    db.commit()
    result = plan_all(cfg, db, limit=3)
    assert result["scanned"] == 3
    assert result["truncated"] is True


def test_planning_writes_nothing(cfg, db) -> None:
    """The whole point. A dry run that creates the files it was asked to predict
    is not a dry run."""
    n = note()
    db.insert_note(n)
    db.commit()
    plan_all(cfg, db)
    assert not markdown.vault_path_for(cfg, n).exists()


def test_planning_does_not_record_a_sync(cfg, db) -> None:
    """Otherwise the log claims we wrote files we only thought about, and every
    later conflict check is against a fiction."""
    from fleeting.services import vault_log

    db.insert_note(note())
    db.commit()
    plan_all(cfg, db)
    assert vault_log.last_write(db, "n1") is None


# ---- the endpoints ---------------------------------------------------------


def test_the_dry_run_endpoint(client) -> None:
    r = client.post("/api/vault/dry-run")
    assert r.status_code == 200, r.text
    assert {"total", "counts", "samples", "safe_to_apply"} <= set(r.json())


def test_the_dry_run_endpoint_writes_nothing(client) -> None:
    client.post("/api/capture/text", json={"text": "should not reach the vault yet"})
    client.post("/api/vault/dry-run")
    from pathlib import Path

    from fleeting.main import _db_path

    db_dir = Path(_db_path()).parent
    vault = next((p for p in db_dir.glob("**/fleeting-n*.md")), None)
    assert vault is None, f"the dry run created {vault}"


def test_the_endpoint_reports_a_synced_note_as_unchanged(client) -> None:
    """The `client` fixture syncs, so a freshly captured note is already on
    disk. Reporting it as `create` would be the dry run lying about the folder."""
    from conftest import wait_done

    note_id = client.post("/api/capture/text", json={"text": "a brand new note"}).json()["id"]
    wait_done(client, note_id)
    body = client.post("/api/vault/dry-run").json()
    assert body["counts"]["create"] == 0
    assert body["counts"]["unchanged"] >= 1


def test_an_unsynced_note_is_reported_as_a_create(client) -> None:
    from conftest import wait_done

    client.put("/api/settings", json={"vault_sync": False})
    note_id = client.post("/api/capture/text", json={"text": "never mirrored"}).json()["id"]
    wait_done(client, note_id)
    body = client.post("/api/vault/dry-run").json()
    assert body["counts"]["create"] >= 1


def test_the_endpoint_reports_conflicts(client) -> None:
    """End to end through the API: a note synced, then edited in the vault."""
    from conftest import wait_done

    from fleeting.services.markdown import vault_path_for

    note_id = client.post("/api/capture/text", json={"text": "will be edited by hand"}).json()["id"]
    wait_done(client, note_id)
    db = client.app.state.st.db
    path = vault_path_for(client.app.state.st.cfg.paths, db.get_note(note_id))
    path.write_text(path.read_text(encoding="utf-8") + "\ntyped in Obsidian\n", encoding="utf-8")

    body = client.post("/api/vault/dry-run").json()
    assert body["counts"]["conflict"] >= 1
    assert body["safe_to_apply"] is False