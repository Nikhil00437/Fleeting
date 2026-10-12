"""Regression: `migrate()` must not re-create tasks it already made.

Found while writing #189 seed data. `insert_note` promotes a note's
action_items into `tasks` under the *bare* item id, and `_sync_note_action_items`
writes that id back into the note's JSON. `_migrate_action_items` then ran on
every boot and rebuilt the id as `<note_id>_<item_id>` — a different string —
so every process start inserted a second copy of every task.

Not theoretical: a real database had `84649eb6942e` and
`037c9b9ab47e_84649eb6942e`, the same text under the same note.

Both shapes are covered because they fail differently:
  - an action item carrying an id (what today's captures produce), and
  - one without (legacy JSON from before the tasks table), where nothing ever
    wrote an id back, so the old code minted a fresh one on every single boot.
"""

from __future__ import annotations

import pytest

from fleeting.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    d = Database(str(tmp_path / "dup.db"))
    d.migrate()
    return d


def _tasks(d: Database) -> list[dict]:
    return [dict(r) for r in d.execute("SELECT * FROM tasks ORDER BY created_at")]


def _note(nid: str, items: list[dict]) -> dict:
    return {
        "id": nid,
        "type": "text",
        "title": f"note {nid}",
        "raw_text": "something to act on",
        "tags": [],
        "action_items": items,
        "created_at": "2026-10-11T09:00:00+00:00",
    }


def test_migrate_twice_does_not_duplicate_a_task_with_an_id(db: Database) -> None:
    db.insert_note(_note("n1", [{"id": "ai1", "text": "call the vet", "priority": "P2"}]))
    before = _tasks(db)
    assert len(before) == 1

    db.migrate()
    db.migrate()

    after = _tasks(db)
    assert len(after) == 1, f"duplicated on boot: {[t['id'] for t in after]}"
    assert after == before


def test_migrate_twice_does_not_duplicate_a_task_without_an_id(db: Database) -> None:
    """Legacy JSON: no id ever, so the old code minted one on every boot."""
    db.execute(
        "INSERT INTO notes (id, type, title, raw_text, tags, action_items,"
        " created_at, updated_at) VALUES"
        " ('n1', 'text', 'old note', 'body', '[]',"
        ' \'[{"text": "buy stamps", "priority": "P3"}]\','
        " '2024-01-01T09:00:00+00:00', '2024-01-01T09:00:00+00:00')"
    )
    db.commit()
    before = _tasks(db)
    assert before == [], "nothing promoted yet, so there is nothing to duplicate"

    db.migrate()  # first boot makes the task
    assert len(_tasks(db)) == 1
    first = _tasks(db)

    db.migrate()
    db.migrate()

    after = _tasks(db)
    assert len(after) == 1, f"duplicated on boot: {[t['id'] for t in after]}"
    assert after == first


def test_migrate_still_backfills_a_note_that_never_had_tasks(db: Database) -> None:
    """The fix must not turn the migration off.

    This is its original purpose: a note captured before the tasks table
    existed has action_items in JSON and no rows to match.
    """
    db.execute(
        "INSERT INTO notes (id, type, title, raw_text, tags, action_items,"
        " created_at, updated_at) VALUES"
        " ('legacy', 'text', 'old note', 'body', '[]',"
        " '[{\"text\": \"water the plants\"}, {\"text\": \"return the library book\"}]',"
        " '2024-01-01T09:00:00+00:00', '2024-01-01T09:00:00+00:00')"
    )
    db.commit()
    assert _tasks(db) == []

    db.migrate()

    texts = sorted(t["text"] for t in _tasks(db))
    assert texts == ["return the library book", "water the plants"]
    assert all(t["note_id"] == "legacy" for t in _tasks(db))


def test_two_notes_with_the_same_text_both_get_their_task(db: Database) -> None:
    """Deduplicating by text must not merge across notes.

    Matching an idless item to a same-text task is only correct within one
    note; globally it would silently drop a task.
    """
    db.execute(
        "INSERT INTO notes (id, type, title, raw_text, tags, action_items,"
        " created_at, updated_at) VALUES"
        " ('n1', 'text', 'a', 'b', '[]', '[{\"text\": \"buy stamps\"}]',"
        " '2024-01-01T09:00:00+00:00', '2024-01-01T09:00:00+00:00'),"
        " ('n2', 'text', 'c', 'd', '[]', '[{\"text\": \"buy stamps\"}]',"
        " '2024-01-02T09:00:00+00:00', '2024-01-02T09:00:00+00:00')"
    )
    db.commit()

    db.migrate()

    rows = _tasks(db)
    assert len(rows) == 2
    assert {r["note_id"] for r in rows} == {"n1", "n2"}