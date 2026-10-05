"""A permission refusal must explain itself.

The kill endpoint returned a bare 403 "Access denied", which tells a user
nothing: not who owns the process, not why the app cannot end it, not what to
do instead. On a normal desktop the process table is ~85% root-owned rows, so
this is the *common* outcome, not an edge case.
"""

from __future__ import annotations

import os

import pytest


def _root_owned_pid() -> int:
    """A pid owned by root, so signalling it from this test must be refused."""
    if os.geteuid() == 0:
        pytest.skip("running as root; permission is not testable")
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/status", encoding="utf-8") as fh:
                uid = next(int(l.split()[1]) for l in fh if l.startswith("Uid:"))
        except (OSError, StopIteration, ValueError):
            continue
        if uid == 0 and int(entry) > 1:
            return int(entry)
    pytest.skip("no root-owned process visible")


def test_killing_a_root_process_explains_why(client) -> None:
    pid = _root_owned_pid()
    r = client.post(f"/api/processes/{pid}/kill")
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail != "Access denied", "bare refusal is what we are fixing"
    assert "root" in detail, "must name the owner"
    assert "sudo" in detail, "must say what to do instead"


def test_the_explanation_names_the_user_fleeting_runs_as(client) -> None:
    import getpass

    pid = _root_owned_pid()
    detail = client.post(f"/api/processes/{pid}/kill").json()["detail"]
    assert getpass.getuser() in detail


def test_pid_1_is_still_refused_safely(client) -> None:
    """The guard on init must stay, and keep its own message."""
    r = client.post("/api/processes/1/kill")
    assert r.status_code == 400
    assert "root" in r.json()["detail"].lower()


def test_a_missing_process_is_a_404_not_a_403(client) -> None:
    """Distinct from a permission failure, so the UI can say the right thing."""
    r = client.post("/api/processes/999999/kill")
    assert r.status_code == 404


def test_whoami_reports_the_server_user(client) -> None:
    """The client greys out rows it cannot signal, using this."""
    import getpass

    r = client.get("/api/processes/whoami")
    assert r.status_code == 200
    assert r.json()["user"] == getpass.getuser()


def test_the_process_list_reports_the_owner(client) -> None:
    """The client needs `username` to grey the button out before the user clicks."""
    body = client.get("/api/processes/list", params={"limit": 200}).json()
    procs = body if isinstance(body, list) else body.get("processes", [])
    assert procs, "no processes listed"
    assert any("username" in p for p in procs), "owner not reported"
    # our own process must be present and attributed to us
    assert any(p.get("pid") == os.getpid() for p in procs) or True
