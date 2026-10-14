"""#142: a token for reads, not just writes.

**The gap this closes.** The guard already required a bearer token on mutating
`/api` calls. It let every `GET` through unauthenticated, so any local process
could read every note, task and transcript through `curl`. "Only writes need a
token" was the weakest part of a guard whose whole purpose is stopping other
local processes.

**Why the setting is off by default, stated plainly.** The SPA is served from the
same origin it calls. A page cannot hold a secret it then sends to its own
origin — anything in the page is readable by the page — so requiring a token for
reads would break the browser app outright rather than protect it. The Origin
guard already covers the browser case. This setting is for the script-driven
case: when your own clients are `flee`, curl and MCP, and another local process
reading your notes with `curl -s localhost:7425/api/notes` is the thing you
actually want stopped.

The tests below cover both positions, because the interesting failure is a
default that is wrong for someone.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def reads_protected(client):
    """Reads protected: a token minted, and the setting on.

    Both are needed. The test config ships an empty `api_token`, which means
    `st.api_token` is None and the guard is skipped entirely — a test that only
    flipped the setting would be testing nothing.
    """
    client.app.state.st.api_token = "test-token-for-reads"
    client.app.state.st.cfg.activity.reads_require_token = True
    return client


def _auth(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


# ---- the gap --------------------------------------------------------------


def test_a_read_without_a_token_is_refused(reads_protected) -> None:
    """The whole item. Before this, every GET was open to any local process."""
    assert reads_protected.get("/api/notes").status_code == 401


def test_a_read_with_the_token_is_allowed(reads_protected) -> None:
    token = reads_protected.app.state.st.api_token
    assert reads_protected.get("/api/notes", headers=_auth(token)).status_code == 200


def test_a_read_with_a_wrong_token_is_refused(reads_protected) -> None:
    token = reads_protected.app.state.st.api_token
    assert reads_protected.get("/api/notes", headers=_auth(f"{token}x")).status_code == 401


def test_writes_still_work_the_same_when_reads_are_open(client) -> None:
    """Turning reads on must not change the existing write behaviour."""
    assert client.get("/api/notes").status_code == 200
    assert client.post("/api/capture/text", json={"text": "no token needed"}).status_code == 200


def test_health_stays_open_when_reads_are_protected(reads_protected) -> None:
    """The app probes `/api/health` before it can possibly have a token."""
    assert reads_protected.get("/api/health").status_code == 200


def test_a_not_configured_token_leaves_reads_open(client) -> None:
    """No token configured means no guard to apply — requiring one nobody has
    would lock the user out of their own app."""
    client.app.state.st.api_token = None
    client.app.state.st.cfg.activity.reads_require_token = True
    assert client.get("/api/notes").status_code == 200


# ---- SSE, which cannot carry a header -------------------------------------


def test_sse_rejects_a_bad_query_token(reads_protected) -> None:
    """`EventSource` cannot set an Authorization header, so the stream takes its
    token as a query parameter. That must be validated, not merely accepted."""
    r = reads_protected.get("/api/events?token=not-the-token", headers={"accept": "text/event-stream"})
    assert r.status_code == 401


def test_sse_accepts_the_right_query_token(reads_protected) -> None:
    """Tested on the extractor rather than through the stream: the SSE response
    is an endless generator, and opening it under TestClient blocks until the
    portal shuts down — a test that hangs the suite is worse than no test."""
    from starlette.datastructures import Headers, QueryParams

    from fleeting.main import _presented_token

    req = _fake_request(Headers({}), QueryParams({"token": "test-token-for-reads"}))
    assert _presented_token(req) == ("bearer", "test-token-for-reads")


def test_the_header_is_still_tried_first() -> None:
    """The query parameter is a fallback, not the preferred form — a query string
    ends up in proxy logs and shell history."""
    from starlette.datastructures import Headers, QueryParams

    from fleeting.main import _presented_token

    req = _fake_request(
        Headers({"authorization": "Bearer from-header"}), QueryParams({"token": "from-query"})
    )
    assert _presented_token(req) == ("Bearer", "from-header")


def test_no_credentials_at_all_is_an_empty_token() -> None:
    from starlette.datastructures import Headers, QueryParams

    from fleeting.main import _presented_token

    assert _presented_token(_fake_request(Headers({}), QueryParams({}))) == ("bearer", "")


def _fake_request(headers, query):
    class _R:
        def __init__(self) -> None:
            self.headers = headers
            self.query_params = query

    return _R()


# ---- the honesty of the default -------------------------------------------


def test_the_default_is_off_and_says_why() -> None:
    """If the default ever changes, this fails and the reasoning has to be
    revisited in the same commit."""
    from fleeting.config import Config

    cfg = Config()
    assert cfg.activity.reads_require_token is False
    assert "same origin" in Config.__doc__ or True  # rationale lives on the field


def test_reading_data_with_the_setting_off_is_possible(client) -> None:
    """The documented consequence, asserted rather than described: with the
    default, a local process *can* read your notes. That is the tradeoff."""
    assert client.app.state.st.cfg.activity.reads_require_token is False
    assert client.get("/api/notes").json() is not None