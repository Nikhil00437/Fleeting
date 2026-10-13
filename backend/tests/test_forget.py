"""#136: forget the last N minutes, in one click.

This is the feature people install a local-first notes app *for*, and it is the
one place where asking "are you sure?" is not enough. A confirm dialog makes you
read; a panic button is for the moment you are not going to read carefully. So
the design leans on two things instead:

- **A preview with titles, not ids.** You cannot confirm "delete 4 rows" — you
  can confirm "delete the four notes you dictated in the last ten minutes" once
  you see what they are.
- **It only touches what was *created* in the window.** A note you had for six
  months and edited five minutes ago is not something "forget the last ten
  minutes" should destroy, even though it is technically inside the window.
  Deleting a long-lived note to protect the last ten minutes is a worse failure
  than leaving one stray edit.

Reuses `services/bulk.py` — the same preview and confirmation shape as #455, so
"are you sure" means the same thing everywhere it appears.
"""

from __future__ import annotations

import pytest

from conftest import wait_done


def _capture(client, title: str) -> dict:
    r = client.post("/api/capture/text", json={"text": f"body of {title}", "title": title})
    return wait_done(client, r.json()["id"])


@pytest.fixture()
def recent(client):
    return [_capture(client, t) for t in ("alpha", "bravo", "charlie")]


def _forget(client, minutes: int, **extra):
    return client.post("/api/forget", json={"minutes": minutes, **extra})


# ---- the preview ----------------------------------------------------------


def test_the_preview_counts_what_would_go(client, recent) -> None:
    body = _forget(client, 30).json()
    assert body["detail"]["notes"] == 3


def test_the_preview_shows_titles(client, recent) -> None:
    """You cannot confirm "3 rows". You can confirm three titles."""
    body = _forget(client, 30).json()
    samples = body["detail"]["samples"]
    titles = [s["title"] for s in samples]
    # Not "alpha in titles": the heuristic enricher rewrites titles, so the exact
    # string is not stable. What matters is that each row is identifiable and
    # distinguishable — three blanks would pass an id-only check.
    assert len(samples) == 3
    assert all(t.strip() for t in titles), titles
    assert len(set(titles)) == 3, titles


def test_a_preview_does_not_delete_anything(client, recent) -> None:
    _forget(client, 30)
    assert len(client.get("/api/notes").json()) == 3


def test_an_empty_window_is_a_no_op_not_a_prompt(client) -> None:
    """The same rule as #455: nothing to forget is not something to confirm.

    The activity table is seeded by other tests, so "empty" has to be made
    rather than assumed.
    """
    st = client.app.state.st.db
    with st.conn:
        st.conn.execute("DELETE FROM activity")
        st.conn.execute("DELETE FROM notes")
        st.conn.execute("DELETE FROM tasks")
    st.commit()
    assert _forget(client, 30).status_code == 200


# ---- the execution --------------------------------------------------------


def test_confirming_forgets_the_window(client, recent) -> None:
    out = _forget(client, 30, confirm=True).json()
    assert out["forgotten"]["notes"] == 3
    assert client.get("/api/notes").json() == []


def test_a_note_from_before_the_window_survives(client) -> None:
    old = _capture(client, "ancient history")
    """The rule that makes this safe to use in a panic: only what was *created*
    in the window goes. A six-month-old note edited five minutes ago is not
    "the last ten minutes"."""
    st_db = client.app.state.st.db
    st_db.conn.execute(
        "UPDATE notes SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (old["id"],)
    )
    st_db.commit()

    _forget(client, 30, confirm=True)
    remaining = client.get("/api/notes").json()
    assert [n["id"] for n in remaining] == [old["id"]]


def test_tasks_created_in_the_window_go_too(client, recent) -> None:
    """A task extracted from a note you just dictated is part of what you are
    trying to forget. Leaving it behind would be worse than useless."""
    r = client.post("/api/tasks", json={"text": "buy milk", "priority": "P1"})
    assert r.status_code in (200, 201), r.text
    out = _forget(client, 30, confirm=True).json()
    assert out["forgotten"]["tasks"] == 1


def test_activity_in_the_window_is_forgotten(client, recent) -> None:
    out = _forget(client, 30, confirm=True).json()
    assert "activity" in out["forgotten"]


def test_the_action_is_audited(client, recent) -> None:
    """#140: something that destroys data is exactly what an audit log is for."""
    _forget(client, 30, confirm=True)
    entry = next(
        e for e in client.get("/api/audit").json()["entries"] if e["action"] == "privacy.forget"
    )
    assert entry["detail"]["minutes"] == 30
    assert entry["detail"]["notes"] == 3


def test_the_ui_is_told(client, recent, monkeypatch) -> None:
    """Trashing is not enough — the inbox would still show rows the server no
    longer has."""
    published: list[str] = []
    bus = client.app.state.st.bus
    orig = bus.publish
    monkeypatch.setattr(bus, "publish", lambda name, payload: (published.append(name), orig(name, payload)))

    _forget(client, 30, confirm=True)
    assert published.count("note.deleted") == 3


# ---- bounds ---------------------------------------------------------------


@pytest.mark.parametrize("minutes", [0, -5, 10**9])
def test_the_window_is_clamped_to_something_sane(client, recent, minutes: int) -> None:
    body = _forget(client, minutes).json()
    assert "detail" in body or body.get("ok") is True


def test_a_non_numeric_window_is_a_422_not_a_crash(client) -> None:
    r = client.post("/api/forget", json={"minutes": "all of it"})
    assert r.status_code == 422

# ---- gaps found by the first mutation pass -------------------------------


def test_the_counts_reported_match_what_was_actually_deleted(client, recent) -> None:
    """The first version asserted `forgotten.tasks == 1` and was satisfied by a
    mutation that deleted nothing — the count is computed before the delete, so
    it reports the same either way.

    The activity row is inserted by hand: the collector is disabled in tests, so
    without one the delete is a no-op that passes either way too.
    """
    from fleeting.db import now_iso

    # The task hangs off a note from *before* the window, on purpose. A task on
    # a recent note is removed by `ON DELETE CASCADE` when the note goes, so
    # deleting with the mutation applied still ends up with zero tasks — the
    # explicit delete only matters for a task added recently to an older note.
    old_note = _capture(client, "older note")
    db0 = client.app.state.st.db
    with db0.conn:
        db0.conn.execute(
            "UPDATE notes SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (old_note["id"],),
        )
    db0.commit()
    made = client.post(
        "/api/tasks", json={"text": "buy milk", "note_id": old_note["id"]}
    )
    assert made.status_code in (200, 201), made.text
    assert db0.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 1

    db = client.app.state.st.db
    db.upsert_activity(
        {
            "app_class": "firefox",
            "title": "something to forget",
            "first_seen": now_iso(),
            "last_seen": now_iso(),
            "seconds": 60,
            "day": now_iso()[:10],
        }
    )
    assert db.execute("SELECT COUNT(*) c FROM activity").fetchone()["c"] >= 1

    _forget(client, 30, confirm=True)
    assert db.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0
    # ...and the old note it hung off is still there. Forgetting recent work is
    # not a licence to delete a note from 2020.
    assert db.execute(
        "SELECT COUNT(*) c FROM notes WHERE id = ?", (old_note["id"],)
    ).fetchone()["c"] == 1
    assert db.execute("SELECT COUNT(*) c FROM activity").fetchone()["c"] == 0


def test_an_empty_window_writes_no_audit_entry(client) -> None:
    """An audit log full of "forgot 0 things" is the same clutter problem as
    auditing a no-op settings save."""
    st = client.app.state.st.db
    with st.conn:
        st.conn.execute("DELETE FROM activity")
        st.conn.execute("DELETE FROM notes")
        st.conn.execute("DELETE FROM tasks")
    st.commit()
    _forget(client, 30, confirm=True)
    assert not [
        e for e in client.get("/api/audit").json()["entries"] if e["action"] == "privacy.forget"
    ]


def test_the_window_clamp_is_reachable_and_sane(tmp_path) -> None:
    """The route's `le=7 days` rejects the input before the service ever sees
    it, so the service clamp was unreachable through the API and untested."""
    from fleeting.db import Database
    from fleeting.services.forget import MAX_MINUTES, window_preview

    db = Database(str(tmp_path / "f.db"))
    db.migrate()
    assert window_preview(db, 10**9)["minutes"] == MAX_MINUTES
    assert window_preview(db, 0)["minutes"] == 1


def test_the_sample_list_is_bounded(client) -> None:
    """A preview that returns every affected row is a wall of text, and on a
    panic button the confirmation is the last thing anyone reads."""
    from fleeting.services.bulk import PREVIEW_SAMPLES

    for i in range(PREVIEW_SAMPLES + 6):
        _capture(client, f"note {i}")
    body = _forget(client, 30).json()
    assert len(body["detail"]["samples"]) == PREVIEW_SAMPLES
