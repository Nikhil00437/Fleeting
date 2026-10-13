"""#97: a backup you can put on a machine you do not control.

#188 backs up before every migration, but those files sit next to the database in
plaintext — fine for "the migration broke, roll back", useless for "I am moving
machines" or "this laptop is being stolen". This writes a self-contained
encrypted backup instead.

**One file, self-describing.** The salt, KDF parameters and ciphertext all live in
a single JSON document. A backup with a sidecar key file is a backup whose other
half is on the floor; a single file can be copied, emailed and verified on its
own.

**The passphrase is supplied per call and never stored.** This is the decision
that matters. Deriving the key from the keyring's content key would make the
backup unrestorable onto any other machine, which defeats the point of a backup —
the machine that needs one is often the one that died. A passphrase the user
holds works everywhere, and the cost is that they must keep it, which is stated
in the response rather than discovered at restore time.

**Restore is a restore, not a merge.** It replaces the database wholesale. Anything
cunning enough to reconcile two histories is a data-corruption risk dressed as a
feature, and the user who wants the old data back wants the old data, not a blend
of it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

log = logging.getLogger("fleeting.backup_crypto")

FORMAT = "fleeting-backup/1"

# Scrypt cost. n=2**15 is the interactive-login recommendation and takes a few
# hundred ms — slow enough to make guessing a passphrase expensive, fast enough
# that a restore at 2am does not feel broken.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1

# A restored database must not be left world-readable. SQLite does not inherit
# the mode of the file it replaces, so this has to be set explicitly.
DB_MODE = 0o600


class BackupError(RuntimeError):
    """Anything that stops a backup being written or restored."""


def _derive(passphrase: str, salt: bytes) -> Fernet:
    if not passphrase:
        raise BackupError("a passphrase is required")
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8"))))


def _snapshot(db_path: str | Path) -> bytes:
    """The database as a consistent byte image.

    SQLite's backup API, for the reason #188 documents: the app runs in WAL mode,
    so recent commits live in the `-wal` sidecar and a plain file copy silently
    omits them.
    """
    source = Path(db_path)
    if not source.exists():
        raise BackupError(f"no database at {source}")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "snapshot.db"
        try:
            src = sqlite3.connect(str(source))
            try:
                dst = sqlite3.connect(str(copy))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            return copy.read_bytes()
        except sqlite3.Error as exc:
            raise BackupError(f"could not snapshot the database: {exc}") from exc


def create(db_path: str | Path, out_path: str | Path, passphrase: str) -> dict[str, Any]:
    """Write an encrypted backup. Returns the index entry describing it."""
    salt = os.urandom(16)
    fernet = _derive(passphrase, salt)
    payload = _snapshot(db_path)
    target = Path(out_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "format": FORMAT,
                    "kdf": "scrypt",
                    "salt": base64.b64encode(salt).decode("ascii"),
                    "n": SCRYPT_N,
                    "r": SCRYPT_R,
                    "p": SCRYPT_P,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "token": fernet.encrypt(payload).decode("ascii"),
                }
            ),
            encoding="utf-8",
        )
        os.chmod(target, DB_MODE)
    except OSError as exc:
        raise BackupError(f"could not write the backup: {exc}") from exc
    return {
        "file": target.name,
        "file_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "bytes": len(payload),
        "format": FORMAT,
        # Never echoed back and never logged — the response is what a UI shows,
        # and a passphrase in an API payload is a passphrase in a screenshot.
        "restore_requires": "the passphrase used to create it",
    }


def _read(path: str | Path) -> dict[str, Any]:
    """Parse and sanity-check the header. Does not decrypt anything."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError(f"not a readable backup: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise BackupError(f"unsupported backup format: {doc.get('format')!r}")
    for field in ("salt", "token"):
        if not doc.get(field):
            raise BackupError(f"malformed backup: no {field}")
    return doc


def restore(path: str | Path, db_path: str | Path, passphrase: str) -> dict[str, Any]:
    """Decrypt a backup over the live database. Replaces it wholesale."""
    doc = _read(path)
    if not passphrase:
        raise BackupError("a passphrase is required")
    salt = base64.b64decode(doc["salt"])
    fernet = _derive(passphrase, salt)
    try:
        payload = fernet.decrypt(doc["token"].encode("ascii"))
    except (InvalidToken, KeyError) as exc:
        # A wrong passphrase and a corrupted file are indistinguishable here, and
        # that is fine: both are fixed by trying the passphrase again. Saying
        # which one it was would tell an attacker whether their guess was close.
        raise BackupError(
            "wrong passphrase, or the backup is damaged"
        ) from exc
    try:
        # Validate before replacing anything. Restoring a file that is not a
        # database would leave the app with a corrupt store and no original.
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(payload)
            check = tmp.name
        try:
            probe = sqlite3.connect(check)
            try:
                # `integrity_check` returns "ok" or a description of what is
                # wrong. Calling it without reading the answer is a no-op that
                # looks like a check.
                verdict = probe.execute("PRAGMA integrity_check").fetchone()[0]
                if verdict != "ok":
                    raise BackupError(f"the backup decrypted but is corrupt: {verdict}")
                names = {
                    r[0]
                    for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
            finally:
                probe.close()
        finally:
            os.unlink(check)
    except sqlite3.Error as exc:
        raise BackupError(f"the backup decrypted but is not a database: {exc}") from exc
    if "notes" not in names:
        raise BackupError("the decrypted file is a database, but not a Fleeting one")

    target = Path(db_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: a restore interrupted halfway through must not leave a
        # half-written database behind, which is worse than the original problem.
        tmp = target.with_name(f"{target.name}.restore-tmp")
        tmp.write_bytes(payload)
        os.chmod(tmp, DB_MODE)
        os.replace(tmp, target)
    except OSError as exc:
        raise BackupError(f"could not write the restored database: {exc}") from exc
    return {
        "restored": True,
        "bytes": len(payload),
        "tables": len(names),
        "replaced": str(target),
    }