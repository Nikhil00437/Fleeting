#!/usr/bin/env python3
"""#293: generate `API.md` from the live OpenAPI spec.

The file is committed, because a reference you have to run something to read is
not a reference. `tests/test_api_docs.py` regenerates it and fails if the
committed copy differs — so it cannot drift, which is the only property that
makes a generated document worth having.

Lives at the repo root rather than under `docs/` because `docs/` is gitignored
on purpose: it holds local planning material, and a published API reference is
not that.

Run it from the repo root:

    uv run --project backend python scripts/gen_api_docs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "API.md"

sys.path.insert(0, str(REPO_ROOT / "backend"))

from fleeting import __version__  # noqa: E402
from fleeting.config import Config  # noqa: E402
from fleeting.main import create_app  # noqa: E402

# Response codes that are behaviour rather than schema. Everything else comes
# from the spec, so this list stays short.
EXTRA_STATUS = {
    "get": {200: "OK", 421: "foreign Host", 423: "app is locked"},
    "post": {
        200: "OK",
        401: "token required",
        403: "cross-origin write, or read-only demo",
        409: "confirmation required",
        421: "foreign Host",
        423: "app is locked",
    },
    "put": {200: "OK", 401: "token required", 409: "confirmation required", 421: "foreign Host"},
    "patch": {200: "OK", 401: "token required", 421: "foreign Host"},
    "delete": {200: "OK", 401: "token required", 421: "foreign Host"},
}


def _summary(op: dict) -> str:
    """One-line summary, falling back to something honest when there is none."""
    text = (op.get("summary") or op.get("description") or "").strip().split("\n")[0]
    return text or "—"


def render(spec: dict) -> str:
    lines: list[str] = [
        "# Fleeting HTTP API",
        "",
        f"Generated from the OpenAPI spec by `scripts/gen_api_docs.py`. "
        f"Do not edit — `tests/test_api_docs.py` regenerates and compares.",
        "",
        f"Fleeting {spec['info']['version']} · {len(spec['paths'])} paths · "
        f"server `{spec['servers'][0]['url']}`",
        "",
        "The [spec itself](backend/fleeting/api_docs.py) is the source of truth for what the",
        "guards do; this file is an index of what exists.",
        "",
        spec["info"]["description"],
        "",
        "## Endpoints",
        "",
    ]
    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            tag = (op.get("tags") or ["untagged"])[0]
            by_tag.setdefault(tag, []).append((method.upper(), path, op))

    descriptions = {t["name"]: t.get("description", "") for t in spec.get("tags") or []}
    for tag in sorted(by_tag):
        lines.append(f"### `{tag}`")
        if descriptions.get(tag):
            lines.append("")
            lines.append(descriptions[tag])
        lines.append("")
        lines.append("| Method | Path | Summary | Codes |")
        lines.append("| --- | --- | --- | --- |")
        for method, path, op in sorted(by_tag[tag], key=lambda r: (r[1], r[0])):
            # The spec keys responses by string; `EXTRA_STATUS` by int. Mixed
            # types do not sort, which is a TypeError rather than a wrong order.
            extra = EXTRA_STATUS.get(method.lower(), {})
            codes = sorted({int(c) for c in op.get("responses", {})} | set(extra))
            pretty = ", ".join(
                f"{c}" + (f" — {extra[c]}" if c in extra else "") for c in codes
            )
            lines.append(f"| {method} | `{path}` | {_summary(op)} | {pretty} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    app = create_app(Config(), load_from_disk=False)
    text = render(app.openapi())
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("API.md is out of date — run scripts/gen_api_docs.py", file=sys.stderr)
            return 1
        print("API.md is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({len(text.splitlines())} lines) for Fleeting {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())