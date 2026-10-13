"""Generates the route table for tests/test_routes_smoke.py.

Run once; the output is committed. A committed table beats a generated one at
runtime because a route that disappears does not silently shrink the test — it
fails, which is the whole point.

    uv run python tests/_gen_route_table.py > /tmp/table.py
"""

from __future__ import annotations

import re

from fleeting.config import Config
from fleeting.main import create_app

# Path params get a placeholder that cannot exist, so the operation is proven
# wired (and reachable) without needing a fixture per resource.
PLACEHOLDERS = {
    "note_id": "no-such-note",
    "task_id": "no-such-task",
    "coll_id": "no-such-collection",
    "rule_id": "no-such-rule",
    "chat_id": "no-such-chat",
    "job_id": "no-such-job",
    "alias": "no-such-alias",
    "att_id": "no-such-attachment",
    "schedule_id": "no-such-schedule",
    "reminder_id": "no-such-reminder",
    "version_id": "1",
}

# Methods whose happy path needs a body the caller must supply. Covered
# explicitly in the smoke module rather than guessed at here.
SKIP = {
    ("POST", "/api/sql"),
    # Server-sent events never return — the response body is an endless
    # stream, so a plain request blocks forever. Covered by test_events.py's
    # streaming test and the frontend's SSE client, not by a reachability probe.
    ("GET", "/api/events"),
}


def concrete(path: str) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        return PLACEHOLDERS.get(name, "placeholder")

    return re.sub(r"\{([a-zA-Z_]+)(:[^}]+)?\}", sub, path)


def main() -> None:
    spec = create_app(Config(), load_from_disk=False).openapi()
    rows: list[tuple[str, str, int]] = []
    for path, ops in sorted(spec["paths"].items()):
        if any(x in path for x in ("/docs", "/openapi", "/redoc")):
            continue
        for method in ops:
            if method in ("head", "options"):
                continue
            key = (method.upper(), path)
            if key in SKIP:
                continue
            rows.append((method.upper(), concrete(path), 0))
    rows.sort(key=lambda r: (r[1], r[0]))
    print(f"# {len(rows)} API operations, generated from the OpenAPI spec.")
    print("ROUTES = [")
    for method, path, _ in rows:
        print(f'    ("{method}", "{path}"),')
    print("]")


if __name__ == "__main__":
    main()