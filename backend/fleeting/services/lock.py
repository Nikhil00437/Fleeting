"""#135: lock the app until a passphrase is given.

A local-first notes app on a shared or borrowed machine is the case this is for.
The threat is not a network attacker — it is someone with the keyboard.

**The passphrase is never stored.** Only a scrypt hash, with a per-install salt,
and that hash is what the file holds. A config that contains the thing it is
supposed to protect is not a lock; it is a note about where to look.

**A wrong attempt is throttled.** Three guesses a second turns a 32-character
passphrase into a few hours of offline cracking. The delay grows with each
failure and is capped, so a lockout lasts minutes rather than becoming an
outage — the app must still be openable by the person who owns it.

**The unlock token is per-process and dies with the process.** Restarting the app
relocks it. That is the correct default for a laptop you closed and handed to
someone, and the thing that makes "unlock" mean what the user thinks it means.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("fleeting.lock")

# scrypt: n=2**15 is the interactive-login recommendation. A few hundred ms on
# unlock is invisible; the same cost per guess is what makes guessing expensive.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1

# scrypt at n=2**15, r=8 needs 128*r*(n+p+2) ≈ 33.5 MB. OpenSSL's default
# `maxmem` is 32 MB, so without this the very first hash raises
# "[digital envelope routines] memory limit exceeded" — a lock that cannot be
# set, and the one setting where a raised exception is a locked-out user.
SCRYPT_MAXMEM = 64 * 1024 * 1024

# Failures before the delay starts.
FREE_ATTEMPTS = 3
BASE_DELAY = 0.5
MAX_DELAY = 30.0

# Everything reachable while locked: health (so the app can be detected), the
# unlock endpoint itself, and nothing else. A lock you can read data through is
# not a lock.
EXEMPT = frozenset({"/api/health", "/api/lock/status", "/api/lock/unlock"})


def hash_passphrase(passphrase: str, salt: bytes | None = None) -> str:
    """`scrypt$salt$hash`, both base64url. Safe to write to config."""
    salt = salt or os.urandom(16)
    kdf = hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
        maxmem=SCRYPT_MAXMEM,
    )
    return "scrypt${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(kdf).decode("ascii"),
    )


def verify_passphrase(passphrase: str, stored: str) -> bool:
    """Constant-time compare. A timing leak on a 32-character passphrase is not
    the threat here, but it costs one line to avoid."""
    try:
        scheme, _, rest = stored.partition("$")
        salt_b64, _, hash_b64 = rest.partition("$")
        if scheme != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(hash_b64)
        got = base64.urlsafe_b64decode(hash_b64)
        kdf = hashlib.scrypt(
            passphrase.encode("utf-8"),
            salt=base64.urlsafe_b64decode(salt_b64),
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=len(got),
            maxmem=SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(kdf, expected)
    except (ValueError, TypeError):
        # A malformed or truncated hash is a lock nobody can open. Treat it as a
        # failed attempt rather than raising inside a middleware.
        log.warning("stored lock hash is malformed")
        return False


class Lock:
    """In-process lock state. One instance per app."""

    def __init__(self, enabled: bool = False, stored: str = "") -> None:
        self.enabled = bool(enabled)
        self.stored = stored or ""
        self._token: str | None = None
        self._failures = 0
        self._locked_until = 0.0
        # Reentrant: `configure()` holds this and calls `relock()`, which takes
        # it again. With a plain Lock that is a self-deadlock at startup, and a
        # lock that hangs on boot is the worst possible failure for this feature.
        self._lock = threading.RLock()

    # -- state ---------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.stored)

    def locked(self) -> bool:
        return self.enabled and self.is_configured() and self._token is None

    def delay_for_next_attempt(self) -> float:
        """Seconds the caller must wait before the next guess is accepted."""
        return max(0.0, self._locked_until - time.monotonic())

    # -- transitions ---------------------------------------------------------

    def unlock(self, passphrase: str) -> dict[str, Any]:
        """Try a passphrase. Returns `{"ok", "token"}` or `{"ok": False, ...}`."""
        if self.delay_for_next_attempt() > 0:
            return {
                "ok": False,
                "error": "too_many_attempts",
                "retry_in": round(self.delay_for_next_attempt(), 1),
            }
        if not verify_passphrase(passphrase, self.stored):
            self._failures += 1
            if self._failures >= FREE_ATTEMPTS:
                delay = min(MAX_DELAY, BASE_DELAY * 2 ** (self._failures - FREE_ATTEMPTS))
                self._locked_until = time.monotonic() + delay
            return {"ok": False, "error": "incorrect_passphrase", "attempts": self._failures}
        self._failures = 0
        self._locked_until = 0.0
        self._token = os.urandom(32).hex()
        return {"ok": True, "token": self._token}

    def check(self, presented: str | None) -> bool:
        if not self.locked():
            return True
        return bool(presented) and hmac.compare_digest(presented, self._token or "")

    def relock(self) -> None:
        """Back to locked. Used on lock, and implicitly on restart — the token
        is not persisted anywhere."""
        with self._lock:
            self._token = None
            self._failures = 0
            self._locked_until = 0.0

    def configure(self, passphrase: str | None) -> None:
        """Set, change or clear the passphrase. `None` or `""` turns the lock
        off."""
        with self._lock:
            if not passphrase:
                self.stored = ""
                self.enabled = False
                self.relock()
                return
            self.stored = hash_passphrase(passphrase)
            self.enabled = True
            self.relock()
