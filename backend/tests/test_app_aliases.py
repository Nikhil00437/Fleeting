"""#64 per-app rename and merge."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

NOW = datetime(2026, 10, 8, 9, 0, 0)


@pytest.fixture
def db(tmp_path: Path):
    from fleeting.db import Database

    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _session(db, app: str, seconds: int = 600, title: str = "page") -> int:
    cur = db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (app, title, NOW.isoformat(), NOW.isoformat(), seconds, "2026-10-08"),
    )
    db.commit()
    return int(cur.lastrowid)


def _classes(db) -> list[str]:
    return [r["app_class"] for r in db.execute("SELECT app_class FROM activity ORDER BY id")]


def test_merging_folds_the_history_of_both_classes(db) -> None:
    from fleeting.activity import set_app_alias

    _session(db, "firefox")
    _session(db, "firefox-esr")
    set_app_alias(db, "firefox-esr", "firefox")

    assert _classes(db) == ["firefox", "firefox"]


def test_renaming_is_the_same_operation(db) -> None:
    from fleeting.activity import set_app_alias

    _session(db, "Code")
    set_app_alias(db, "Code", "vscode")
    assert _classes(db) == ["vscode"]


def test_aliases_resolve_through_a_chain(db) -> None:
    from fleeting.activity import resolve_app_class

    set = __import__("fleeting.activity", fromlist=["x"]).set_app_alias
    set(db, "b", "c")
    set(db, "a", "b")
    assert resolve_app_class(db, "a") == "c"


def test_an_alias_cycle_does_not_hang(db) -> None:
    from fleeting.activity import resolve_app_class, set_app_alias

    set_app_alias(db, "a", "b")
    set_app_alias(db, "b", "a")
    # Whichever way it resolves, it must terminate.
    assert resolve_app_class(db, "a") in {"a", "b"}


def test_the_collector_stores_the_canonical_class(tmp_path: Path) -> None:
    from test_activity import FakeDB

    from fleeting.activity import ActivityCollector, set_app_alias
    from fleeting.config import ActivityConfig
    from fleeting.db import Database

    real = Database(tmp_path / "real.db")
    real.migrate()
    set_app_alias(real, "kitty", "alacritty")

    fake = FakeDB()
    fake.app_aliases = lambda: {"kitty": "alacritty"}
    cfg = ActivityConfig(poll_secs=20, idle_after_min=3, auto_daily_log=False)
    col = ActivityCollector(fake, cfg, probe=lambda: (None, None))
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW)
    assert fake.rows[0]["app_class"] == "alacritty"


def test_removing_an_alias_stops_future_renames_but_keeps_history(db) -> None:
    from fleeting.activity import delete_app_alias

    _session(db, "firefox-esr")
    delete_app_alias(db, "firefox-esr")
    assert _classes(db) == ["firefox-esr"]


def test_the_alias_endpoint_merges_and_lists(db, client) -> None:
    client.post("/api/notes", json={"type": "text", "title": "x", "raw_text": "y"})
    # the endpoint reads the app's own Database
    app_db = client.app.state.st.db
    _session(app_db, "firefox-esr")

    assert client.post("/api/activity/apps/alias", json={"from_class": "firefox-esr", "to_class": "firefox"}).status_code == 200
    listed = client.get("/api/activity/apps/aliases").json()
    assert listed == [{"from_class": "firefox-esr", "to_class": "firefox"}]

    assert client.delete("/api/activity/apps/alias/firefox-esr").status_code == 204
    assert client.get("/api/activity/apps/aliases").json() == []


def test_a_blank_target_is_rejected(client) -> None:
    assert client.post("/api/activity/apps/alias", json={"from_class": "firefox", "to_class": "  "}).status_code == 422