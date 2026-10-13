"""#295: run a read-only SQL query against the app's own database.

Two independent mechanisms, because `mode=ro` alone is not a sandbox.

**A separate connection**, opened as `file:...?mode=ro`, never the app's
read-write connection. Read-only mode stops writes to *that* file and nothing
else: `ATTACH DATABASE '/somewhere' AS p` opens a second file, and in a read-only
connection that second file is still opened read-write. So a console gated only
on `mode=ro` is a way to write anywhere the process can.

**An authorizer** that denies every action which writes, and every action which
touches a file, regardless of what the connection mode says. `sqlite3`'s
authorizer is native — no dependency, and it runs inside SQLite rather than
beside it, so a cleverer query does not get further.

Everything else is containment rather than safety: one statement per call, a row
cap, and a wall-clock limit so a cartesian product does not hold a request open.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

# Actions that write, or that touch a file, or that could be used to reach one.
_DENIED = frozenset(
    {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_REINDEX,
        sqlite3.SQLITE_ANALYZE,
        sqlite3.SQLITE_CREATE_VTABLE,
        sqlite3.SQLITE_DROP_VTABLE,
        # The escape hatch: a read-only connection still attaches read-write.
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
    }
)

MAX_ROWS = 500
MAX_SQL_CHARS = 20_000


class QueryError(Exception):
    """Anything that means the query was refused or would not run."""


# Function-level escapes. Denying SQLITE_FUNCTION outright looks right and
# breaks everything: SQLite invokes the authorizer for *every* function call,
# so a blanket denial refuses COUNT. `load_extension` was the reason the check
# existed, and readfile/writefile are the other two worth naming.
_DENIED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit"})


def _authorizer(action: int, *_args: Any) -> int:
    """sqlite3 asks before every operation; deny before the ones that matter.

    `SQLITE_FUNCTION` passes the function name as the second argument.
    """
    if action in _DENIED:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        name = (_args[1] or "").lower() if len(_args) > 1 else ""
        if name in _DENIED_FUNCTIONS:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


# Pragmas worth having in a read console. An allowlist rather than a
# denylist: the authorizer does not see pragma settings at all, and an earlier
# attempt to deny the obvious writers let `PRAGMA writable_schema = 1` through.
_READ_PRAGMAS = frozenset(
    {
        "table_info",
        "index_list",
        "index_info",
        "index_xinfo",
        "foreign_key_list",
        "database_list",
        "page_count",
        "page_size",
        "integrity_check",
        "quick_check",
        "user_version",
        "schema_version",
        "compile_options",
        "collation_list",
    }
)


def _check_pragmas(sql: str) -> None:
    """Allow reading a known-safe pragma; refuse anything with an assignment.

    `PRAGMA user_version` reads and `PRAGMA user_version = 7` writes, and the
    only difference is the `=`, so that is where the line is drawn.
    """
    body = sql[len("pragma") :].strip()
    if "=" in body or "pragma" != sql[:6].strip().lower():
        raise QueryError("only read-only pragmas are allowed")
    name = body.split()[0].split("(")[0].strip().lower() if body.split() else ""
    if name not in _READ_PRAGMAS:
        raise QueryError(f"pragma {name or '?'} is not allowed")


def _check_single_statement(sql: str) -> None:
    """One statement per call.

    `sqlite3.execute` refuses multiple statements itself, so this is belt and
    braces — but the refusal comes from a check that looked at the whole string,
    rather than from the driver stopping at the first semicolon.
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise QueryError("empty query")
    if ";" in stripped:
        raise QueryError("one statement at a time")
    if not sqlite3.complete_statement(stripped + ";"):
        raise QueryError("incomplete statement")
    if stripped[:6].strip().lower() == "pragma":
        _check_pragmas(stripped)


def _connect(path: Path) -> sqlite3.Connection:
    # `mode=ro` is the second of two independent guards; the authorizer below is
    # the first, and neither is sufficient alone.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.set_authorizer(_authorizer)
    return conn


def run_readonly(
    path: Path | str,
    sql: str,
    *,
    limit: int = MAX_ROWS,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Run one read-only statement. Returns rows as dicts, capped and timed out."""
    path = Path(path)
    sql = (sql or "").strip()
    if len(sql) > MAX_SQL_CHARS:
        raise QueryError("query too long")
    _check_single_statement(sql)
    if not path.exists():
        raise QueryError(f"no database at {path}")

    limit = max(1, min(int(limit), MAX_ROWS))
    conn = _connect(path)
    deadline = time.monotonic() + max(0.0, timeout_s)

    def expired() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(expired, 10_000)
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in (cur.description or [])]
        rows = [dict(r) for r in cur.fetchmany(limit + 1)]
    except sqlite3.Error as exc:
        # `not authorized` comes from the authorizer; say so plainly rather than
        # letting a read attempt look like a syntax error.
        raise QueryError(str(exc)) from exc
    finally:
        conn.close()

    truncated = len(rows) > limit
    return {
        "columns": columns,
        "rows": rows[:limit],
        "truncated": truncated,
    }