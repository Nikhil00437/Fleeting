"""#398: the README roadmap must not claim a version shipped that has not.

A roadmap that drifts is worse than no roadmap: the first reader who notices
stops trusting the rest of the file, and nobody audits a table on the way to the
capture button. There is no generator keeping these in sync — the source table
lives in gitignored `docs/`, and a script nobody runs is a script that does not
run — so the check is a test.

This is not theoretical. The first draft of this roadmap listed 0.10 through
0.17 as shipped, on the strength of `docs/versions/README.md` listing them in a
table, and those bundles hold 20 to 52 unchecked items each. Two tests here
caught it before it was committed.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
VERSIONS = ROOT / "docs" / "versions"


def _version_key(value: str) -> tuple[int, int]:
    """`0.10` is a higher version than `0.3` — which `float` gets wrong.

    The first version of this compared floats, so 0.10 sorted below 0.3 and the
    ordering test failed on a table that was correctly ordered.
    """
    major, _, minor = value.partition(".")
    return (int(major), int(minor) if minor.isdigit() else 0)


def _shipped_rows(readme: str) -> list[str]:
    """The `| 0.3 | Theme |` rows of the shipped table."""
    return re.findall(r"^\|\s*(\d+\.\d+)\s*\|", readme, re.MULTILINE)


def _in_progress(readme: str) -> str | None:
    # The version, not the bold markup around it: the README writes
    # `**In progress — 0.18:**`, so an earlier pattern requiring `**` adjacent
    # to the number matched nothing and both in-progress tests failed.
    match = re.search(r"In progress.*?(\d+\.\d+)", readme, re.MULTILINE)
    return match.group(1) if match else None


def _all_bundle_versions() -> list[str]:
    return sorted(
        (m.group(1) for p in VERSIONS.glob("*.md") if (m := re.match(r"(\d+\.\d+)-", p.name))),
        key=_version_key,
    )


def _open_items(version: str) -> int:
    bundle = next(VERSIONS.glob(f"{version}-*.md"), None)
    if bundle is None:
        return 0
    return len(re.findall(r"^\s*-\s*\[ \]", bundle.read_text(encoding="utf-8"), re.MULTILINE))


# ---- the claims -----------------------------------------------------------


def test_every_shipped_version_has_a_bundle_file() -> None:
    readme = README.read_text(encoding="utf-8")
    for version in _shipped_rows(readme):
        assert next(VERSIONS.glob(f"{version}-*.md"), None), (
            f"README lists {version} as shipped but docs/versions has no bundle"
        )


def test_a_shipped_version_really_is_complete() -> None:
    """The expensive direction, and the one that caught the first draft.

    0.10–0.17 were listed as shipped while carrying 20–52 unchecked items each.
    """
    readme = README.read_text(encoding="utf-8")
    for version in _shipped_rows(readme):
        open_items = _open_items(version)
        assert not open_items, (
            f"README lists {version} as shipped, but its bundle still has "
            f"{open_items} unchecked items"
        )


def test_an_unshipped_version_is_not_claimed_as_shipped() -> None:
    """The other side: a bundle with work left in it must not be in the table."""
    readme = README.read_text(encoding="utf-8")
    shipped = _shipped_rows(readme)
    for version in _all_bundle_versions():
        if _open_items(version):
            assert version not in shipped, (
                f"{version} has {_open_items(version)} unchecked items but is listed as shipped"
            )


def test_the_in_progress_version_is_not_also_listed_as_shipped() -> None:
    readme = README.read_text(encoding="utf-8")
    in_progress = _in_progress(readme)
    assert in_progress, "the roadmap does not name what is in progress"
    assert in_progress not in _shipped_rows(readme), (
        f"{in_progress} is both 'in progress' and in the shipped table"
    )


def test_the_in_progress_version_really_is_being_worked_on() -> None:
    """Not left naming a version that finished long ago.

    Note what this does *not* check: whether the version named is the right one.
    Writing "in progress: 0.15" when the work is in 0.18 is undetectable here —
    both have items left — and no test can tell, because which bundle is being
    worked on is a judgement, not a fact in the repo. The two checkable
    directions are covered; this one is not, deliberately.
    """
    readme = README.read_text(encoding="utf-8")
    in_progress = _in_progress(readme)
    assert _open_items(in_progress or ""), (
        f"{in_progress} is called 'in progress' but has nothing left to do"
    )


def test_the_shipped_table_is_in_order() -> None:
    readme = README.read_text(encoding="utf-8")
    versions = [_version_key(v) for v in _shipped_rows(readme)]
    assert versions == sorted(versions), "the shipped table is out of order"
    assert versions, "no shipped versions are listed at all"
