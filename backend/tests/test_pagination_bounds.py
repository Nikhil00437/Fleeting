"""Pagination bounds on list endpoints.

A negative LIMIT is not clamped by SQLite — it means "no limit" — so an
unclamped `?limit=-1` returns the entire table. Notes carry full transcripts,
so that is an unbounded response body from an untrusted query param.
"""

from __future__ import annotations

import pytest


def _count(client) -> int:
    return len(client.get("/api/notes?limit=500").json())


@pytest.mark.parametrize("limit", [-1, -100, 0])
def test_notes_limit_rejects_non_positive(client, limit: int) -> None:
    """422, not "here is everything"."""
    for i in range(5):
        client.post("/api/capture/text", json={"text": f"note {i}"})
    assert client.get(f"/api/notes?limit={limit}").status_code == 422


def test_notes_limit_rejects_over_max(client) -> None:
    """422 at both ends, matching /api/tasks and /api/processes."""
    assert client.get("/api/notes?limit=99999").status_code == 422
    assert client.get("/api/notes?limit=500").status_code == 200


def test_notes_offset_rejects_negative(client) -> None:
    assert client.get("/api/notes?offset=-1").status_code == 422


def test_search_limit_rejects_non_positive(client) -> None:
    assert client.get("/api/search?q=a&limit=-1").status_code == 422
    assert client.get("/api/search?q=a&limit=0").status_code == 422


def test_search_limit_rejects_over_max(client) -> None:
    assert client.get("/api/search?q=a&limit=99999").status_code == 422
    assert client.get("/api/search?q=a&limit=200").status_code == 200


def test_pagination_does_not_exceed_seeded_rows(client) -> None:
    """Sanity: a valid small limit returns exactly that many."""
    for i in range(5):
        client.post("/api/capture/text", json={"text": f"note {i}"})
    assert len(client.get("/api/notes?limit=2").json()) == 2
    assert _count(client) >= 5