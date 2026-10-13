"""#99: encrypt content at rest, with the key in the keyring.

Fernet (AES-128-CBC + HMAC-SHA256) over a key held in the OS keyring. Authenticated
means a tampered ciphertext fails loudly rather than decrypting to garbage, which
is the property that makes "we encrypt it" a real statement rather than a
promise.

**What this does and does not protect, stated up front.** It encrypts the
*content* of notes marked `sensitive`, in the database. It does not encrypt the
SQLite file: whole-file encryption needs SQLCipher, which is a custom SQLite
build and a packaging change rather than a dependency. The item's wording asks for
the file, so this is the honest subset and the gap is recorded rather than papered
over.

Two design points that are easy to get wrong:

- **A row that is not ciphertext must not be treated as ciphertext.** Encryption
  was optional and is off by default, so every existing row is plaintext. The
  marker is a prefix on the stored value and `decrypt()` returns non-marked input
  unchanged — otherwise turning encryption on would render the whole database
  unreadable.
- **The key is in the keyring, never in the config.** The same rule as #139: the
  config says *that* a key exists, not what it is.
"""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from .keyring import get as keyring_get, set_secret

log = logging.getLogger("fleeting.crypto")

KEY_NAME = "fleeting.content_key"

# Prefix marking a stored value as ciphertext. Any decryptor checks it, so a
# plaintext row and an encrypted one can coexist in the same column.
MARKER = "enc:v1:"


def get_key() -> Fernet | None:
    """The content key, created on first use.

    None when there is no way to store one — a machine with no keyring and an
    unwritable config directory cannot keep a key safely, and silently falling
    back to a hardcoded key would be worse than not encrypting.
    """
    raw = keyring_get(KEY_NAME)
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except (ValueError, TypeError):
            log.warning("stored content key is malformed — regenerating")
    try:
        # `generate_key` returns raw bytes, not a Fernet — returning it unwrapped
        # hands callers something that only explodes later, at `encrypt()`.
        key = Fernet.generate_key()
        fernet = Fernet(key)
    except Exception:  # noqa: BLE001
        log.warning("could not generate a content key", exc_info=True)
        return None
    if set_secret(KEY_NAME, key.decode("utf-8")):
        return fernet
    # Only the file fallback declined. Encryption cannot proceed safely without a
    # durable key, so this reports "off" rather than pretending.
    log.warning("could not store the content key — encryption stays off")
    return None


def encrypt_text(plain: str, fernet: Fernet | None) -> str:
    """Encrypt, or return the input unchanged when there is no key.

    Returning plaintext is a real downgrade, and the caller is expected to have
    checked `encryption_available()` — this function exists for the case where a
    note is written while the keyring is briefly unavailable, and failing the
    write instead would lose the note.
    """
    if fernet is None or not plain:
        return plain
    return MARKER + fernet.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(stored: str, fernet: Fernet | None) -> str:
    """Decrypt, or return the input unchanged when it is not ciphertext.

    The "not ciphertext" case is the common one: encryption is off by default, so
    most rows are plaintext and must keep reading back as themselves.
    """
    if not stored or not stored.startswith(MARKER):
        return stored
    if fernet is None:
        log.error("content is encrypted but no key is available — returning it as stored")
        return stored
    try:
        return fernet.decrypt(stored[len(MARKER) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):
        # A wrong key or a tampered row. Returning the ciphertext is honest:
        # empty text would look like a note with no content.
        log.error("could not decrypt content — wrong key or the row was modified")
        return stored


def is_encrypted(stored: str) -> bool:
    return bool(stored) and stored.startswith(MARKER)


def status() -> dict[str, object]:
    """What Settings shows. Never contains key material, not even a length."""
    fernet = get_key()
    return {
        "available": fernet is not None,
        "algorithm": "fernet (AES-128-CBC + HMAC-SHA256)",
        "covers": "the content of notes marked sensitive, in the database",
        "does_not_cover": (
            "the SQLite file itself — that needs SQLCipher, a custom SQLite build. "
            "Exported backups are encrypted separately."
        ),
    }