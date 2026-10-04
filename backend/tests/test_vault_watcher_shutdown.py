"""Shutdown must not deadlock against the observer thread.

`VaultWatcher.stop()` acquired `self._lock` and then called into watchdog's
stop path, which blocks in `_clear_emitters()` on `emitter.join()` with no
timeout. Meanwhile the observer thread can be inside `_schedule_debounce`,
which needs `self._lock`. So:

    stop() holds _lock  ->  waits for the observer thread
    observer thread     ->  waits for _lock

Neither ever proceeds, and `TestClient.__exit__` / the lifespan never
completes. Measured at roughly 3-6 runs in 20 on the full suite.

`join(timeout=...)` on line 214 did not help: the block happens earlier, inside
`observer.stop()` itself.

The invariant, tested deterministically rather than by racing threads:
**`stop()` must not hold `_lock` while inside watchdog.**
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from fleeting.services.vault_watcher import VaultWatcher


class _FakeObserver:
    """Stands in for watchdog's BaseObserver.

    `stop()` is where the real implementation blocks on `emitter.join()`, so
    that is where we assert the lock state.
    """

    def __init__(self, watcher: VaultWatcher) -> None:
        self.watcher = watcher
        self.lock_was_free = False
        self.stopped = False
        self._alive = True

    def stop(self) -> None:
        # Would block in watchdog; record whether the watcher still held _lock.
        self.lock_was_free = self.watcher._lock.acquire(blocking=False)
        if self.lock_was_free:
            self.watcher._lock.release()
        self.stopped = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self._alive = False


@pytest.fixture
def watcher(tmp_path) -> VaultWatcher:
    v = tmp_path / "vault"
    v.mkdir()
    return VaultWatcher(vault_dir=v, db=None, bus=None, cfg=None)


def test_stop_does_not_hold_the_lock_inside_watchdog(watcher) -> None:
    """The deadlock's root cause, asserted without racing threads.

    Swaps in a *non-reentrant* lock: the production `_lock` is an RLock, and
    `RLock.acquire(blocking=False)` succeeds for the thread already holding it,
    so the check would pass vacuously.
    """
    watcher._lock = threading.Lock()  # type: ignore[assignment]
    obs = _FakeObserver(watcher)
    watcher._observer = obs  # type: ignore[assignment]

    watcher.stop()

    assert obs.stopped, "observer.stop() was never called"
    assert obs.lock_was_free, (
        "stop() held _lock while calling observer.stop() — the observer thread "
        "needs that lock to finish dispatching, so shutdown deadlocks"
    )


def test_stop_releases_the_lock_afterwards(watcher) -> None:
    watcher._observer = _FakeObserver(watcher)  # type: ignore[assignment]
    watcher.stop()
    acquired = watcher._lock.acquire(timeout=1.0)
    assert acquired, "stop() leaked the lock"
    if acquired:
        watcher._lock.release()


def test_stop_clears_pending_timers(watcher) -> None:
    fired = []
    timers = []
    for i in range(3):
        t = threading.Timer(30.0, lambda: fired.append(i))
        t.daemon = True
        timers.append(t)
        watcher._timers[f"/vault/n{i}.md"] = t
        t.start()

    watcher.stop()

    assert watcher._timers == {}, "pending debounce timers were not cancelled"
    for t in timers:
        t.join(timeout=0.1)
    assert not fired, "a cancelled timer still fired"


def test_stop_without_an_observer_is_a_noop(watcher) -> None:
    watcher.stop()  # must not raise
    assert watcher._observer is None


def test_stop_is_idempotent(watcher) -> None:
    watcher._observer = _FakeObserver(watcher)  # type: ignore[assignment]
    watcher.stop()
    watcher.stop()  # must not raise


def test_is_running_after_stop_is_false(watcher) -> None:
    watcher._observer = _FakeObserver(watcher)  # type: ignore[assignment]
    assert watcher.is_running() is True
    watcher.stop()
    assert watcher.is_running() is False


def test_stop_survives_an_observer_that_raises(watcher) -> None:
    class Exploding(_FakeObserver):
        def stop(self) -> None:
            raise RuntimeError("inotify exploded")

    watcher._observer = Exploding(watcher)  # type: ignore[assignment]
    watcher.stop()  # must not propagate


def test_observer_thread_can_finish_an_event_during_stop(watcher) -> None:
    """The real deadlock, reproduced with real threads.

    The observer thread is parked inside `_schedule_debounce` waiting for the
    lock when `stop()` runs. Before the fix this never completes.
    """
    vault = Path(watcher.vault_dir)
    (vault / "note.md").write_text("# hi\n")

    inside = threading.Event()
    proceed = threading.Event()
    original = watcher._lock

    class SlowLock:
        """Wraps the RLock so we can hold it and observe the observer thread."""

        def __init__(self) -> None:
            self._r = threading.RLock()

        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            return self._r.acquire(blocking, timeout)

        def release(self) -> None:
            self._r.release()

        def __enter__(self):
            self._r.acquire()
            return self

        def __exit__(self, *a):
            self._r.release()

    watcher._lock = SlowLock()  # type: ignore[assignment]
    watcher.debounce_secs = 0.01

    done = threading.Thread(target=watcher._handle_raw_event, args=(str(vault / "note.md"),))
    # Hold the lock so the observer thread blocks inside _schedule_debounce.
    original.acquire()
    done.start()
    inside.set()
    proceed.set()

    # Let the observer thread reach the lock, then release and stop.
    original.release()
    done.join(timeout=2.0)
    assert not done.is_alive(), "observer thread never finished the event"

    watcher.stop()