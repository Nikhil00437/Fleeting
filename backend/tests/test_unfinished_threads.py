"""#169 Persistent unfinished threads list from reports."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.db import Database
from fleeting.services.unfinished_threads import (
    convert_thread_to_task,
    get_unfinished_threads,
    resolve_thread,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "threads.db")
    database.migrate()
    return database


def test_extract_threads_from_daily_logs(db: Database) -> None:
    # Daily log with Questions for tomorrow and loose ends
    log_content = (
        "# Daily Digest — 2026-10-06\n\n"
        "## Summary\nDid deep work.\n\n"
        "## Questions for tomorrow\n"
        "- Did the security review get signed off?\n"
        "- Need to verify OAuth refresh token expiry.\n"
    )
    db.upsert_daily_log("2026-10-06", log_content, "ollama")

    threads = get_unfinished_threads(db)
    texts = [t["text"] for t in threads]
    assert any("security review" in t for t in texts)
    assert any("OAuth refresh token" in t for t in texts)
    assert all(t["source_day"] == "2026-10-06" for t in threads)


def test_extract_threads_from_stale_carried_over_tasks(db: Database) -> None:
    # An open task created 5 days ago
    t = db.insert_task(
        {
            "text": "Refactor database connection pool",
            "done": False,
            "created_at": "2026-10-01T10:00:00+00:00",
        }
    )

    threads = get_unfinished_threads(db)
    texts = [t["text"] for t in threads]
    assert "Refactor database connection pool" in texts


def test_resolve_thread_persists_across_calls(db: Database) -> None:
    db.upsert_daily_log(
        "2026-10-06",
        "# Digest\n\n## Questions for tomorrow\n- Is CI green?\n",
        "m",
    )
    threads = get_unfinished_threads(db)
    assert len(threads) >= 1
    thread_id = threads[0]["id"]

    resolve_thread(db, thread_id, "resolve")
    remaining = get_unfinished_threads(db)
    assert not any(t["id"] == thread_id for t in remaining)


def test_dismiss_thread_persists_across_calls(db: Database) -> None:
    db.upsert_daily_log(
        "2026-10-06",
        "# Digest\n\n## Questions for tomorrow\n- Stale thread\n",
        "m",
    )
    threads = get_unfinished_threads(db)
    assert len(threads) >= 1
    thread_id = threads[0]["id"]

    resolve_thread(db, thread_id, "dismiss")
    remaining = get_unfinished_threads(db)
    assert not any(t["id"] == thread_id for t in remaining)


def test_convert_thread_to_task(db: Database) -> None:
    db.upsert_daily_log(
        "2026-10-06",
        "# Digest\n\n## Questions for tomorrow\n- Fix audio stutter\n",
        "m",
    )
    threads = get_unfinished_threads(db)
    assert len(threads) >= 1
    thread_id = threads[0]["id"]

    task = convert_thread_to_task(db, thread_id, "Fix audio stutter")
    assert task is not None
    assert task["text"] == "Fix audio stutter"
    assert task["done"] is False

    # Thread should now be resolved
    remaining = get_unfinished_threads(db)
    assert not any(t["id"] == thread_id for t in remaining)


def test_unfinished_threads_api(client) -> None:
    client.app.state.st.db.upsert_daily_log(
        "2026-10-06",
        "# Digest\n\n## Questions for tomorrow\n- Deploy landing page\n",
        "m",
    )
    r = client.get("/api/activity/unfinished-threads")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    thread = data[0]
    assert "Deploy landing page" in thread["text"]

    # Resolve thread
    r_res = client.post(
        "/api/activity/unfinished-threads/resolve",
        json={"thread_id": thread["id"], "action": "resolve"},
    )
    assert r_res.status_code == 200

    # Convert to task
    client.app.state.st.db.upsert_daily_log(
        "2026-10-07",
        "# Digest\n\n## Questions for tomorrow\n- Update readme\n",
        "m",
    )
    data2 = client.get("/api/activity/unfinished-threads").json()
    t2 = next(t for t in data2 if "Update readme" in t["text"])

    r_conv = client.post(
        "/api/activity/unfinished-threads/convert-to-task",
        json={"thread_id": t2["id"], "text": "Update readme"},
    )
    assert r_conv.status_code == 200
    assert r_conv.json()["task"]["text"] == "Update readme"
