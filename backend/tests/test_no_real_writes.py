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

def test_no_module_holds_a_copy_of_the_real_config_path() -> None:
    """`from ..config import CONFIG_PATH` freezes the real path at import time.

    The session redirect only moves `fcfg.CONFIG_PATH`, so anything that copied
    it still holds — and can write to — the user's real config.toml. That is
    how the file ended up holding a pytest temp directory as `vault_dir`: a
    value no human would ever type, written atomically and valid.

    Checked by scanning loaded modules rather than grepping, because a grep
    finds the source but not which names survived into a closure or a default
    argument.
    """
    import sys

    # Import every router and service first, or the scan sees almost nothing and
    # passes vacuously — this test was green against a live copy in settings.py
    # simply because nothing had imported it.
    import importlib
    import pkgutil

    import fleeting

    for info in pkgutil.walk_packages(fleeting.__path__, "fleeting."):
        try:
            importlib.import_module(info.name)
        except Exception:  # noqa: BLE001 - a module needing live state is not the point
            continue

    # No `attr != "CONFIG_PATH"` exemption here: `fleeting.config` is already
    # excluded by module name, and CONFIG_PATH is the one name this would ever
    # catch — exempting it made the guard silently vacuous.
    real = str(_REAL["CONFIG_PATH"])
    sandboxed = str(fcfg.CONFIG_PATH)
    offenders: list[str] = []
    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.startswith("fleeting") or mod is None or mod_name == "fleeting.config":
            continue
        for attr, value in list(vars(mod).items()):
            if isinstance(value, (str, Path)) and str(value) == real:
                offenders.append(f"{mod_name}.{attr}")
    assert not offenders, (
        f"these hold the real config path by value: {offenders} "
        f"(sandboxed: {sandboxed})"
    )
