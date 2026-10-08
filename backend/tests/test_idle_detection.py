"""#60 real idle detection via logind's IdleHint.

`ext-idle-notify` is an X11 protocol; on Wayland there is no equivalent a
plain client can subscribe to. logind *does* publish the compositor/session's
own idle verdict on the user bus (`IdleHint`, `IdleSinceHint`), so that is the
signal used here — it is the session manager's answer, not a cursor guess.

Everything degrades to the cursor heuristic when the bus is unavailable
(a container, a non-systemd host), because a tracker that stops tracking is
worse than one that is slightly wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fleeting.activity import ActivityCollector, parse_idle_hint, session_idle
from fleeting.config import ActivityConfig

NOW = datetime(2026, 10, 8, 9, 0, 0)


class FakeDB:
    def __init__(self):
        self.rows: list[dict] = []
        self.store: dict[str, str] = {}

    def upsert_activity(self, row):
        if row.get("id") is not None:
            self.rows[row["id"]] = dict(row)
            return row["id"]
        r = dict(row)
        r["id"] = len(self.rows)
        self.rows.append(r)
        return r["id"]

    def activity_sessions(self, day):
        return [dict(r) for r in self.rows if r.get("day") == day]

    def kv_get(self, key, default=None):
        return self.store.get(key, default)

    def kv_set(self, key, value):
        self.store[key] = value

    def app_rules(self):
        return {}

    def app_aliases(self):
        return {}

    def app_idle_rules(self):
        return {}


def _collector(**cfg_kwargs) -> tuple[ActivityCollector, FakeDB]:
    cfg_kwargs.setdefault("idle_source", "logind")
    cfg = ActivityConfig(poll_secs=20, idle_after_min=3, auto_daily_log=False, **cfg_kwargs)
    db = FakeDB()
    return ActivityCollector(db, cfg, probe=lambda: (None, None)), db


def test_idle_hint_true_and_false_are_parsed() -> None:
    assert parse_idle_hint("s \"true\"\n") is True
    assert parse_idle_hint("s \"false\"\n") is False
    assert parse_idle_hint("garbage") is None
    assert parse_idle_hint("") is None


def test_idle_since_hint_parses_to_a_timestamp() -> None:
    hint = parse_idle_hint('t 1759916400000000 0')
    assert hint is not None
    assert hint.tzinfo is not None


def test_the_collector_uses_the_hint_over_the_cursor() -> None:
    """A moving cursor does not make a person who walked away present."""
    col, db = _collector()
    col._idle_hint = lambda: (True, NOW)  # type: ignore[method-assign]
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW)
    col.poll_once({"class": "kitty", "title": "vim"}, (900, 900), NOW + timedelta(seconds=20))

    row = db.rows[0]
    assert row["seconds"] == 0
    assert row["idle_secs"] == 20


def test_the_collector_accrues_again_when_the_hint_clears() -> None:
    col, db = _collector()
    col._idle_hint = lambda: (False, None)  # type: ignore[method-assign]
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW)
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW + timedelta(seconds=20))
    assert db.rows[0]["seconds"] == 20
    assert db.rows[0]["idle_secs"] == 0


def test_an_unavailable_bus_falls_back_to_the_cursor() -> None:
    col, db = _collector(idle_source="cursor")
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW)
    for i in range(1, 12):
        col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW + timedelta(seconds=20 * i))
    assert db.rows[0]["seconds"] == 160  # cursor heuristic, as before
    assert db.rows[0]["idle_secs"] == 60


def test_the_probe_reports_why_it_fell_back() -> None:
    col, _db = _collector()
    col._bus_call = lambda args: (_ for _ in ()).throw(FileNotFoundError("busctl"))  # type: ignore[method-assign]
    assert col._idle_hint() == (None, None)


def test_a_malformed_property_read_is_not_an_idle_verdict() -> None:
    col, db = _collector()
    col._bus_call = lambda args: "not-a-property-value\n"  # type: ignore[method-assign]
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW)
    col.poll_once({"class": "kitty", "title": "vim"}, (1, 1), NOW + timedelta(seconds=20))
    assert db.rows[0]["seconds"] == 20  # treated as "not idle", and kept tracking


def test_session_idle_helper_is_pure() -> None:
    since = datetime(2026, 10, 8, 8, 0, tzinfo=NOW.tzinfo)
    epoch = datetime(1970, 1, 1, tzinfo=NOW.tzinfo)
    # logind wins over the cursor, both ways
    assert session_idle((True, since), 0, 180) is True
    assert session_idle((False, None), 600, 180) is False
    # an idle timestamp alone still means idle
    assert session_idle((None, since), 0, 180) is True
    # no answer at all → the cursor streak decides
    assert session_idle((None, None), 60, 180) is False
    assert session_idle((None, epoch), 600, 180) is True  # cursor streak wins

def test_settings_report_and_accept_the_idle_source(client) -> None:
    s = client.get("/api/settings").json()
    assert s["activity_idle_source"] == "auto"
    assert isinstance(s["activity_idle_available"], bool)

    assert client.put("/api/settings", json={"activity_idle_source": "cursor"}).status_code == 200
    assert client.get("/api/settings").json()["activity_idle_source"] == "cursor"
    assert client.put("/api/settings", json={"activity_idle_source": "telepathy"}).status_code == 422
