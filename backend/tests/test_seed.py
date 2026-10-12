"""#189 seed data for demo mode, E2E and visual regression.

Determinism is the whole requirement. #190 and #394 select notes by id and
compare screenshots against a fixed date, so the same seed must produce the same
ids, timestamps and rows on every run and on every machine. Anything derived
from `now()`, `new_id()` or `random` without a pinned seed would make those
tests flaky for reasons that have nothing to do with the thing under test.

That is why `seed_demo` takes `today` as a parameter instead of reading the
clock: the caller decides what "now" means, and a test pins it.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.seed import DEMO_TODAY, seed_demo

TODAY = DEMO_TODAY


@pytest.fixture()
def db(tmp_path) -> Database:
    # No close(): `Database` is thread-local and garbage collected, which is
    # what every other DB test in this suite relies on.
    d = Database(str(tmp_path / "seed.db"))
    d.migrate()
    return d


def _notes(d: Database) -> list[dict]:
    return d.execute("SELECT * FROM notes ORDER BY created_at").fetchall()


def _tasks(d: Database) -> list[dict]:
    return d.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()


def _activity(d: Database) -> list[dict]:
    return d.execute("SELECT * FROM activity ORDER BY first_seen").fetchall()


# ---- it seeds something ---------------------------------------------------


def test_it_seeds_notes_tasks_and_activity(db: Database) -> None:
    counts = seed_demo(db)
    assert counts["notes"] == len(_notes(db)) > 5
    assert counts["activity"] == len(_activity(db)) > 20
    assert counts["tasks"] == 12
    # `insert_note` promotes every action item to a task row, so the table
    # holds more than the twelve added by hand. The returned count is what
    # seed_demo itself wrote, which is the useful number for a caller
    # reporting "seeded N". Promotion is the contract; the exact total is not,
    # because it moves whenever the corpus does.
    assert len(_tasks(db)) > counts["tasks"]


def test_every_seeded_note_has_enough_to_render(db: Database) -> None:
    """Demo data with no title or tags renders as blank rows. Useless."""
    seed_demo(db)
    for note in _notes(db):
        assert note["title"], f"note {note['id']} has no title"
        assert note["raw_text"], f"note {note['id']} has no body"
        assert note["type"] in ("text", "voice", "youtube", "file")


def test_seeded_notes_are_not_marked_generated(db: Database) -> None:
    """`generated` marks vault-imported digests.

    A demo that filled the inbox with what look like AI-written daily digests
    would misrepresent the very thing it is demonstrating, and #259/#260
    urgency and clarity keys off this column.
    """
    seed_demo(db)
    assert all(n["generated"] == 0 for n in _notes(db))


def test_activity_spans_every_day_of_the_window(db: Database) -> None:
    """A heatmap with gaps is not a demo of a heatmap."""
    seed_demo(db, days=14, today=TODAY)
    days = {a["day"] for a in _activity(db)}
    assert len(days) == 14
    assert min(days) == (TODAY - timedelta(days=13)).isoformat()
    assert max(days) == TODAY.isoformat()


def test_timestamps_are_all_in_the_past(db: Database) -> None:
    """Nothing in the future: a chart axis that runs past today looks broken."""
    seed_demo(db)
    today_iso = TODAY.isoformat()
    assert all(a["first_seen"][:10] <= today_iso for a in _activity(db))
    assert all(n["created_at"][:10] <= today_iso for n in _notes(db))


def test_tasks_have_priorities_and_due_dates(db: Database) -> None:
    seed_demo(db)
    tasks = _tasks(db)
    assert {t["priority"] for t in tasks} == {"P1", "P2", "P3"}
    assert any(t["done"] == 1 for t in tasks), "no completed task to show"
    assert any(t["done"] == 0 for t in tasks), "nothing left to do"
    assert any(t["completed_at"] for t in tasks)
    assert all(t["completed_at"] is None for t in tasks if not t["done"])


# ---- determinism, which is the actual requirement -------------------------


def test_two_fresh_databases_get_byte_identical_rows(tmp_path) -> None:
    a, b = Database(str(tmp_path / "a.db")), Database(str(tmp_path / "b.db"))
    for d in (a, b):
        d.migrate()
    seed_demo(a)
    seed_demo(b)
    for table in ("notes", "tasks", "activity"):
        rows_a = a.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        rows_b = b.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        assert [dict(r) for r in rows_a] == [dict(r) for r in rows_b], table


def test_ids_are_pinned_not_generated(db: Database) -> None:
    """E2E selects by id, so ids must not come from `new_id()`.

    Tasks get two passes: the twelve inserted directly, and the ones promoted
    out of a note's action items by `insert_note`. Both need pinned ids or the
    two-seeded-databases test fails.
    """
    seed_demo(db)
    assert all(n["id"].startswith("demo-note-") for n in _notes(db))
    assert all(t["id"].startswith(("demo-task-", "demo-ai-")) for t in _tasks(db))


def test_reseeding_is_idempotent(db: Database) -> None:
    """Running it twice must not double the demo data."""
    seed_demo(db)
    before = (len(_notes(db)), len(_tasks(db)), len(_activity(db)))
    counts = seed_demo(db)
    assert (len(_notes(db)), len(_tasks(db)), len(_activity(db))) == before
    assert counts == {"notes": 0, "tasks": 0, "activity": 0}


# ---- isolation, the thing AGENTS.md is loud about -------------------------


def test_importing_the_seeder_does_not_build_the_app(tmp_path) -> None:
    """`fleeting.main` builds its app at module level, so importing it migrates.

    Run in a subprocess because that is the only way to observe a genuinely
    clean import. An earlier version of this test deleted every `fleeting`
    module from `sys.modules` in-process, which broke each module the rest of
    the suite had already imported and made 55 unrelated tests fail — a test
    that corrupts the run to prove a point about isolation is not worth having.
    """
    import subprocess
    import sys

    env = {
        "PATH": os.environ.get("PATH", ""),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "VIRTUAL_ENV": str(Path(sys.prefix)),
    }
    Path(env["XDG_DATA_HOME"], "fleeting").mkdir(parents=True, exist_ok=True)
    Path(env["XDG_CONFIG_HOME"], "fleeting").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, fleeting.seed; "
            "assert 'fleeting.main' not in sys.modules, 'seeder imported the app'",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # Nothing migrated either: importing must not create a database.
    assert not (tmp_path / "data" / "fleeting" / "fleeting.db").exists()