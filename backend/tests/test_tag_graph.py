"""#249 tag co-occurrence matrix and topic-over-time stream chart tests."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from fleeting.db import Database
from fleeting.services.tag_graph import get_tag_cooccurrence_and_stream


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_tg.db")
    database.migrate()
    return database


def test_tag_graph_empty(db: Database) -> None:
    res = get_tag_cooccurrence_and_stream(db)
    assert res["top_tags"] == []
    assert res["matrix"] == []
    assert res["pairs"] == []
    assert res["total_tagged_notes"] == 0


def test_tag_graph_with_notes(db: Database) -> None:
    # Note 1: python, fastapi, sqlite
    db.insert_note({
        "type": "text",
        "title": "Backend stack",
        "raw_text": "text",
        "tags": json.dumps(["python", "fastapi", "sqlite"]),
        "created_at": "2026-10-08T10:00:00Z",
    })
    # Note 2: python, fastapi
    db.insert_note({
        "type": "text",
        "title": "API design",
        "raw_text": "text",
        "tags": json.dumps(["python", "fastapi"]),
        "created_at": "2026-10-08T11:00:00Z",
    })
    # Note 3: sqlite, database
    db.insert_note({
        "type": "text",
        "title": "DB schema",
        "raw_text": "text",
        "tags": json.dumps(["sqlite", "database"]),
        "created_at": "2026-10-08T12:00:00Z",
    })

    res = get_tag_cooccurrence_and_stream(db, top_n=4, weeks=4)
    tags = [t["tag"] for t in res["top_tags"]]
    assert "python" in tags
    assert "fastapi" in tags
    assert "sqlite" in tags

    py_idx = tags.index("python")
    fa_idx = tags.index("fastapi")
    sq_idx = tags.index("sqlite")

    # Matrix checks
    assert res["matrix"][py_idx][py_idx] == 2  # python appears in 2 notes
    assert res["matrix"][py_idx][fa_idx] == 2  # python + fastapi appear together in 2 notes
    assert res["matrix"][fa_idx][py_idx] == 2  # symmetric
    assert res["matrix"][py_idx][sq_idx] == 1  # python + sqlite appear in 1 note

    # Pairs
    py_fa_pair = next(p for p in res["pairs"] if (p["tag_a"], p["tag_b"]) in [("python", "fastapi"), ("fastapi", "python")])
    assert py_fa_pair["count"] == 2

    # Stream checks
    assert len(res["weeks"]) == 4
    assert len(res["stream"]) == len(tags)


def test_tag_graph_api(client) -> None:
    resp = client.get("/api/stats/tag-graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "matrix" in data
    assert "stream" in data
