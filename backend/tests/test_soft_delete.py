"""#456: soft-delete everywhere, with a recoverable window.

The item is "everywhere", and that word is the whole difficulty. Four paths could
destroy a note and they had drifted apart:

| path | before | now |
|---|---|---|
| `DELETE /api/notes/{id}` | trash | trash (unchanged) |
| the assistant's `delete_note` tool | **hard delete** | trash |
| `POST /api/notes/{id}/purge` | **hard delete, any note, no confirm** | trashed notes only, confirmed |
| `POST /api/forget` | hard delete | hard delete — it is the panic button |

The one hard-delete that stays is the one whose entire purpose is to be
irreversible. The tests below therefore pin an invariant rather than a list of
endpoints: **no path may destroy a note that is not already in the trash**, with
`forget` named as the single exception.

The assistant tool is the case that mattered most. It is a *tool call*: the
caller can be a model that decided a note was not worth keeping, and a model
that is wrong about that is precisely the mistake you cannot undo.
"""

from __future__ import annotations



def make_note(client, text: str = "something worth keeping") -> dict:
    note = client.post("/api/capture/text", json={"text": text}).json()
    from conftest import wait_done

    return wait_done(client, note["id"])


def trash(client, note_id: str) -> None:
    assert client.delete(f"/api/notes/{note_id}").status_code == 200


# ---- the assistant tool ----------------------------------------------------


def test_the_assistants_delete_leaves_the_note_recoverable(client) -> None:
    from fleeting.services.actions import delete_note
    from fleeting.events import EventBus

    note = make_note(client)
    st = client.app.state.st
    result = delete_note({"note_id": note["id"]}, st.db, st.cfg, EventBus())
    assert result["ok"] is True
    assert result["recoverable"] is True


def test_the_assistants_delete_does_not_destroy_the_row(client) -> None:
    """A model that is wrong about which note to delete is the mistake you
    cannot undo."""
    from fleeting.services.actions import delete_note
    from fleeting.events import EventBus

    note = make_note(client)
    st = client.app.state.st
    delete_note({"note_id": note["id"]}, st.db, st.cfg, EventBus())
    assert st.db.get_note(note["id"]) is not None


def test_the_assistants_delete_puts_it_in_the_trash(client) -> None:
    from fleeting.services.actions import delete_note
    from fleeting.events import EventBus

    note = make_note(client)
    st = client.app.state.st
    delete_note({"note_id": note["id"]}, st.db, st.cfg, EventBus())
    assert st.db.get_note(note["id"])["trashed_at"] is not None


def test_the_assistants_delete_is_reversible(client) -> None:
    from fleeting.services.actions import delete_note
    from fleeting.events import EventBus

    note = make_note(client, "recover me")
    st = client.app.state.st
    delete_note({"note_id": note["id"]}, st.db, st.cfg, EventBus())
    assert client.post(f"/api/notes/{note['id']}/restore").status_code == 200
    assert st.db.get_note(note["id"])["trashed_at"] is None


def test_the_assistants_delete_still_reports_a_missing_note(client) -> None:
    from fleeting.services.actions import delete_note
    from fleeting.events import EventBus

    st = client.app.state.st
    assert delete_note({"note_id": "nope"}, st.db, st.cfg, EventBus())["ok"] is False


# ---- purge -----------------------------------------------------------------


def test_purging_a_live_note_is_refused(client) -> None:
    """Purging already-trashed notes deliberately is allowed; purging a live one
    skipped the recoverable window the rest of the app depends on."""
    note = make_note(client)
    r = client.post(f"/api/notes/{note['id']}/purge", json={"confirm": True})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "not_trashed"
    assert client.app.state.st.db.get_note(note["id"]) is not None


def test_the_refusal_explains_the_order(client) -> None:
    note = make_note(client)
    message = client.post(f"/api/notes/{note['id']}/purge", json={"confirm": True}).json()["detail"]["message"]
    assert "trash" in message


def test_purging_a_trashed_note_still_works(client) -> None:
    note = make_note(client)
    trash(client, note["id"])
    r = client.post(f"/api/notes/{note['id']}/purge", json={"confirm": True})
    assert r.status_code == 200
    assert client.app.state.st.db.get_note(note["id"]) is None


def test_purging_without_confirming_is_refused(client) -> None:
    """A mistyped URL was enough to destroy a note before."""
    note = make_note(client)
    trash(client, note["id"])
    r = client.post(f"/api/notes/{note['id']}/purge", json={})
    assert r.status_code == 409
    assert client.app.state.st.db.get_note(note["id"]) is not None


# ---- the invariant ---------------------------------------------------------


# Paths relative to the `fleeting` package.
HARD_DELETE_CALLERS = {
    # The panic button. Irreversible *is* the feature, and it has its own
    # preview, confirmation and audit entry.
    "services/forget.py",
    # The purge endpoint — the one place a permanent delete is reachable, and
    # only for an already-trashed note with an explicit confirm. Both halves of
    # that are asserted behaviourally above, not just here.
    "routers/notes.py",
    # `undo`. Reverting a creation means removing what that creation added — the
    # note was made moments ago by the very action being undone, so there is
    # nothing a user wrote that a trash window would protect. The assistant's
    # *tool* in the same file trashes, and that is asserted above.
    "services/actions.py",
}


def test_no_module_hard_deletes_outside_the_panic_button() -> None:
    """One invariant, covering every path — including any added later.

    A list of endpoints is a list that goes stale the next time someone adds one,
    and the new one is precisely the one nobody re-reviews.
    """
    package = __import__("pathlib").Path(__file__).resolve().parents[1] / "fleeting"
    offenders = [
        str(path.relative_to(package))
        for path in sorted(package.rglob("*.py"))
        if str(path.relative_to(package)) not in HARD_DELETE_CALLERS
        # The db layer defines the purge; only its *callers* are in scope.
        and path.name != "db.py"
        # `db.delete_note(...)` specifically: that is the hard delete. The
        # router and the tool now share the name `delete_note` for the soft one.
        and "db.delete_note(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"these hard-delete outside the panic button: {offenders}"


def test_every_endpoint_that_deletes_goes_through_the_trash(client) -> None:
    """Behavioural, not structural: a note deleted "the normal way" is still
    there."""
    note = make_note(client)
    assert client.delete(f"/api/notes/{note['id']}").status_code == 200
    assert client.app.state.st.db.get_note(note["id"]) is not None


def test_the_retention_window_is_still_what_makes_it_permanent() -> None:
    """Soft delete everywhere does not mean nothing is ever deleted."""
    from fleeting.config import Config

    assert Config().notes.trash_retention_days > 0


def test_the_purge_hook_still_hard_deletes(client) -> None:
    """Otherwise "soft-delete everywhere" could be satisfied by deleting nothing."""
    note = make_note(client)
    trash(client, note["id"])
    assert client.post(f"/api/notes/{note['id']}/purge", json={"confirm": True}).status_code == 200
    assert client.app.state.st.db.get_note(note["id"]) is None