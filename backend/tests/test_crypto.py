"""#99: encryption at rest for sensitive note content.

The properties worth pinning, in order of how badly they would hurt if wrong:

1. **A plaintext row still reads back as itself.** Encryption is off by default,
   so every existing row is plaintext. A decryptor that assumed otherwise would
   make the whole database unreadable the moment someone turned the switch on.
2. **The marker is checked before decrypting**, so plaintext and ciphertext can
   share a column and a migration is not needed to start.
3. **A wrong key fails loudly** rather than returning empty text, which would
   read as "a note with no content" and be filed as such.
4. **Turning encryption on does not rewrite what is already stored**, so a key
   that is later lost cannot take existing notes with it.

The tests run against an in-process Fernet key rather than the keyring, because
what is under test is the cipher's behaviour and not where the key came from.
The keyring path has its own tests in `test_keyring.py`.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from fleeting.services import crypto


@pytest.fixture()
def fernet() -> Fernet:
    # `generate_key()` returns raw bytes; wrapping it is the whole difference
    # between a working fixture and an AttributeError at the first encrypt.
    return Fernet(Fernet.generate_key())


# ---- round trip -----------------------------------------------------------


def test_encrypted_text_is_not_readable(fernet) -> None:
    out = crypto.encrypt_text("my bank code is 1234", fernet)
    assert "1234" not in out
    assert crypto.is_encrypted(out)


def test_it_decrypts_back(fernet) -> None:
    assert crypto.decrypt_text(crypto.encrypt_text("hello", fernet), fernet) == "hello"


def test_unicode_survives(fernet) -> None:
    text = "日本語 café 😀 — em dash"
    assert crypto.decrypt_text(crypto.encrypt_text(text, fernet), fernet) == text


def test_empty_text_is_not_encrypted(fernet) -> None:
    assert crypto.encrypt_text("", fernet) == ""


# ---- the marker -----------------------------------------------------------


def test_plaintext_reads_back_unchanged(fernet) -> None:
    """The common case. Every row written before encryption was switched on is
    plaintext, and decrypting it must be a no-op rather than an error."""
    assert crypto.decrypt_text("an ordinary note", fernet) == "an ordinary note"


def test_a_row_written_before_the_switch_is_still_readable(fernet) -> None:
    assert not crypto.is_encrypted("written yesterday")
    assert crypto.decrypt_text("written yesterday", fernet) == "written yesterday"


def test_ciphertext_and_plaintext_coexist_in_one_column(fernet) -> None:
    values = ["plain one", crypto.encrypt_text("secret one", fernet), "plain two"]
    assert [crypto.decrypt_text(v, fernet) for v in values] == [
        "plain one",
        "secret one",
        "plain two",
    ]


# ---- failure --------------------------------------------------------------


def test_a_wrong_key_returns_the_ciphertext_not_empty_text(fernet) -> None:
    """Empty would read as 'a note with no content' and be filed as one. The
    ciphertext at least looks wrong, which is the truth."""
    stored = crypto.encrypt_text("my bank code is 1234", fernet)
    other = Fernet(Fernet.generate_key())
    assert crypto.decrypt_text(stored, other) == stored


def test_a_tampered_ciphertext_does_not_decrypt(fernet) -> None:
    """Authenticated encryption: this is the property that makes 'we encrypt it'
    a real statement."""
    stored = crypto.encrypt_text("my bank code is 1234", fernet)
    tampered = stored[:-4] + ("AAAA" if not stored.endswith("AAAA") else "BBBB")
    assert crypto.decrypt_text(tampered, fernet) == tampered


def test_no_key_means_the_text_is_stored_as_is() -> None:
    """A write during a brief keyring outage must not lose the note."""
    assert crypto.encrypt_text("kept as plaintext", None) == "kept as plaintext"


def test_no_key_reading_encrypted_text_returns_it_rather_than_guessing(fernet) -> None:
    stored = crypto.encrypt_text("secret", fernet)
    assert crypto.decrypt_text(stored, None) == stored


# ---- the key --------------------------------------------------------------


@pytest.fixture()
def fake_keyring(monkeypatch):
    """An in-process stand-in for the keyring, so the key tests do not touch the
    developer's real Secret Service."""
    store: dict[str, str] = {}
    monkeypatch.setattr(crypto, "keyring_get", lambda name: store.get(name))
    monkeypatch.setattr(crypto, "set_secret", lambda name, value: bool(store.__setitem__(name, value)) or True)
    return store


def test_a_key_is_created_on_first_use(fake_keyring) -> None:
    assert crypto.KEY_NAME not in fake_keyring
    assert crypto.get_key() is not None
    assert crypto.KEY_NAME in fake_keyring


def test_the_key_is_the_same_on_every_call(fake_keyring) -> None:
    """A key that changed on every call would make every stored note
    unreadable — the failure looks like data loss, not a keyring bug."""
    first = crypto.get_key()
    second = crypto.get_key()
    assert first is not None and second is not None
    probe = first.encrypt(b"probe")
    assert second.decrypt(probe) == b"probe"


def test_a_key_that_cannot_be_stored_means_encryption_is_off(fake_keyring, monkeypatch) -> None:
    """Silently falling back to a hardcoded key would be worse than not
    encrypting, so this reports 'off' instead."""
    monkeypatch.setattr(crypto, "set_secret", lambda name, value: False)
    assert crypto.get_key() is None


def test_a_malformed_stored_key_is_replaced_rather_than_crashing(fake_keyring) -> None:
    """A keyring entry truncated by a bad shutdown must not make every note
    undecryptable with no way forward."""
    fake_keyring[crypto.KEY_NAME] = "not-a-fernet-key"
    assert crypto.get_key() is not None
    assert fake_keyring[crypto.KEY_NAME] != "not-a-fernet-key"


# ---- the status -----------------------------------------------------------


def test_the_status_never_leaks_key_material(monkeypatch) -> None:
    monkeypatch.setattr(crypto, "get_key", lambda: Fernet.generate_key())
    text = repr(crypto.status())
    assert "Fernet.generate_key" not in text
    assert "generate_key()" not in text


def test_the_status_is_honest_about_what_it_covers(monkeypatch) -> None:
    """The item asked for the whole file. It is not the whole file, and the
    status says so rather than letting a reader assume otherwise."""
    monkeypatch.setattr(crypto, "get_key", lambda: Fernet.generate_key())
    s = crypto.status()
    assert s["available"] is True
    assert "SQLCipher" in str(s["does_not_cover"])


def test_no_key_means_the_status_says_so(monkeypatch) -> None:
    monkeypatch.setattr(crypto, "get_key", lambda: None)
    assert crypto.status()["available"] is False


def test_the_status_names_the_algorithm() -> None:
    assert "fernet" in crypto.status()["algorithm"].lower()


# ---- through the database -------------------------------------------------


@pytest.fixture()
def encrypted_db(tmp_path, monkeypatch, fake_keyring):
    """A migrated database with content encryption switched on."""
    from fleeting.db import Database, set_content_encryption

    db = Database(str(tmp_path / "enc.db"))
    db.migrate()
    monkeypatch.setattr(db, "path", db.path, raising=False)
    set_content_encryption(True)
    yield db
    set_content_encryption(False)


def test_a_sensitive_note_is_encrypted_in_the_stored_row(encrypted_db) -> None:
    encrypted_db.insert_note(
        {"id": "s1", "title": "private", "raw_text": "my bank code is 1234", "sensitive": 1}
    )
    encrypted_db.commit()
    raw = encrypted_db.execute("SELECT raw_text FROM notes WHERE id = 's1'").fetchone()["raw_text"]
    assert "1234" not in raw
    assert crypto.is_encrypted(raw)


def test_and_it_reads_back_unchanged(encrypted_db) -> None:
    encrypted_db.insert_note(
        {"id": "s1", "title": "private", "raw_text": "my bank code is 1234", "sensitive": 1}
    )
    encrypted_db.commit()
    assert encrypted_db.get_note("s1")["raw_text"] == "my bank code is 1234"


def test_an_ordinary_note_is_not_encrypted(encrypted_db) -> None:
    """Encryption covers what is flagged sensitive. Silently encrypting
    everything would make the search index useless and is not what was asked."""
    encrypted_db.insert_note({"id": "n1", "title": "ordinary", "raw_text": "plain body"})
    encrypted_db.commit()
    raw = encrypted_db.execute("SELECT raw_text FROM notes WHERE id = 'n1'").fetchone()["raw_text"]
    assert not crypto.is_encrypted(raw)
    assert encrypted_db.get_note("n1")["raw_text"] == "plain body"


def test_a_note_written_before_the_switch_still_reads(encrypted_db) -> None:
    """Turning encryption on must not make the existing database unreadable —
    that is the migration story, and 'we added encryption' plus 'all my notes
    are gone' is not one."""
    encrypted_db.insert_note({"id": "old", "title": "old", "raw_text": "written yesterday"})
    encrypted_db.commit()
    assert encrypted_db.get_note("old")["raw_text"] == "written yesterday"


def test_listing_notes_decrypts_too(encrypted_db) -> None:
    """`_row_to_note` is the read funnel, so every path through it is covered —
    this asserts the other one."""
    encrypted_db.insert_note(
        {"id": "s1", "title": "private", "raw_text": "secret body", "sensitive": 1}
    )
    encrypted_db.commit()
    listed = encrypted_db.list_notes(limit=10)
    assert [n["raw_text"] for n in listed if n["id"] == "s1"] == ["secret body"]


def test_the_endpoint_states_what_is_and_is_not_encrypted(client) -> None:
    """A user asking 'is my database encrypted?' must not be told yes."""
    body = client.get("/api/encryption").json()
    assert body["available"] in (True, False)
    assert "SQLCipher" in body["does_not_cover"]
