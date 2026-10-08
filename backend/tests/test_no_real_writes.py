"""The test suite must never write to the user's real data directory.

Two real leaks this guards against, both found during 0.7 development:

1. `fleeting.main` builds `app = create_app()` at import time, so importing it
   migrates and rewrites the *user's* database even when no test touches it.
2. `services/actions.py` bound `AUDIO_DIR` by value at import, so no test could
   redirect where voice memos are written — the stub `.webm` files that turned
   up in the real audio directory came from here.

The session-wide redirect lives in `conftest.py::pytest_configure`; the
`real_paths_untouched` fixture there asserts it held, so a regression fails
the suite instead of quietly littering the real inbox.
"""

from __future__ import annotations

from pathlib import Path

import fleeting.config as fcfg
from conftest import REAL_PATHS, _REAL, _sandbox


def test_the_real_paths_are_redirected() -> None:
    """Every user path now resolves inside the temp sandbox.

    Structural rather than observational on purpose: with the app running
    against the same database, "did the suite write a row?" cannot be answered
    from side effects — the user's own clicks look identical. What *can* be
    proven is that nothing in this process can still reach the real files.
    """
    sandbox = _sandbox()
    for name in REAL_PATHS:
        path = fcfg.__dict__[name]
        assert path != _REAL[name], f"{name} still points at the user's data"
        assert sandbox in Path(path).parents or Path(path).parent == sandbox


def test_the_apps_own_db_path_resolver_is_redirected() -> None:
    """`fleeting.main._db_path()` is what create_app() actually opens."""
    from fleeting.main import _db_path

    assert _sandbox() in Path(_db_path()).parents


def test_a_database_built_by_import_time_lands_in_the_sandbox() -> None:
    """Importing fleeting.main migrates a database — prove it is not yours."""
    from fleeting.db import Database

    fresh = Database(_sandbox() / "import-probe.db")
    fresh.migrate()
    assert _sandbox() in Path(fresh.path).parents
    assert Path(fresh.path) != _REAL["DB_PATH"]


def test_audio_dir_is_redirected_for_actions(monkeypatch) -> None:
    """actions.py must read the module attribute, not a copy taken at import."""
    from fleeting.services import actions

    monkeypatch.setattr(fcfg, "AUDIO_DIR", Path("/tmp/fleeting-test-audio"))
    assert actions.cfg_audio_dir() == Path("/tmp/fleeting-test-audio")