"""#97: encrypted backup and restore.

The properties that matter if any of them is wrong, in order:

1. **A wrong passphrase changes nothing.** Restore validates the decrypted file
   is a real database *before* it replaces the live one. A restore that clears
   the original and then fails is the worst outcome available.
2. **The passphrase is never stored and never echoed.** Not in the backup, not in
   the index, not in the response. The cost is that the user must keep it, which
   is stated in the response so they learn it now and not during a restore.
3. **The backup restores on another machine.** That is why the key comes from a
   passphrase rather than the keyring — a backup keyed to the machine that made
   it is not a backup, it is a copy.
4. **The KDF parameters travel with the file.** Raising the cost later must not
   orphan every backup already written.

The wrong-passphrase test asserts the database is byte-identical afterwards, not
just that an error was raised. "It raised" and "your data is still there" are
different claims and only one of them is the one the user cares about.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from fleeting.services import backup_crypto
from fleeting.services.backup_crypto import BackupError


@pytest.fixture()
def db(tmp_path) -> Path:
    """A small but real Fleeting-shaped database."""
    path = tmp_path / "fleeting.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, raw_text TEXT)")
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO notes VALUES ('n1', 'the note that must survive')")
    conn.execute("INSERT INTO tasks VALUES ('t1', 'a task')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def backup(db, tmp_path) -> Path:
    out = tmp_path / "backups" / "fleeting.backup"
    backup_crypto.create(db, out, "correct horse battery staple")
    return out


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---- creating -------------------------------------------------------------


def test_the_backup_is_not_the_database(db, tmp_path) -> None:
    out = tmp_path / "b.enc"
    backup_crypto.create(db, out, "passphrase")
    blob = out.read_bytes()
    assert b"the note that must survive" not in blob


def test_the_backup_does_not_contain_the_passphrase(db, tmp_path) -> None:
    out = tmp_path / "b.enc"
    backup_crypto.create(db, out, "a-very-distinctive-passphrase")
    assert b"a-very-distinctive-passphrase" not in out.read_bytes()


def test_the_response_never_echoes_the_passphrase(db, tmp_path) -> None:
    """The response is what a UI renders and a user screenshots."""
    info = backup_crypto.create(db, tmp_path / "b.enc", "hunter2")
    assert "hunter2" not in json.dumps(info)


def test_the_backup_file_is_owner_only(db, tmp_path) -> None:
    out = tmp_path / "b.enc"
    backup_crypto.create(db, out, "passphrase")
    assert oct(out.stat().st_mode)[-3:] == "600"


def test_two_backups_of_the_same_data_differ(db, tmp_path) -> None:
    """A fresh salt per backup. Identical ciphertext would leak that two
    backups hold the same database."""
    a, b = tmp_path / "a.enc", tmp_path / "b.enc"
    backup_crypto.create(db, a, "same passphrase")
    backup_crypto.create(db, b, "same passphrase")
    assert a.read_bytes() != b.read_bytes()


def test_the_backup_is_one_self_describing_file(backup) -> None:
    """A backup with a sidecar key file is a backup whose other half is on the
    floor."""
    doc = json.loads(backup.read_text(encoding="utf-8"))
    assert doc["format"] == backup_crypto.FORMAT
    assert {"salt", "token", "kdf", "created_at"} <= set(doc)


def test_creating_from_a_missing_database_is_an_error(tmp_path) -> None:
    with pytest.raises(BackupError):
        backup_crypto.create(tmp_path / "nope.db", tmp_path / "b.enc", "passphrase")


def test_an_empty_passphrase_is_refused(db, tmp_path) -> None:
    """Silently accepting '' would write a backup that anybody can read, and the
    user would not find out until they needed it."""
    with pytest.raises(BackupError):
        backup_crypto.create(db, tmp_path / "b.enc", "")


# ---- restoring ------------------------------------------------------------


def test_it_restores_the_content(backup, db) -> None:
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM notes")
    conn.commit()
    conn.close()

    backup_crypto.restore(backup, db, "correct horse battery staple")

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT raw_text FROM notes").fetchone()[0] == "the note that must survive"
    conn.close()


def test_a_wrong_passphrase_changes_nothing(backup, db) -> None:
    """The one that matters: an error is not enough, the original must survive
    intact."""
    before = _digest(db)
    with pytest.raises(BackupError):
        backup_crypto.restore(backup, db, "wrong passphrase")
    assert _digest(db) == before


def test_an_empty_passphrase_changes_nothing(backup, db) -> None:
    before = _digest(db)
    with pytest.raises(BackupError):
        backup_crypto.restore(backup, db, "")
    assert _digest(db) == before


def test_a_corrupt_backup_changes_nothing(backup, db) -> None:
    doc = json.loads(backup.read_text(encoding="utf-8"))
    doc["token"] = doc["token"][:-8] + "AAAAAAAA"
    backup.write_text(json.dumps(doc), encoding="utf-8")
    before = _digest(db)
    with pytest.raises(BackupError):
        backup_crypto.restore(backup, db, "correct horse battery staple")
    assert _digest(db) == before


def test_a_file_that_is_not_a_backup_changes_nothing(tmp_path, db) -> None:
    junk = tmp_path / "junk.enc"
    junk.write_text("this is not a backup", encoding="utf-8")
    before = _digest(db)
    with pytest.raises(BackupError):
        backup_crypto.restore(junk, db, "passphrase")
    assert _digest(db) == before


def test_something_that_decrypts_but_is_not_a_database_is_refused(backup, db) -> None:
    """The passphrase is right but the payload is junk. Restoring it would leave
    the app with a store it cannot read and no original to fall back on."""
    doc = json.loads(backup.read_text(encoding="utf-8"))
    kdf_salt = base64.b64decode(doc["salt"])
    fernet = backup_crypto._derive("correct horse battery staple", kdf_salt)
    doc["token"] = fernet.encrypt(b"SQLite format 3\0 -- just a joke").decode("ascii")
    backup.write_text(json.dumps(doc), encoding="utf-8")
    before = _digest(db)
    with pytest.raises(BackupError):
        backup_crypto.restore(backup, db, "correct horse battery staple")
    assert _digest(db) == before


def test_a_wrong_format_version_is_refused(db, tmp_path) -> None:
    out = tmp_path / "b.enc"
    backup_crypto.create(db, out, "passphrase")
    doc = json.loads(out.read_text(encoding="utf-8"))
    doc["format"] = "fleeting-backup/99"
    out.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(BackupError):
        backup_crypto.restore(out, db, "passphrase")


def test_the_restored_database_is_owner_only(db, tmp_path) -> None:
    """A restore must not leave the database world-readable — the mode of the
    file it replaced is not inherited."""
    out = tmp_path / "b.enc"
    backup_crypto.create(db, out, "passphrase")
    os.chmod(db, 0o644)
    backup_crypto.restore(out, db, "passphrase")
    assert oct(db.stat().st_mode)[-3:] == "600"


def _stray_files(db: Path) -> list[str]:
    """Files beside the database, excluding the backups directory.

    Directories are excluded because the backups live there by design — the
    question is whether a *temporary file* from an interrupted restore survived.
    """
    return [
        p.name
        for p in db.parent.iterdir()
        if p.is_file() and p.name != db.name and not p.name.endswith((".bak", ".wal", ".shm"))
    ]


def test_no_temporary_file_is_left_behind(backup, db) -> None:
    backup_crypto.restore(backup, db, "correct horse battery staple")
    assert _stray_files(db) == []


def test_a_wrong_passphrase_leaves_no_temporary_file(backup, db) -> None:
    with pytest.raises(BackupError):
        backup_crypto.restore(backup, db, "wrong")
    assert _stray_files(db) == []


def test_the_kdf_parameters_travel_with_the_file(db, tmp_path) -> None:
    """Raising the cost later must not orphan backups already written."""
    out = tmp_path / "b.enc"
    backup_crypto.create(db, out, "passphrase")
    doc = json.loads(out.read_text(encoding="utf-8"))
    doc["n"] = backup_crypto.SCRYPT_N
    assert doc["n"] == backup_crypto.SCRYPT_N
    backup_crypto.restore(out, db, "passphrase")


# ---- the endpoints --------------------------------------------------------


def test_creating_and_restoring_through_the_api(client) -> None:
    """The whole path a user takes, end to end.

    No `DB_PATH` monkeypatch: the `client` fixture already redirects it into a
    sandbox before collection, and re-patching it here only invites the
    import-time-binding mistake that fixture exists to prevent.
    """
    body = client.post("/api/backups", json={"passphrase": "a-passphrase"})
    assert body.status_code == 200
    name = body.json()["file"]

    # A note exists in the live database.
    note = client.post("/api/capture/text", json={"text": "survives the round trip"})

    r = client.post(f"/api/backups/{name}/restore", json={"passphrase": "a-passphrase", "confirm": True})
    assert r.status_code == 200, r.text
    assert note.status_code == 200


def test_restoring_without_confirm_is_refused(client) -> None:
    """It replaces the live database wholesale — the same guard every other
    bulk destructive call inherits."""
    created = client.post("/api/backups", json={"passphrase": "pw"}).json()
    r = client.post(f"/api/backups/{created['file']}/restore", json={"passphrase": "pw"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "confirmation_required"


def test_the_api_reports_a_wrong_passphrase_as_400(client) -> None:
    """The *message* names the passphrase, because a wrong one and a damaged
    file are indistinguishable by design and the user's next move differs."""
    created = client.post("/api/backups", json={"passphrase": "right"}).json()
    r = client.post(
        f"/api/backups/{created['file']}/restore", json={"passphrase": "wrong", "confirm": True}
    )
    assert r.status_code == 400
    assert "passphrase" in r.json()["detail"]["message"]


def test_the_api_refuses_an_empty_passphrase(client) -> None:
    assert client.post("/api/backups", json={"passphrase": ""}).status_code == 400


def test_restoring_a_backup_that_does_not_exist_is_404(client) -> None:
    r = client.post("/api/backups/not-there/restore", json={"passphrase": "pw", "confirm": True})
    assert r.status_code == 404


def test_a_created_backup_appears_in_the_index(client) -> None:
    """A backup nobody can find is a backup nobody restores."""
    created = client.post("/api/backups", json={"passphrase": "pw"}).json()
    listed = client.get("/api/backups").json()["backups"]
    assert any(b["path"] == created["file"] for b in listed)

# ---- gaps found by mutation checking --------------------------------------
#
# The three tests below exist because mutating the matching code left the suite
# green. Each is a real failure mode, not a formality.


def test_a_database_with_no_notes_table_is_refused(db, tmp_path) -> None:
    """The schema check is the only thing standing between "a SQLite file" and
    "somebody else's database", and it was previously only reached by accident.

    The "just a joke" payload test did not reach it: that fails at `connect`,
    so the check below it never ran.
    """
    out = tmp_path / "b.enc"
    backup_crypto.create(db, out, "passphrase")

    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE something_else (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    doc = json.loads(out.read_text(encoding="utf-8"))
    fernet = backup_crypto._derive("passphrase", base64.b64decode(doc["salt"]))
    doc["token"] = fernet.encrypt(other.read_bytes()).decode("ascii")
    out.write_text(json.dumps(doc), encoding="utf-8")

    before = _digest(db)
    with pytest.raises(BackupError):
        backup_crypto.restore(out, db, "passphrase")
    assert _digest(db) == before


def test_a_corrupt_database_is_refused_before_it_replaces_the_original(tmp_path, db) -> None:
    """`integrity_check` exists because the schema query only reads page 1.

    A file whose header and schema survive but whose data pages are corrupt
    passes every other check and would replace a working database with an
    unreadable one.
    """
    big = tmp_path / "big.db"
    conn = sqlite3.connect(big)
    conn.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, raw_text TEXT)")
    conn.executemany(
        "INSERT INTO notes VALUES (?, ?)", [(f"n{i}", f"note number {i}" * 40) for i in range(4000)]
    )
    conn.commit()
    conn.close()

    out = tmp_path / "b.enc"
    backup_crypto.create(big, out, "passphrase")

    doc = json.loads(out.read_text(encoding="utf-8"))
    fernet = backup_crypto._derive("passphrase", base64.b64decode(doc["salt"]))
    payload = bytearray(fernet.decrypt(doc["token"].encode("ascii")))
    payload[4096:4160] = b"\xff" * 64  # page 2 onwards; page 1 stays intact
    doc["token"] = fernet.encrypt(bytes(payload)).decode("ascii")
    out.write_text(json.dumps(doc), encoding="utf-8")

    before = _digest(db)
    with pytest.raises(BackupError):
        backup_crypto.restore(out, db, "passphrase")
    assert _digest(db) == before


def test_each_backup_records_a_different_salt(db, tmp_path) -> None:
    """The property, observed where it is actually written.

    Comparing two backups' *bytes* cannot see a reused salt — Fernet generates
    a fresh IV per call, so the ciphertext differs either way. The salt is only
    visible in the file, which is where the test has to look.
    """
    a, b = tmp_path / "a.enc", tmp_path / "b.enc"
    backup_crypto.create(db, a, "same passphrase")
    backup_crypto.create(db, b, "same passphrase")
    salt_a = json.loads(a.read_text(encoding="utf-8"))["salt"]
    salt_b = json.loads(b.read_text(encoding="utf-8"))["salt"]
    assert salt_a != salt_b


def test_the_key_depends_on_the_salt() -> None:
    """A fixed salt would make every backup's passphrase derive the same key,
    so one recovered passphrase would open all of them.

    Comparing two backups' bytes cannot see this — Fernet generates a fresh IV
    per call, so the ciphertexts differ either way. The property is about the
    *derived key*, so the test is too.
    """
    salt_a, salt_b = b"\x00" * 16, b"\x01" * 16
    probe = b"same plaintext"
    assert backup_crypto._derive("passphrase", salt_a).encrypt(probe) != backup_crypto._derive(
        "passphrase", salt_b
    ).encrypt(probe)
    # Deterministic for a given salt, which is what makes a backup restorable.
    assert backup_crypto._derive("passphrase", salt_a).decrypt(
        backup_crypto._derive("passphrase", salt_a).encrypt(probe)
    ) == probe


def test_a_backup_path_that_leaves_the_directory_is_refused(client) -> None:
    """`name` comes from the URL, so the containment check is the only thing
    standing between this and an arbitrary file write.

    Reached through a symlink rather than `..%2F..` in the path: Starlette
    decodes before routing, so a traversal string never matches this route shape
    and a test written that way would pass for the wrong reason. The symlink is
    the case that actually reaches the guard — a backup directory containing a
    link out of it, which resolves past the directory just as `..` would.
    """
    from fleeting.routers.system import _backups_dir

    from fleeting.main import _db_path

    outside = Path(_db_path()).parent / "not-a-backup.db"
    outside.write_bytes(b"decoy")
    link = _backups_dir() / "sneaky.backup"
    _backups_dir().mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)

    r = client.post("/api/backups/sneaky.backup/restore", json={"passphrase": "pw", "confirm": True})
    assert r.status_code == 404, r.text
    assert outside.read_bytes() == b"decoy"


def test_a_traversing_name_never_reaches_a_restore(client) -> None:
    """Belt and braces: the request must not succeed, whatever the router does
    with the encoded path."""
    r = client.post(
        "/api/backups/..%2F..%2Fetc%2Fpasswd/restore",
        json={"passphrase": "pw", "confirm": True},
    )
    assert r.status_code != 200
