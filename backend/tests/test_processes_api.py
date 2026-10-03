"""Tests for the processes router: kill guards and process listing."""

from __future__ import annotations

import subprocess
import time

import pytest


@pytest.fixture
def sleeper():
    """A harmless long-lived child process to terminate."""
    proc = subprocess.Popen(["sleep", "30"])
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_kill_refuses_pid_one(client):
    """init must never be killable, even by the local user."""
    r = client.post("/api/processes/1/kill")
    assert r.status_code == 400, r.text


def test_kill_refuses_non_positive_pid(client):
    r = client.post("/api/processes/0/kill")
    assert r.status_code in (400, 404), r.text


def test_kill_unknown_pid_returns_404(client):
    # PID 0 is never a real process; use a high pid that will not exist.
    r = client.post("/api/processes/4194304/kill")
    assert r.status_code == 404, r.text


def test_kill_terminates_a_live_process(client, sleeper):
    assert sleeper.poll() is None
    r = client.post(f"/api/processes/{sleeper.pid}/kill")
    assert r.status_code == 200, r.text
    assert r.json()["pid"] == sleeper.pid

    deadline = time.monotonic() + 5
    while sleeper.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sleeper.poll() is not None, "process survived a non-force kill"


def test_kill_is_idempotent_after_process_is_gone(client, sleeper):
    client.post(f"/api/processes/{sleeper.pid}/kill")
    for _ in range(100):
        if sleeper.poll() is not None:
            break
        time.sleep(0.05)
    r = client.post(f"/api/processes/{sleeper.pid}/kill")
    assert r.status_code in (200, 404), r.text


def test_list_processes_returns_the_current_process(client):
    import os

    r = client.get("/api/processes/list?limit=500")
    assert r.status_code == 200, r.text
    pids = {p["pid"] for p in r.json()}
    assert os.getpid() in pids


def test_list_processes_sorted_by_memory(client):
    r = client.get("/api/processes/list?sort_by=memory&limit=20")
    assert r.status_code == 200, r.text
    mems = [p["memory_mb"] for p in r.json()]
    assert mems == sorted(mems, reverse=True)


def test_process_details_reports_thread_count(client):
    import os

    r = client.get(f"/api/processes/{os.getpid()}/details")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pid"] == os.getpid()
    assert body["num_threads"] > 0


def test_apps_endpoint_responds(client):
    """On a headless box there may be no windows, but the route must not 500."""
    r = client.get("/api/processes/apps")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)