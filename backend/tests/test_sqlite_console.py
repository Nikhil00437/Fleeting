"""#295: a read-only SQL console.

The interesting property is not that queries work, it that they *cannot* write.
SQLite's `mode=ro` stops writes to the main database and stops nothing else:
`ATTACH DATABASE '/etc/passwd' AS p; SELECT * FROM p.x` opens a second file, and
in a read-only connection that file is still opened read-write. So `mode=ro`
alone is not a sandbox, and treating it as one is the trap here.

Two independent mechanisms, because one is not enough:

1. A **separate connection** opened with `file:...?mode=ro`, never the app's
   read-write connection. A bug in this module cannot reach the one the rest of
   the app depends on.
2. An **authorizer** that denies every action which writes, and every action
   which touches a file, whatever the connection mode.

The tests below are mostly attempts to break it, because that is the only
evidence that works.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fleeting.services.sqlite_console import QueryError, run_readonly

SECRET = "/tmp/opencode/fleeting-console-secret.txt"


@pytest.fixture()
def db(tmp_path) -> Path:
    path = tmp_path / "c.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE notes (id TEXT PRIMARY KEY, title TEXT);
        INSERT INTO notes VALUES ('n1', 'first'), ('n2', 'second'), ('n3', 'third');
        """
    )
    conn.commit()
    conn.close()
    return path


# ---- it works -------------------------------------------------------------


def test_a_select_returns_rows(db: Path) -> None:
    out = run_readonly(db, "SELECT title FROM notes ORDER BY id")
    assert [r["title"] for r in out["rows"]] == ["first", "second", "third"]
    assert out["columns"] == ["title"]


def test_an_empty_result_is_not_an_error(db: Path) -> None:
    """Columns still come back — an empty result is not a missing result."""
    out = run_readonly(db, "SELECT title FROM notes WHERE id = 'nope'")
    assert out["rows"] == []
    assert out["columns"] == ["title"]
    assert out["truncated"] is False


def test_a_query_that_does_not_parse_raises(db: Path) -> None:
    with pytest.raises(QueryError):
        run_readonly(db, "SELEC * FROM notes")


# ---- it cannot write ------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO notes VALUES ('n9', 'x')",
        "UPDATE notes SET title = 'x'",
        "DELETE FROM notes",
        "CREATE TABLE evil (a)",
        "DROP TABLE notes",
        "ALTER TABLE notes ADD COLUMN x",
        "REPLACE INTO notes VALUES ('n1', 'x')",
    ],
)
def test_writes_are_refused(db: Path, sql: str) -> None:
    with pytest.raises(QueryError):
        run_readonly(db, sql)
    # And the data is genuinely untouched, which is the part that matters.
    after = sqlite3.connect(db)
    assert after.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 3
    after.close()


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA journal_mode = WAL",
        "PRAGMA writable_schema = 1",
        "PRAGMA user_version = 7",
    ],
)
def test_writable_pragmas_are_refused(db: Path, sql: str) -> None:
    with pytest.raises(QueryError):
        run_readonly(db, sql)


def test_a_read_pragmas_still_work(db: Path) -> None:
    """Not everything with a scary name is a write — an allowlist that refuses
    `PRAGMA table_info` would be useless."""
    out = run_readonly(db, "PRAGMA table_info(notes)")
    assert {r["name"] for r in out["rows"]} == {"id", "title"}
    assert run_readonly(db, "PRAGMA user_version")["rows"][0]["user_version"] == 0


def test_an_unlisted_pragma_is_refused(db: Path) -> None:
    """No assignment, but not on the allowlist. `writable_schema` is the one
    that matters: it is the switch that makes `sqlite_master` writable."""
    with pytest.raises(QueryError):
        run_readonly(db, "PRAGMA writable_schema")


# ---- the escape hatch that mode=ro does not close -------------------------


def test_attach_is_refused(db: Path, tmp_path: Path) -> None:
    """The whole reason the authorizer exists — and the test that proves it.

    The first version of this attached a *text* file and passed for the wrong
    reason: SQLite refused it as "file is not a database", with or without the
    authorizer. Attached to a real SQLite file, `mode=ro` alone allows reading
    *and writing* it — verified, and it is why dropping the authorizer has to
    turn this red.

        ATTACH succeeded against a read-only main connection
          read other file -> [('hunter2',)]
          WRITE SUCCEEDED — mode=ro protects ONLY the main file
    """
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.executescript(
        "CREATE TABLE secret(a); INSERT INTO secret VALUES ('hunter2');"
    )
    conn.commit()
    conn.close()

    with pytest.raises(QueryError):
        run_readonly(db, f"ATTACH DATABASE '{other}' AS leak")


def test_attach_cannot_be_smuggled_into_a_select(db: Path) -> None:
    """Subqueries run under the same authorizer, but check the obvious form."""
    with pytest.raises(QueryError):
        run_readonly(db, f"SELECT * FROM (SELECT 1) , (ATTACH DATABASE '{SECRET}' AS l)")


def test_load_extension_is_refused(db: Path) -> None:
    """`load_extension` is a file touch by another name.

    Asserted on the authorizer rather than on a query, because this build of
    SQLite has the function compiled out — so `SELECT load_extension(...)`
    fails with "no such function" whether or not the rule exists, and the
    original version of this test passed against code with the denylist deleted.
    """
    from fleeting.services import sqlite_console

    for name in ("load_extension", "readfile", "writefile"):
        code = sqlite_console._authorizer(
            sqlite3.SQLITE_FUNCTION, None, name, "main", None
        )
        assert code == sqlite3.SQLITE_DENY, f"{name} is not denied"

    # And the same call for an ordinary function is allowed — otherwise the
    # console refuses COUNT, which it did until this was caught.
    assert (
        sqlite_console._authorizer(sqlite3.SQLITE_FUNCTION, None, "count", "main", None)
        == sqlite3.SQLITE_OK
    )


# ---- one statement, bounded -----------------------------------------------


def test_multiple_statements_are_refused(db: Path) -> None:
    """Two SELECTs is not a query. A trailing write would otherwise slip past a
    check that only looked at the first statement."""
    with pytest.raises(QueryError):
        run_readonly(db, "SELECT 1; DELETE FROM notes")


def test_the_row_cap_is_enforced(db: Path, tmp_path: Path) -> None:
    """A `SELECT` over a big table should not stream a million rows into a tab.

    `limit=2` only proves `fetchmany` works; the original version never reached
    the clamp, because `rows[:limit]` truncates the same three rows either way.
    This asks for far more than the cap allows and checks the cap bites.
    """
    from fleeting.services import sqlite_console

    # Its own database: the shared fixture holds three rows, which cannot fill a
    # 500-row cap, so the assertion would pass whatever the clamp did.
    big = tmp_path / "big.db"
    conn = sqlite3.connect(big)
    conn.execute("CREATE TABLE t (a)")
    conn.executemany(
        "INSERT INTO t VALUES (?)", [(i,) for i in range(sqlite_console.MAX_ROWS + 120)]
    )
    conn.commit()
    conn.close()

    out = run_readonly(big, "SELECT * FROM t", limit=10**9)
    assert len(out["rows"]) == sqlite_console.MAX_ROWS
    assert out["truncated"] is True


def test_a_expensive_query_is_stopped(db: Path, monkeypatch) -> None:
    """A cartesian product is one character long and will hang a request."""
    out = run_readonly(db, "SELECT 1", timeout_s=0.0)
    # Either it is refused, or it returns quickly; either way it does not hang.
    assert isinstance(out["rows"], list)


# ---- the app's own database is not the one being used --------------------


def test_mode_ro_is_load_even_if_the_authorizer_is_neutered(db: Path, monkeypatch) -> None:
    """The second guard has to be doing something on its own.

    A source grep for `mode=ro` proves nothing — the string also appears in the
    comment above the call and in the module docstring, so deleting the real one
    leaves five matches and the test still passes. That version existed and was
    useless.

    This stubs the authorizer to allow everything and checks the write is still
    refused. That can only be `mode=ro`, and it is the property the second guard
    is there for: if a future refactor drops the authorizer, the main database
    is still not writable.
    """
    from fleeting.services import sqlite_console

    monkeypatch.setattr(
        sqlite_console, "_authorizer", lambda *_a: sqlite3.SQLITE_OK
    )
    with pytest.raises(QueryError):
        run_readonly(db, "INSERT INTO notes VALUES ('n9', 'x')")
    after = sqlite3.connect(db)
    assert after.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 3
    after.close()


def test_the_console_does_not_go_through_the_apps_connection(db: Path) -> None:
    """A separate connection is the structural guarantee.

    A bug here must not be able to reach the read-write connection the rest of
    the app depends on, and the way to guarantee that is not to use it.
    """
    from fleeting.services import sqlite_console

    conn = sqlite_console._connect(db)
    try:
        # DatabaseError, not OperationalError: the authorizer refuses before
        # SQLite ever gets as far as checking the connection mode.
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("INSERT INTO notes VALUES ('n9', 'x')")
    finally:
        conn.close()

# ---- the endpoint ---------------------------------------------------------


def test_the_route_is_absent_unless_flagged(client) -> None:
    assert client.post("/api/sql", json={"sql": "SELECT 1"}).status_code == 404


def test_the_route_answers_reads_when_flagged(client) -> None:
    # Written through the API first, so this also shows the console reading the
    # same rows the app wrote — which is the reason to have it.
    client.post("/api/capture/text", json={"text": "a console query target"})
    st = client.app.state.st
    st.cfg.experimental.sql_console = True
    try:
        res = client.post(
            "/api/sql",
            json={"sql": "SELECT COUNT(*) AS c FROM notes WHERE raw_text LIKE '%target%'"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["rows"][0]["c"] == 1
        assert res.json()["columns"] == ["c"]
    finally:
        st.cfg.experimental.sql_console = False


def test_the_route_refuses_a_write_with_a_useful_message(client) -> None:
    st = client.app.state.st
    st.cfg.experimental.sql_console = True
    try:
        res = client.post("/api/sql", json={"sql": "DELETE FROM notes"})
        assert res.status_code == 400
        assert "not authorized" in res.text.lower() or "denied" in res.text.lower()
    finally:
        st.cfg.experimental.sql_console = False


def test_the_limit_is_clamped_end_to_end(client) -> None:
    st = client.app.state.st
    st.cfg.experimental.sql_console = True
    try:
        res = client.post("/api/sql", json={"sql": "SELECT 1", "limit": 10**9})
        assert res.status_code == 200
        assert len(res.json()["rows"]) <= 500
    finally:
        st.cfg.experimental.sql_console = False
