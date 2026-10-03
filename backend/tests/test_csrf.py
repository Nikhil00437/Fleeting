"""Cross-origin request guard for mutating /api endpoints.

A browser attaches Origin to cross-origin POSTs even when the attacker cannot
read the response, so CORS alone does not stop a hostile page from firing
side-effecting requests at the loopback server. These tests pin the guard.
"""

from __future__ import annotations

import pytest

FOREIGN = "http://evil.example"
SELF = "http://127.0.0.1:7425"


@pytest.fixture
def note_id(client) -> str:
    r = client.post("/api/capture/text", json={"text": "csrf fixture"})
    assert r.status_code == 200, r.text
    nid = r.json()["id"]
    # let the worker finish so the note is in a normal, mutable state
    for _ in range(100):
        if client.get(f"/api/notes/{nid}").json()["status"] in ("done", "failed"):
            break
    return nid


@pytest.mark.parametrize(
    ("method", "path_factory"),
    [
        ("POST", lambda nid: f"/api/notes/{nid}/pin"),
        ("POST", lambda nid: f"/api/notes/{nid}/archive"),
        ("PATCH", lambda nid: f"/api/notes/{nid}"),
        ("DELETE", lambda nid: f"/api/notes/{nid}"),
    ],
)
def test_mutating_api_rejects_foreign_origin(client, note_id, method, path_factory):
    r = client.request(method, path_factory(note_id), json={"title": "x"}, headers={"Origin": FOREIGN})
    assert r.status_code == 403, f"{method} accepted a cross-origin request: {r.text}"


def test_mutating_api_allows_missing_origin(client, note_id):
    """No Origin header means a non-browser client (curl, the flee CLI)."""
    r = client.post(f"/api/notes/{note_id}/pin")
    assert r.status_code == 200, r.text


def test_mutating_api_allows_own_origin(client, note_id):
    r = client.post(f"/api/notes/{note_id}/pin", headers={"Origin": SELF})
    assert r.status_code == 200, r.text


def test_mutating_api_allows_vite_dev_origin(client, note_id):
    """The Vite dev server proxies from a different port during development."""
    r = client.post(f"/api/notes/{note_id}/pin", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200, r.text


def test_reads_ignore_foreign_origin(client, note_id):
    """Reads are not side-effecting; CORS already blocks reading the response."""
    r = client.get(f"/api/notes/{note_id}", headers={"Origin": FOREIGN})
    assert r.status_code == 200, r.text


def test_error_body_does_not_echo_attacker_input(client, note_id):
    r = client.post(f"/api/notes/{note_id}/pin", headers={"Origin": FOREIGN})
    assert FOREIGN not in r.text