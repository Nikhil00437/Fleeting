"""#458: read-only demo mode.

The property is simple to state and easy to get wrong: **in demo mode, no write
reaches the database.** The subtle part is *how* it is enforced. A guard each
route has to remember to check is a guard the next endpoint forgets — and the
failure is invisible, because a demo that quietly wrote to the data it is
demonstrating looks exactly like a demo that worked, right up until someone
finds the fake note sitting among their real ones.

So the tests here assert the boundary rather than the feature list:

- every mutating verb is refused, including ones no demo endpoint uses;
- the guard is not per-route, so it catches an endpoint that does not know it
  exists;
- seeding only touches an *empty* database — switching the flag on over real
  data must not quietly add a fortnight of fake notes next to your own;
- the failure names the mode, because "403" with no explanation is a support
  question rather than an answer.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def demo(client, monkeypatch):
    """Demo mode on, after the app has started.

    The flag is flipped on the live app state rather than rebuilding the app:
    the guard reads `cfg.server` per request, and rebuilding would re-run startup
    and seed a second time.
    """
    client.app.state.st.cfg.server.demo_mode = True
    yield client
    client.app.state.st.cfg.server.demo_mode = False


# ---- the boundary ----------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/capture/text", {"text": "should not stick"}),
        ("put", "/api/settings", {"llm_provider": "openai"}),
        ("delete", "/api/notes/nonexistent", {}),
        ("post", "/api/tasks", {"title": "should not stick"}),
        ("post", "/api/trash/empty", {"confirm": True}),
    ],
)
def test_writes_are_refused(demo, method, path, body) -> None:
    # `httpx.delete` takes no `json`, so DELETE goes through `request`.
    r = demo.request(method.upper(), path, json=body) if method == "delete" else getattr(demo, method)(path, json=body)
    assert r.status_code == 403, f"{method} {path} was not refused"
    assert r.json()["detail"]["error"] == "read_only_demo"


def test_the_refusal_names_the_setting(demo) -> None:
    """A bare 403 is a support question. Saying which setting to turn off is an
    answer."""
    message = demo.post("/api/capture/text", json={"text": "x"}).json()["detail"]["message"]
    assert "demo_mode" in message


def test_nothing_actually_reaches_the_database(demo, client) -> None:
    """The whole item: refused is not the same as ignored-and-written."""
    before = client.get("/api/notes").json()
    demo.post("/api/capture/text", json={"text": "this must not be stored"})
    assert client.get("/api/notes").json() == before


def test_reads_still_work(demo) -> None:
    """A read-only demo that cannot show you anything is not a demo."""
    assert demo.get("/api/notes").status_code == 200
    assert demo.get("/api/health").status_code == 200


def test_the_guard_is_not_per_route(demo, client) -> None:
    """A route added after this was written gets the guard for free. This is
    the reason it is middleware rather than a flag on each handler."""
    from fastapi import APIRouter

    router = APIRouter(prefix="/api", tags=["demo-test"])

    @router.post("/demo-route-added-later")
    def _later() -> dict:
        return {"ok": True}

    client.app.include_router(router)
    try:
        assert client.post("/api/demo-route-added-later").status_code == 403
    finally:
        client.app.router.routes = [
            r for r in client.app.router.routes if getattr(r, "path", "") != "/api/demo-route-added-later"
        ]


@pytest.fixture()
def demo_client(tmp_path, monkeypatch):
    """A whole app started in demo mode — the only way to observe startup
    behaviour such as seeding."""
    import fleeting.config as fcfg
    from fastapi.testclient import TestClient

    monkeypatch.setattr(fcfg, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = fcfg.Config()
    cfg.llm.provider = "none"
    cfg.paths.vault_dir = str(tmp_path / "vault")
    cfg.paths.vault_sync = False
    cfg.activity.enabled = False
    cfg.server.demo_mode = True

    from fleeting.main import create_app

    with TestClient(create_app(cfg, load_from_disk=False), base_url=f"http://127.0.0.1:{cfg.server.port}") as c:
        yield c


# ---- seeding ---------------------------------------------------------------


def test_an_empty_demo_database_is_seeded(demo_client) -> None:
    """Built from scratch *with* the flag on.

    Seeding happens at startup, so flipping the flag on a running app cannot
    retroactively seed it — which is exactly the property that keeps real data
    safe, and the reason this test needs its own app.
    """
    assert len(demo_client.get("/api/notes").json()) > 0


def test_seeding_does_not_touch_a_populated_database(client) -> None:
    """Turning the flag on over real data must not add a fortnight of fake notes
    next to your own. That is the one thing a demo may never do."""
    client.post("/api/capture/text", json={"text": "a genuine note"})
    client.app.state.st.cfg.server.demo_mode = True
    try:
        titles = [n.get("raw_text", "") for n in client.get("/api/notes?limit=200").json()]
        assert not any("demo" in str(t).lower() and "genuine" not in str(t).lower() for t in titles)
        assert len(client.get("/api/notes?limit=200").json()) < 100
    finally:
        client.app.state.st.cfg.server.demo_mode = False


def test_a_demo_started_over_real_data_adds_nothing(client, tmp_path, monkeypatch) -> None:
    """The worst case: switching the flag on over a database that already holds
    real notes. A demo that quietly files a fortnight of fake notes among them
    is the one thing this mode exists to prevent.

    Needs its own app because seeding happens at startup — flipping the flag on
    a running app cannot retroactively seed it, which is the other half of the
    same guarantee.
    """
    import fleeting.config as fcfg
    from fastapi.testclient import TestClient

    client.post("/api/capture/text", json={"text": "a genuine note from before the demo"})
    before = {n["id"] for n in client.get("/api/notes?limit=200").json()}

    from fleeting.main import create_app

    cfg = fcfg.Config()
    cfg.llm.provider = "none"
    cfg.paths.vault_dir = str(tmp_path / "vault")
    cfg.paths.vault_sync = False
    cfg.activity.enabled = False
    cfg.server.demo_mode = True
    # Same database file the `client` fixture just wrote to.
    monkeypatch.setattr(fcfg, "DB_PATH", _db_file(client))

    with TestClient(create_app(cfg, load_from_disk=False), base_url=f"http://127.0.0.1:{cfg.server.port}") as demo:
        after = demo.get("/api/notes?limit=200").json()
        assert len(after) == len(before)
        assert {n["id"] for n in after} == before


def _db_file(client):
    """The database the `client` fixture is actually using."""
    from fleeting.main import _db_path

    return _db_path()


# ---- reporting -------------------------------------------------------------


def test_the_mode_is_reported(client) -> None:
    """The UI needs to know, so it can show a banner instead of letting someone
    discover read-only-ness by failing to save."""
    assert client.get("/api/demo").json()["demo_mode"] is False


def test_the_mode_is_reported_when_on(demo) -> None:
    assert demo.get("/api/demo").json()["demo_mode"] is True


def test_the_report_is_readable_in_demo_mode(demo) -> None:
    """A report endpoint that refuses to be read is useless exactly when it is
    needed."""
    assert demo.get("/api/demo").status_code == 200


# ---- off by default --------------------------------------------------------


def test_the_mode_is_off_by_default(client) -> None:
    from fleeting.config import Config

    assert Config().server.demo_mode is False
    assert client.post("/api/capture/text", json={"text": "ordinary capture"}).status_code == 200