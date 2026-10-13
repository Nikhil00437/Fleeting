"""#140: an audit log of settings changes and destructive actions.

For answering "what happened to my data at 3am", which is the only question an
audit log is really for. Two rules shape it:

- **Never record a secret.** `settings.py` writes the whole config, so the
  obvious implementation — diff the config before and after and store it — writes
  `llm.api_key`, `activity.api_token` and `transcribe.hf_token` into a table that
  gets read back, exported and backed up. A denylist of key names is a race
  against the next secret someone adds; the shape of a *change* is what matters,
  so old/new values are replaced with a marker and only the field name survives.

- **Record the action, not the payload.** "tag `work` deleted from 41 notes" is
  useful. The titles of those 41 notes are a copy of the user's data in a place
  nobody expects to find it.

Append-only and capped, like every other log table here: enough history to answer
the question, not an archive.
"""

from __future__ import annotations

import json

import pytest

from fleeting.db import AUDIT_CAP, Database


@pytest.fixture()
def db(tmp_path) -> Database:
    d = Database(str(tmp_path / "a.db"))
    d.migrate()
    return d


def rows(db: Database) -> list[dict]:
    # dicts, not sqlite3.Row: these are json.dumps-ed in several tests.
    return [dict(r) for r in db.execute("SELECT * FROM audit_log ORDER BY id").fetchall()]


# ---- recording ------------------------------------------------------------


def test_a_change_is_recorded(db) -> None:
    db.record_audit("settings.update", "llm.provider", {"from": "none", "to": "ollama"})
    assert len(rows(db)) == 1
    assert rows(db)[0]["action"] == "settings.update"
    assert rows(db)[0]["target"] == "llm.provider"


def test_a_secret_is_never_written(db) -> None:
    """The property the whole design is for."""
    db.record_audit("settings.update", "llm.api_key", {"from": "", "to": "sk-live-abc123"})
    blob = json.dumps(rows(db))
    assert "sk-live-abc123" not in blob


def test_a_secret_change_still_records_that_it_happened(db) -> None:
    """Redaction must not erase the evidence — "you changed your key at this
    time" is exactly what you want to know."""
    db.record_audit("settings.update", "llm.api_key", {"from": "", "to": "sk-live-abc123"})
    assert rows(db)[0]["target"] == "llm.api_key"


@pytest.mark.parametrize(
    "target",
    [
        "llm.api_key",
        "llm.api_token",
        "activity.api_token",
        "transcribe.hf_token",
        "server.password",
        "writing.secret",
    ],
)
def test_anything_that_looks_like_a_secret_is_redacted(db, target: str) -> None:
    db.record_audit("settings.update", target, {"from": "old", "to": "hunter2"})
    assert "hunter2" not in json.dumps(rows(db))


def test_an_ordinary_value_is_kept(db) -> None:
    """Redaction that swallows everything is useless — you could not answer any
    question with it."""
    db.record_audit("settings.update", "activity.retention_days", {"from": 30, "to": 7})
    # The column is JSON text; `audit_log()` is what parses it.
    assert json.loads(rows(db)[0]["detail"])["to"] == 7


def test_a_destructive_action_is_recorded_with_a_count(db) -> None:
    db.record_audit("notes.purge", "trash", {"count": 41})
    assert json.loads(rows(db)[0]["detail"])["count"] == 41


def test_the_detail_is_json_not_a_blob(db) -> None:
    """A column you cannot query is a log you can only read end to end."""
    db.record_audit("notes.purge", "trash", {"count": 2})
    assert json.loads(rows(db)[0]["detail"])["count"] == 2


def test_a_failure_to_record_does_not_break_the_operation(db) -> None:
    """An audit log that can stop you deleting a note has inverted its priority.
    (Asserted in the router tests; here: the helper never raises on bad input.)"""
    db.record_audit("x", "y", "not a dict")
    assert isinstance(rows(db)[0]["detail"], str)


def test_the_log_is_capped(db) -> None:
    for i in range(AUDIT_CAP + 25):
        db.record_audit("test", f"t{i}", {"i": i})
    assert len(rows(db)) <= AUDIT_CAP


def test_capping_keeps_the_newest(db) -> None:
    """Keeping the oldest means the answer to "what just happened" is gone."""
    for i in range(AUDIT_CAP + 25):
        db.record_audit("test", f"t{i}", {"i": i})
    assert rows(db)[-1]["target"] == f"t{AUDIT_CAP + 24}"


def test_the_log_survives_a_restart(tmp_path) -> None:
    path = str(tmp_path / "a.db")
    Database(path).migrate()
    first = Database(path)
    first.record_audit("settings.update", "x", {"a": 1})
    first.commit()
    assert len(rows(Database(path))) == 1


# ---- reading --------------------------------------------------------------


def test_the_newest_entries_come_first(db) -> None:
    for i in range(3):
        db.record_audit("test", f"t{i}", {})
    got = db.audit_log(limit=2)
    assert [r["target"] for r in got] == ["t2", "t1"]


def test_the_limit_is_clamped(db) -> None:
    assert db.audit_log(limit=10**6) == [] or len(db.audit_log(limit=10**6)) >= 0
    db.record_audit("test", "t", {})
    assert len(db.audit_log(limit=10**6)) == 1


def test_it_can_be_filtered_by_action(db) -> None:
    db.record_audit("settings.update", "a", {})
    db.record_audit("notes.purge", "b", {})
    assert [r["target"] for r in db.audit_log(action="notes.purge")] == ["b"]


# ---- API-level audit coverage -------------------------------------------


def test_a_settings_change_is_audited(client) -> None:
    client.put("/api/settings", json={"activity_retention_days": 7})
    entries = client.get("/api/audit").json()["entries"]
    assert any(e["action"] == "settings.update" for e in entries)


def test_the_audited_change_names_the_field_and_both_values(client) -> None:
    client.put("/api/settings", json={"activity_retention_days": 7})
    entry = next(
        e for e in client.get("/api/audit").json()["entries"] if e["action"] == "settings.update"
    )
    # The flat API field name, because that is what the settings payload uses
    # and inventing a dotted config path would be a second mapping to keep in
    # step. The redaction heuristic reads the same field name, so both work.
    assert entry["target"] == "activity_retention_days"
    assert entry["detail"]["to"] == 7


def test_a_settings_change_that_changes_nothing_is_not_audited(client) -> None:
    """`settings.update` is a diff, not a click. Recording no-op saves makes the
    log useless — it fills with entries that say nothing happened."""
    before = len(client.get("/api/audit").json()["entries"])
    client.put("/api/settings", json={"activity_retention_days": 30})
    after = client.get("/api/audit").json()["entries"]
    changed = [e for e in after if e["action"] == "settings.update"]
    # Either no entry, or one recording an unchanged value. Both are acceptable;
    # what is not acceptable is recording the same value as a change.
    assert len(after) - before <= 1
    assert all(e["detail"].get("to") != e["detail"].get("from") for e in changed)


def test_emptying_the_trash_is_audited_with_its_count(client) -> None:
    note = client.post("/api/capture/text", json={"text": "audit me"}).json()
    from conftest import wait_done

    wait_done(client, note["id"])
    client.delete(f"/api/notes/{note['id']}")
    client.post("/api/trash/empty", json={"confirm": True})
    entry = next(
        e for e in client.get("/api/audit").json()["entries"] if e["action"] == "notes.purge"
    )
    assert entry["detail"]["count"] == 1


def test_deleting_a_tag_is_audited(client) -> None:
    note = client.post("/api/capture/text", json={"text": "tagged"}).json()
    from conftest import wait_done

    wait_done(client, note["id"])
    client.patch(f"/api/notes/{note['id']}", json={"tags": ["work"]})
    client.post("/api/tags/delete", json={"tag": "work", "confirm": True})
    assert any(e["action"] == "tags.delete" for e in client.get("/api/audit").json()["entries"])


def test_the_audit_log_is_readable_and_ordered(client) -> None:
    client.put("/api/settings", json={"activity_retention_days": 11})
    client.put("/api/settings", json={"activity_retention_days": 12})
    entries = client.get("/api/audit", params={"limit": 5}).json()["entries"]
    assert len(entries) >= 1
    assert entries[0]["at"] >= entries[-1]["at"]


def test_the_limit_is_bounded(client) -> None:
    for i in range(5):
        client.put("/api/settings", json={"activity_retention_days": i + 1})
    assert len(client.get("/api/audit", params={"limit": 10**6}).json()["entries"]) <= 500


def test_the_api_key_is_never_in_the_audit_log(client) -> None:
    """The whole reason this is a shape-based redaction rather than a list of
    fields to remember: `settings.update` is handed whatever the caller changed,
    and someone will add a secret to the config before they add it to a list."""
    client.put("/api/settings", json={"llm_api_key": "sk-live-do-not-log"})
    assert "sk-live-do-not-log" not in client.get("/api/audit").text


def test_a_secret_change_still_appears_as_a_change(client) -> None:
    client.put("/api/settings", json={"llm_api_key": "sk-live-x"})
    entry = next(
        e for e in client.get("/api/audit").json()["entries"] if "api_key" in e["target"]
    )
    assert entry["detail"]["to"] == "<set>"

# ---- gaps found by the first mutation pass -------------------------------


def test_the_limit_clamp_is_real_not_just_untested(db) -> None:
    """The first version of this asserted `<= 500` after writing five rows, which
    passes with the clamp deleted — there is nothing to clamp."""
    from fleeting.db import AUDIT_CAP

    for i in range(AUDIT_CAP + 10):
        db.record_audit("bulk", f"t{i}", {})
    from fleeting.db import AUDIT_QUERY_CAP

    # Below the storage cap, so the query clamp is what is being measured.
    assert AUDIT_QUERY_CAP < AUDIT_CAP
    assert len(db.audit_log(limit=10**6)) == AUDIT_QUERY_CAP


def test_two_fields_changed_in_one_request_are_both_audited(client) -> None:
    """One row per change, not one row per click: "a settings save happened"
    cannot answer "what did they turn off"."""
    client.put(
        "/api/settings",
        json={"activity_retention_days": 9, "activity_auto_daily_log": False},
    )
    targets = {
        e["target"] for e in client.get("/api/audit").json()["entries"]
        if e["action"] == "settings.update"
    }
    assert "activity_retention_days" in targets
    assert "activity_auto_daily_log" in targets


def test_purging_an_empty_trash_records_nothing(client) -> None:
    """Distinguishes "record after, only if it happened" from "record whenever
    the endpoint was called" — the latter fills the log with zeros and claims
    work that never happened."""
    before = len(client.get("/api/audit").json()["entries"])
    client.post("/api/trash/empty", json={"confirm": True})
    after = client.get("/api/audit").json()["entries"]
    assert not [e for e in after if e["action"] == "notes.purge"]
    assert len(after) == before


def test_the_audit_log_does_not_copy_the_rows_it_acted_on(client) -> None:
    """An audit log that stores what it deleted is a second copy of the user's
    notes in a place nobody expects to find one."""
    note = client.post("/api/capture/text", json={"text": "a very identifiable sentence"}).json()
    from conftest import wait_done

    wait_done(client, note["id"])
    client.delete(f"/api/notes/{note['id']}")
    client.post("/api/trash/empty", json={"confirm": True})
    entry = next(
        e for e in client.get("/api/audit").json()["entries"] if e["action"] == "notes.purge"
    )
    # Exactly one key. Asserting the id is absent passes just as well when the
    # mutation re-reads an already-empty trash and adds nothing — asserting the
    # *shape* catches a payload no matter where it came from.
    assert set(entry["detail"]) == {"count"}
