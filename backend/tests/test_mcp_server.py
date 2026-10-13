"""#294: an MCP server so other local AI clients can search notes and tasks.

Built on stdlib JSON-RPC over stdio rather than the `mcp` package, which pulls
32 MB of dependencies for a surface that is four methods: `initialize`,
`tools/list`, `tools/call` and one notification. The cost of that choice is
protocol drift, and it is paid for here by keeping the implemented method set
small and explicit — see `MCP_METHODS` in the server.

Read-only is enforced by the *exposed tool surface*, not by the connection:
`Database` opens read-write and the search implementation is already tested, so
re-implementing it against a read-only handle would duplicate query logic to buy
a guarantee the tool list already gives. The test at the end checks that nothing
in the exposed surface can write.
"""

from __future__ import annotations

import json

import pytest

from fleeting.mcp_server import TOOLS, build_response, dispatch
from fleeting.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    d = Database(str(tmp_path / "m.db"))
    d.migrate()
    d.insert_note(
        {
            "id": "n1",
            "title": "Router firmware upgrade failed",
            "raw_text": "The upgrade stopped at 60% and needs a serial recovery.",
            "tags": ["homelab"],
        }
    )
    d.insert_note({"id": "n2", "title": "Unrelated note", "raw_text": "nothing here"})
    d.insert_task({"id": "t1", "text": "Back up the router config", "priority": "P1"})
    d.commit()
    return d


def _req(method: str, params: dict | None = None, _id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}


# ---- the handshake --------------------------------------------------------


def test_initialize_reports_a_protocol_version_and_capabilities(db) -> None:
    out = dispatch(db, _req("initialize", {"protocolVersion": "2024-11-05"}))
    assert out["id"] == 1
    assert out["result"]["protocolVersion"]
    assert out["result"]["capabilities"]["tools"] == {}
    assert out["result"]["serverInfo"]["name"]


def test_tools_list_describes_every_tool(db) -> None:
    out = dispatch(db, _req("tools/list"))
    tools = out["result"]["tools"]
    assert {t["name"] for t in tools} == {t.name for t in TOOLS}
    for tool in tools:
        # A tool with no schema cannot be called by a client that has to guess.
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_an_unknown_method_is_an_error_not_a_crash(db) -> None:
    """A client speaking a newer protocol version must get a clean error."""
    out = dispatch(db, _req("tools/call", {"name": "nope"}))
    # An unknown *tool* is -32602 (invalid params); -32601 is for an unknown
    # *method*. Both matter: a client that sent tools/call wants to know the
    # method exists but the tool does not.
    assert out["error"]["code"] == -32602
    assert dispatch(db, _req("does/not/exist"))["error"]["code"] == -32601


def test_a_notification_gets_no_response(db) -> None:
    """`notifications/initialized` has no id; replying to it desynchronises the
    client, which is a protocol violation rather than a nicety."""
    assert dispatch(db, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping_answers(db) -> None:
    assert dispatch(db, _req("ping"))["result"] == {}


# ---- the tools ------------------------------------------------------------


def test_search_notes_finds_a_note(db) -> None:
    out = dispatch(
        db, _req("tools/call", {"name": "search_notes", "arguments": {"query": "router"}})
    )
    text = out["result"]["content"][0]["text"]
    assert "Router firmware" in text
    assert out["result"]["isError"] is False


def test_search_notes_with_no_match_is_not_an_error(db) -> None:
    """An empty result is an answer, and a client that treats it as a failure
    will not retry a query that was simply fine."""
    out = dispatch(
        db,
        _req("tools/call", {"name": "search_notes", "arguments": {"query": "zzzznothing"}}),
    )
    assert out["result"]["isError"] is False
    assert "no notes" in out["result"]["content"][0]["text"].lower()


def test_search_tasks_finds_a_task(db) -> None:
    out = dispatch(
        db,
        _req("tools/call", {"name": "search_tasks", "arguments": {"query": "router"}}),
    )
    assert "Back up the router" in out["result"]["content"][0]["text"]


def test_a_missing_argument_is_an_error_not_a_crash(db) -> None:
    out = dispatch(db, _req("tools/call", {"name": "search_notes", "arguments": {}}))
    assert out["result"]["isError"] is True
    assert "query" in out["result"]["content"][0]["text"]


def test_get_note_returns_the_note(db) -> None:
    out = dispatch(
        db, _req("tools/call", {"name": "get_note", "arguments": {"id": "n1"}})
    )
    assert "Router firmware" in out["result"]["content"][0]["text"]


def test_get_note_on_a_missing_id_says_so(db) -> None:
    out = dispatch(
        db, _req("tools/call", {"name": "get_note", "arguments": {"id": "nope"}})
    )
    assert out["result"]["isError"] is True


def test_the_limit_is_bounded(tmp_path) -> None:
    """A limit from a model is not a number anyone reasoned about.

    Needs more notes than the cap allows: against the two-note fixture a
    request for a million rows returns two either way, so the assertion passed
    with the cap deleted.
    """
    from fleeting.mcp_server import MAX_LIMIT

    big = Database(str(tmp_path / "big.db"))
    big.migrate()
    for i in range(MAX_LIMIT + 60):
        big.insert_note(
            {"id": f"b{i}", "title": f"bulk note {i}", "raw_text": "matching body"}
        )
    big.commit()

    out = dispatch(
        big,
        _req(
            "tools/call",
            {"name": "search_notes", "arguments": {"query": "matching", "limit": 10**6}},
        ),
    )
    assert out["result"]["isError"] is False
    assert out["result"]["content"][0]["text"].count("- ") <= MAX_LIMIT


# ---- the property the item is named for -----------------------------------


def test_no_exposed_tool_can_write(db) -> None:
    """Read-only, enforced by the surface.

    Checked against the tool list rather than asserted: the claim "this server
    is read-only" is only meaningful if it follows from what is exposed, and a
    new tool added later that writes should fail here.
    """
    banned = ("insert", "update", "delete", "drop", "create", "patch", "toggle", "add")
    for tool in TOOLS:
        assert not any(b in tool.name.lower() for b in banned), (
            f"{tool.name} sounds like a write"
        )


def test_every_exposed_tool_only_reads(db) -> None:
    """Call every tool and assert the database is unchanged afterwards."""
    before = _snapshot(db)
    for tool in TOOLS:
        args = {"query": "router", "id": "n1"}
        dispatch(db, _req("tools/call", {"name": tool.name, "arguments": args}))
    assert _snapshot(db) == before


def _snapshot(db: Database) -> dict:
    return {
        "notes": db.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"],
        "tasks": db.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"],
        "version": db.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"],
    }


# ---- framing --------------------------------------------------------------


def test_a_response_is_one_json_object_on_one_line(db) -> None:
    """stdio transport: newline-delimited JSON. A pretty-printed response breaks
    the client in a way that is hard to diagnose from the client side."""
    out = build_response(dispatch(db, _req("tools/list")))
    assert "\n" not in out
    assert json.loads(out)["result"]["tools"]


def test_a_notification_produces_no_output(db) -> None:
    assert build_response(None) == ""

# ---- the real thing, as a client runs it ----------------------------------


def test_it_handshakes_over_stdio_as_a_subprocess(tmp_path) -> None:
    """The unit tests call `dispatch`; a client spawns a process.

    Nothing above covers the entry point, the newline framing, or the fact that
    a notification produces no line — which is how a client ends up waiting for
    a reply that will never come.
    """
    import os
    import subprocess
    import sys

    sandbox = tmp_path / "data" / "fleeting"
    sandbox.mkdir(parents=True)
    conf = tmp_path / "config" / "fleeting"
    conf.mkdir(parents=True)
    d = Database(str(sandbox / "fleeting.db"))
    d.migrate()
    d.insert_note({"id": "n1", "title": "subprocess note", "raw_text": "body"})
    d.commit()

    script = (
        "import json,sys;"
        "from fleeting.mcp_server import serve,Database;"
        "from fleeting.config import DB_PATH;"
        "db=Database(DB_PATH);db.migrate();serve(db)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        input="\n".join(
            [
                json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
                ),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "search_notes",
                            "arguments": {"query": "subprocess"},
                        },
                    }
                ),
            ]
        ),
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
        env={
            "PATH": os.environ.get("PATH", ""),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "VIRTUAL_ENV": str(__import__("pathlib").Path(sys.prefix)),
        },
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    ids = [json.loads(ln).get("id") for ln in lines]
    assert ids == [1, 2, 3], f"a notification was answered, or a frame was lost: {ids}"
    assert "subprocess note" in json.loads(lines[2])["result"]["content"][0]["text"]
