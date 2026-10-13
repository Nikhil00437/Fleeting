"""#141: the egress self-check.

Two things are under test, and they are easy to confuse:

1. **It probes.** It opens a connection and reports whether something answered.
   That is the whole difference from `GET /api/offline` (#460), which only reads
   the config. A test that passes with every probe stubbed proves nothing about
   probing, so the probe is exercised against a real listening socket — the
   cheapest possible proof that the check does what it says.
2. **It fails safely.** No endpoint configured, an unreachable host, a
   nonsensical URL, an exception in the middle of the pool — all produce a
   result, never a 500. A privacy status page that errors is the one thing worse
   than not having one.

The "sends nothing" claim is pinned too. This tool exists to answer "does this
leave my machine", so it had better be true that it does not send a request — the
property is asserted on the bytes that cross the wire, not on the docstring.
"""

from __future__ import annotations

import json
import socket
import threading

import pytest

from fleeting.services import egress


@pytest.fixture()
def listener():
    """A real socket that accepts connections, bound to an ephemeral port."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def _accept() -> None:
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except (socket.timeout, OSError):
                continue
            conn.close()

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    stop.set()
    thread.join(timeout=2)
    srv.close()


# ---- it really probes -----------------------------------------------------


def test_a_listening_host_is_reported_reachable(listener) -> None:
    """Not a stubbed probe: a real connection to a real socket."""
    result = egress._probe(listener)
    assert result["reachable"] is True


def test_a_closed_port_is_reported_unreachable() -> None:
    """A port nothing is listening on, chosen by binding then releasing it."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    assert egress._probe(f"http://127.0.0.1:{port}")["reachable"] is False


def test_the_probe_sends_no_request(listener) -> None:
    """This tool answers "does anything leave my machine". If it sent a request,
    it would be the thing leaving."""
    seen: list[bytes] = []
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = srv.getsockname()[1]

    def _accept() -> None:
        srv.settimeout(1.0)
        try:
            conn, _ = srv.accept()
            conn.settimeout(0.5)
            try:
                seen.append(conn.recv(4096))
            except (socket.timeout, OSError):
                pass
            conn.close()
        except (socket.timeout, OSError):
            pass

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    egress._probe(f"http://127.0.0.1:{port}")
    thread.join(timeout=2)
    srv.close()
    assert seen == [b""]  # a connection, then EOF — no bytes of our own


def test_the_result_names_what_it_talked_to(listener) -> None:
    result = egress._probe(listener)
    assert "127.0.0.1" in result["detail"]


# ---- it cannot fail -------------------------------------------------------


def test_an_unusable_url_is_not_an_error() -> None:
    assert egress._probe("")["reachable"] is None


def test_a_url_with_no_host_is_not_an_error() -> None:
    assert egress._probe("https://")["reachable"] is None


def test_an_exception_in_the_probe_becomes_a_result(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("something unexpected")

    monkeypatch.setattr(egress.socket, "create_connection", boom)
    result = egress._probe("https://example.invalid")
    assert result["reachable"] is False
    assert "something unexpected" in result["detail"]


def test_port_defaults_by_scheme() -> None:
    assert egress._target("https://example.invalid") == ("example.invalid", 443)
    assert egress._target("http://example.invalid") == ("example.invalid", 80)
    assert egress._target("example.invalid") == ("example.invalid", 443)


def test_an_explicit_port_wins() -> None:
    assert egress._target("https://example.invalid:8443") == ("example.invalid", 8443)


# ---- the whole check ------------------------------------------------------


def test_nothing_configured_probes_nothing() -> None:
    """No endpoints means no outbound connection at all — the strongest answer
    the page can give.

    The base URL is cleared explicitly: the shipped default points at a local
    Ollama on `127.0.0.1:11434`, so a bare `Config()` is not the empty case and
    this test would silently be probing the developer's own machine.
    """
    from fleeting.config import Config

    cfg = Config()
    cfg.llm.base_url = ""
    cfg.llm.embedding_base_url = ""
    body = egress.self_check(cfg)
    assert body["probed"] == []
    assert body["reachable"] == []
    assert "Nothing was probed" in body["detail"]


def test_duplicate_urls_are_probed_once(client) -> None:
    """The same provider behind two features should not be probed twice: slower
    for no extra information.
    """
    client.put(
        "/api/settings",
        json={"llm_base_url": "http://example.invalid:9", "llm_embedding_base_url": "http://example.invalid:9"},
    )
    body = client.get("/api/egress").json()
    assert body["probed"], "expected the configured endpoint to be probed"
    assert len(body["probed"]) == len({p["url"] for p in body["probed"]})


def test_an_unreachable_endpoint_reports_rather_than_hangs(client) -> None:
    """A blackholed host must produce an answer, not make the page hang.

    Bound by the connect timeout, not by waiting to be sure: "did not answer" is
    the answer, and a status page that times out is indistinguishable from one
    that is broken.
    """
    client.put("/api/settings", json={"llm_base_url": "http://example.invalid:9"})
    probe = next(
        (p for p in client.get("/api/egress").json()["probed"] if "example.invalid" in p["url"]),
        None,
    )
    assert probe is not None
    assert probe["reachable"] is False
    assert "did not answer" in probe["detail"]


def test_the_endpoint_states_that_nothing_is_sent(client) -> None:
    """An egress page that does not say what it sends is asking for trust it has
    not earned."""
    body = client.get("/api/egress").json()
    assert "TCP" in body["sends"]
    assert "no request" in body["sends"]


def test_the_endpoint_lists_configured_remote_features(client) -> None:
    """YouTube transcription is remote by default, which makes it the reliable
    thing to assert on — an `llm_provider` PUT needs credentials to stick and
    would make this test depend on that validation."""
    assert "youtube" in client.get("/api/egress").json()["configured_remote"]


def test_a_local_feature_is_not_listed_as_remote(client) -> None:
    assert "activity" not in client.get("/api/egress").json()["configured_remote"]


def test_the_endpoint_survives_a_broken_config_report(client, monkeypatch) -> None:
    """A privacy status page that 500s tells you nothing about your privacy,
    which is the one thing it exists to tell you."""
    monkeypatch.setattr(egress, "report", lambda cfg: (_ for _ in ()).throw(RuntimeError("boom")))
    body = client.get("/api/egress").json()
    assert body["offline"] is False
    assert "boom" in json.dumps(body)

def test_the_embedding_endpoint_is_probed_too(client) -> None:
    """Embeddings are a separate egress path. Leaving it unprobed would report
    "no network" for a machine that is in fact sending every capture to a remote
    embedding endpoint."""
    client.put("/api/settings", json={"llm_embedding_base_url": "http://example.invalid:9"})
    urls = [p["url"] for p in client.get("/api/egress").json()["probed"]]
    assert "http://example.invalid:9" in urls
