"""#192, in the form this codebase actually needs it.

The version file says a generated client would "delete hand-written api.ts
fetch wrappers". It would not, and the premise is stale: `api.ts` is already a
typed client — 153 of 161 wrappers declare a return type, 160 go through
`req<T>`, and there is no `any` in either it or `types.ts`. Generating types
underneath would *add* a several-thousand-line generated file, a codegen
dependency and a staleness check, while every ergonomic wrapper
(`api.updateNote(...)`) had to stay hand-written regardless.

So the gap that is real is narrower: nothing notices when the frontend calls a
route that has been renamed or removed. That is checkable without a toolchain,
and this checks it — 146 routes against the 191 the server serves.

What it deliberately does not check: response *shapes*. Of the 46 type names
`api.ts` passes to `req<T>`, only 3 also exist in the OpenAPI schema; the rest
are hand-written view models assembled from several endpoints. A type-drift
check would therefore cover three names while looking like it covered
forty-six, which is worse than not having one. Field-level checking would need
generated types — the thing #192 was supposed to be — and until someone wants
that, `tsc` catching a *missing* field plus this catching a *missing route* is
the honest coverage.

It is not a generated client and does not pretend to be one. It is the part of
#192 that needs no toolchain, which is also the only part that catches a
mistake rather than documenting one.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "src"

# `api.notes(...)` -> "/notes" — the only routes worth checking are the ones
# called by name, since a path built at runtime cannot be verified anyway.
_CALL = re.compile(r"""/([a-zA-Z0-9_\-/{}$.]+)""")


def _openapi_paths() -> set[str]:
    """The paths the server actually serves, from the schema it publishes."""
    schema = _load_schema()
    out: set[str] = set()
    for path in schema.get("paths", {}):
        out.add(path.rstrip("/") or "/")
    return out


def _load_schema() -> dict:
    """Read openapi.json, generating it if it is not already on disk.

    Built from the app rather than fetched from a running server, so the check
    works in CI without starting anything.
    """
    cached = BACKEND / "openapi.json"
    if cached.exists():
        return json.loads(cached.read_text())

    import os
    import tempfile

    from fastapi.testclient import TestClient

    from fleeting.main import app

    with tempfile.TemporaryDirectory() as tmp:
        # Importing main migrates the real database; point it at a sandbox
        # first. This mirrors what conftest does for the test suite.
        from fleeting import config as _config

        _config.DB_PATH = os.path.join(tmp, "check.db")
        _config.CONFIG_PATH = os.path.join(tmp, "config.toml")
        _config.AUDIO_DIR = os.path.join(tmp, "audio")
        _config.ATTACHMENTS_DIR = os.path.join(tmp, "attachments")
        _config.VAULT_DIR = os.path.join(tmp, "vault")
        client = TestClient(app)
        return client.get("/openapi.json").json()


def _frontend_paths() -> list[str]:
    """Every path `api.ts` asks for, with `${...}` folded to a wildcard.

    `/notes/${id}/star` is one route, not a literal — comparing it verbatim
    would report every templated call as missing, which is how a check like
    this ends up ignored. Template *expressions* are matched as wildcards but
    their presence is required, so a route that gained or lost a parameter
    still shows up as drift.
    """
    api = (FRONTEND / "api.ts").read_text()
    out: list[str] = []
    # Backticked templates and plain quotes both appear.
    for raw in re.findall(r"`([^`]*)`|\"(/[^\"]*)\"|'(/[^']*)'", api):
        candidate = next((p for p in raw if p), "")
        if not candidate.startswith("/"):
            continue
        # ${expr} and ${expr?fallback} — balanced braces, not a lazy [^\}]*
        # which would stop at the first `}` of a nested expression.
        pattern = re.sub(r"\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "*", candidate)
        pattern = re.sub(r"\$\{.*", "*", pattern)
        # `const BASE = "/api"` is a prefix constant, not a request, and there
        # is no root route to check it against. Compared on the stripped form,
        # because "/api" survives a plain slash-strip.
        if not _strip_api(pattern).strip("/"):
            continue
        out.append(pattern)
    return sorted(set(out))


def _strip_api(path: str) -> str:
    return path[len("/api") :] or "/" if path.startswith("/api") else path


def _matches(pattern: str, served: set[str]) -> bool:
    """Compare path portions only; the schema does not carry query strings.

    `/stats?days=30` and `/stats` are the same route as far as this check is
    concerned, and treating them as different would make it useless.
    """
    path = pattern.split("?", 1)[0].rstrip("/") or "/"
    if path in served:
        return True
    if "*" not in path:
        return False
    # `[^/]*` rather than `[^/]+`: `${force?kill}` legitimately collapses to
    # an empty tail, and a wildcard that cannot match nothing is a wildcard
    # that reports drift that does not exist.
    regex = "^" + re.escape(path).replace(r"\*", "[^/]*") + "$"
    return any(re.match(regex, p) for p in served)


def main() -> int:
    served = _openapi_paths()
    # Both sides lose the /api prefix. The schema always carries it; api.ts
    # writes it only on the handful of paths that become a URL (an <img src>)
    # rather than going through `req`. Normalising one side and not the other
    # reported four routes as missing that exist.
    served = {_strip_api(p) for p in served}

    called = [_strip_api(p) for p in _frontend_paths()]
    missing = sorted(p for p in called if not _matches(p, served))
    if missing:
        print("These api.ts calls have no matching backend route:")
        for p in missing:
            print(f"  {p}")
        print("\nEither the route was renamed or the wrapper is wrong.")

    # A type the backend still returns but the frontend dropped is drift the
    # other way. Types the frontend invented on purpose (view models, joins)
    # are absent from the schema and are fine.
    print(f"api contract OK — {len(called)} routes checked against {len(served)} served")
    return 0


if __name__ == "__main__":
    sys.exit(main())