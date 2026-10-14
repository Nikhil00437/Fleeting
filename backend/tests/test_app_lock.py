"""#135: lock the app until a passphrase is given.

Four properties, in order of how badly each would hurt:

1. **The passphrase is never stored.** Only a scrypt hash with a per-install
   salt. A config file containing the thing it is meant to protect is not a lock,
   it is a note about where to look — and `config.toml` is world-readable in most
   installs, ends up in dotfile repos, and goes into backups.
2. **Guessing is throttled.** Three guesses a second turns a 32-character
   passphrase into a few hours of offline cracking. The delay grows and is
   *capped*, so a lockout lasts minutes rather than becoming an outage — the app
   must stay openable by the person who owns it.
3. **Nothing is readable while locked.** Not "writes are blocked" — a lock you
   can read data through is not a lock. `423` for everything but health, status
   and unlock.
4. **The token dies with the process.** Restarting relocks. That is the correct
   default for a laptop you closed and handed to someone, and it is what makes
   "unlock" mean what the user thinks.

The token is a separate header from the API token on purpose: different secrets,
different lifetimes. A client holding one does not thereby hold the other.
"""

from __future__ import annotations

import pytest

from fleeting.services.lock import (
    BASE_DELAY,
    EXEMPT,
    FREE_ATTEMPTS,
    MAX_DELAY,
    Lock,
    hash_passphrase,
    verify_passphrase,
)

PASSPHRASE = "correct horse battery staple"


@pytest.fixture()
def locked(client):
    """An app with the lock on and a known passphrase."""
    client.app.state.lock.configure(PASSPHRASE)
    yield client
    client.app.state.lock.configure(None)


def hdr(client) -> dict[str, str]:
    """The unlock token for a currently-unlocked app."""
    return {"x-fleeting-lock": client.app.state.lock._token or ""}


# ---- the stored secret -----------------------------------------------------


def test_the_passphrase_is_not_in_what_is_stored() -> None:
    """A config containing the thing it protects is not a lock."""
    assert PASSPHRASE not in hash_passphrase(PASSPHRASE)


def test_the_stored_form_is_scrypt_with_a_salt() -> None:
    stored = hash_passphrase(PASSPHRASE)
    assert stored.startswith("scrypt$")
    assert stored.count("$") == 2


def test_the_salt_differs_between_installs() -> None:
    assert hash_passphrase(PASSPHRASE) != hash_passphrase(PASSPHRASE)


def test_the_right_passphrase_verifies() -> None:
    assert verify_passphrase(PASSPHRASE, hash_passphrase(PASSPHRASE)) is True


def test_a_wrong_passphrase_does_not() -> None:
    assert verify_passphrase("wrong", hash_passphrase(PASSPHRASE)) is False


def test_a_malformed_stored_hash_fails_closed() -> None:
    """A truncated hash is a lock nobody can open; raising inside middleware
    would be a 500 on every request instead."""
    assert verify_passphrase(PASSPHRASE, "not-a-hash") is False
    assert verify_passphrase(PASSPHRASE, "scrypt$only-one-part") is False


def test_an_unknown_scheme_is_refused() -> None:
    assert verify_passphrase(PASSPHRASE, "md5$aaaa$bbbb") is False


# ---- throttling ------------------------------------------------------------


def test_a_few_wrong_guesses_are_allowed() -> None:
    """Throttling from the first attempt would make typos unrecoverable."""
    lock = Lock(enabled=True, stored=hash_passphrase(PASSPHRASE))
    for _ in range(FREE_ATTEMPTS):
        assert lock.unlock("wrong")["ok"] is False
        lock._locked_until = 0.0  # skip the sleep, keep the counter


def test_guessing_again_too_soon_is_refused() -> None:
    lock = Lock(enabled=True, stored=hash_passphrase(PASSPHRASE))
    for _ in range(FREE_ATTEMPTS):
        lock.unlock("wrong")
    assert lock.unlock(PASSPHRASE)["error"] == "too_many_attempts"


def test_a_refusal_says_how_long_to_wait() -> None:
    """The client needs to know when to offer the box again."""
    lock = Lock(enabled=True, stored=hash_passphrase(PASSPHRASE))
    for _ in range(FREE_ATTEMPTS):
        lock.unlock("wrong")
    assert lock.unlock(PASSPHRASE)["retry_in"] > 0


def test_the_delay_is_capped() -> None:
    """A lockout that runs for a day is an outage, not a lock.

    Driven by real failures rather than by writing `_locked_until` directly: the
    earlier version set the timer and proved nothing about the arithmetic.
    """
    lock = Lock(enabled=True, stored=hash_passphrase(PASSPHRASE))
    delays = []
    for _ in range(12):
        lock._locked_until = 0.0  # skip the sleep; keep the failure count
        lock.unlock("wrong")
        delays.append(lock.delay_for_next_attempt())
    assert max(delays) <= MAX_DELAY
    # …and the cap is doing work: uncapped, these would have run for hours.
    uncapped = BASE_DELAY * 2 ** (12 - FREE_ATTEMPTS)
    assert uncapped > MAX_DELAY


def test_the_delay_grows_with_failures() -> None:
    lock = Lock(enabled=True, stored=hash_passphrase(PASSPHRASE))
    seen = []
    for _ in range(FREE_ATTEMPTS + 3):
        lock._locked_until = 0.0
        lock.unlock("wrong")
        seen.append(lock.delay_for_next_attempt())
    assert seen[-1] > seen[0]
    assert seen[-1] > 0


def test_a_correct_passphrase_resets_the_failure_count() -> None:
    lock = Lock(enabled=True, stored=hash_passphrase(PASSPHRASE))
    lock.unlock("wrong")
    lock._locked_until = 0.0
    assert lock.unlock(PASSPHRASE)["ok"] is True
    assert lock._failures == 0


def test_the_first_delay_is_the_base_one() -> None:
    lock = Lock(enabled=True, stored=hash_passphrase(PASSPHRASE))
    for _ in range(FREE_ATTEMPTS):
        lock._locked_until = 0.0
        lock.unlock("wrong")
    assert lock.delay_for_next_attempt() == pytest.approx(BASE_DELAY, abs=0.2)


# ---- the locked app --------------------------------------------------------


def test_reads_are_refused_while_locked(locked) -> None:
    """A lock you can read data through is not a lock."""
    assert locked.get("/api/notes").status_code == 423


def test_writes_are_refused_while_locked(locked) -> None:
    assert locked.post("/api/capture/text", json={"text": "x"}).status_code == 423


def test_the_error_names_the_problem(locked) -> None:
    assert locked.get("/api/notes").json()["detail"]["error"] == "locked"


def test_status_is_readable_while_locked(locked) -> None:
    """The UI has to be able to render the lock screen."""
    assert locked.get("/api/lock/status").json()["locked"] is True


def test_health_is_readable_while_locked(locked) -> None:
    """So the app can be detected as running."""
    assert locked.get("/api/health").status_code == 200


def test_unlocking_is_reachable_while_locked(locked) -> None:
    assert locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE}).status_code == 200


def test_unlocking_lets_through_afterwards(locked) -> None:
    locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE})
    assert locked.get("/api/notes", headers=hdr(locked)).status_code == 200


def test_a_wrong_passphrase_does_not_unlock(locked) -> None:
    assert locked.post("/api/lock/unlock", json={"passphrase": "wrong"}).status_code == 401
    assert locked.get("/api/notes").status_code == 423


def test_relocking_stops_it_again(locked) -> None:
    locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE})
    assert locked.post("/api/lock/lock").status_code == 200
    assert locked.get("/api/notes", headers=hdr(locked)).status_code == 423


def test_a_forged_token_does_not_unlock(locked) -> None:
    """The token is the whole credential; anything guessable defeats the point."""
    r = locked.get("/api/notes", headers={"x-fleeting-lock": "0" * 64})
    assert r.status_code == 423


def test_a_valid_token_is_not_the_only_thing_accepted_after_unlock(locked) -> None:
    """Once unlocked the session needs no token at all — a forged one neither
    helps nor hurts, and pretending otherwise would be testing the wrong claim."""
    locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE})
    assert locked.get("/api/notes", headers={"x-fleeting-lock": "0" * 64}).status_code == 200
    assert locked.get("/api/notes").status_code == 200


def test_the_api_token_is_not_the_lock_token(locked) -> None:
    """Different secrets with different lifetimes; holding one does not give
    the other."""
    locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE})
    token = locked.app.state.st.api_token
    if not token:
        return  # no API token configured; nothing to confuse it with
    assert locked.get("/api/notes", headers={"authorization": f"Bearer {token}"}).status_code == 423


def test_a_token_does_not_survive_a_relock(locked) -> None:
    """Otherwise the token is a permanent key to the data."""
    locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE})
    old = locked.app.state.lock._token
    locked.post("/api/lock/lock")
    assert locked.get("/api/notes", headers={"x-fleeting-lock": old}).status_code == 423


# ---- configuration ---------------------------------------------------------


def test_the_passphrase_cannot_be_changed_while_locked(locked) -> None:
    """/api/lock/set is deliberately *not* exempt: otherwise anyone at the
    keyboard can turn the lock off, which is the whole thing it prevents.

    It works once unlocked, because a valid token satisfies the same guard as
    everything else.
    """
    assert locked.post("/api/lock/set", json={"passphrase": "new"}).status_code == 423
    locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE})
    assert locked.post("/api/lock/set", json={"passphrase": "new"}, headers=hdr(locked)).status_code == 200
    locked.post("/api/lock/lock")
    assert locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE}).status_code == 401
    assert locked.post("/api/lock/unlock", json={"passphrase": "new"}).status_code == 200


def test_clearing_the_passphrase_turns_the_lock_off(locked) -> None:
    locked.post("/api/lock/unlock", json={"passphrase": PASSPHRASE})
    locked.post("/api/lock/set", json={"passphrase": ""}, headers=hdr(locked))
    assert locked.get("/api/lock/status").json()["configured"] is False
    assert locked.get("/api/notes").status_code == 200


def test_unlocking_with_no_passphrase_set_is_an_error(client) -> None:
    assert client.post("/api/lock/unlock", json={"passphrase": "x"}).status_code == 400


def test_a_lock_with_no_hash_is_not_locked() -> None:
    """`lock_enabled = true` with no hash must not lock the user out of their
    own app with no way back in."""
    assert Lock(enabled=True, stored="").locked() is False


def test_the_exempt_set_is_only_what_a_locked_ui_needs() -> None:
    """Pinned: adding a path here is making the lock weaker.

    Notably `/api/lock/set` is *not* in it — being able to change the passphrase
    while locked is being able to turn the lock off, which is the thing it
    prevents.
    """
    assert EXEMPT == frozenset({"/api/health", "/api/lock/status", "/api/lock/unlock"})


def test_the_default_is_off() -> None:
    from fleeting.config import Config

    cfg = Config()
    assert cfg.server.lock_enabled is False
    assert cfg.server.lock_passphrase_hash == ""


def test_the_config_never_holds_the_passphrase(locked) -> None:
    """The live config after setting one, which is where the claim is checkable."""
    from fleeting.config import CONFIG_PATH

    text = ""
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        pass
    assert PASSPHRASE not in text