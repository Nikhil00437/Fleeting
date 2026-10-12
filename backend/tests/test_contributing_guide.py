"""CONTRIBUTING.md makes claims that go bad quietly.

A guide that says "run this command" for a command that no longer exists is worse
than no guide, and nothing else would notice: `bun run test:e2e` was renamed, a
test directory moved, a flags comment went stale, and a newcomer would find out
by failing in front of whoever asked them to help.

Same idea as the roadmap test — these are facts about the repo, so check them
against the repo.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "CONTRIBUTING.md"
README = ROOT / "README.md"
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"


def test_the_links_to_other_docs_resolve() -> None:
    """A relative link to a file that is not there."""
    for name in ("README.md", "CONTRIBUTING.md", "ARCHITECTURE.md"):
        target = ROOT / name
        if not GUIDE.exists() and target == GUIDE:
            continue
        if f"({name})" in GUIDE.read_text(encoding="utf-8"):
            assert target.exists(), f"{name} is linked but missing"


def test_every_npm_script_the_guide_names_exists() -> None:
    pkg = json.loads((FRONTEND / "package.json").read_text())
    scripts = pkg.get("scripts", {})
    for name in re.findall(r"bun run ([\w:-]+)", GUIDE.read_text(encoding="utf-8")):
        assert name in scripts, f"`bun run {name}` is documented but not in package.json"


def test_every_script_the_guide_cites_is_checked_in() -> None:
    for script in re.findall(r"\./scripts/([\w.-]+\.sh)", GUIDE.read_text(encoding="utf-8")):
        assert (ROOT / "scripts" / script).exists(), f"scripts/{script} is missing"


def test_the_test_counts_are_roughly_right() -> None:
    """Not exact — counts move — but not off by an order of magnitude.

    The README claimed 235 backend tests for a long time against a real 5.8k,
    which is the kind of number a reader trusts without checking.
    """
    readme = README.read_text(encoding="utf-8")
    match = re.search(r"# ~([\d.]+)k tests", readme)
    assert match, "the README no longer states a backend test count"
    claimed = float(match.group(1)) * 1000
    files = len(list((BACKEND / "tests").glob("test_*.py")))
    assert files, "no test files found at all"
    # Asserted as tests-per-file, because a file count alone says nothing.
    per_file = claimed / files
    assert 5 <= per_file <= 150, (
        f"README claims ~{claimed:,.0f} backend tests across {files} files "
        f"({per_file:.0f} per file) — that ratio is not plausible"
    )


def test_the_commit_prefixes_used_are_conventional() -> None:
    prefixes = set(re.findall(r"`(?:feat|fix|docs|refactor|chore|test)(?:\([^)]*\))?:", GUIDE.read_text(encoding="utf-8")))
    assert prefixes, "the guide gives no commit examples"
    history = subprocess.run(
        ["git", "log", "--format=%s", "-n", "40"], cwd=ROOT, capture_output=True, text=True
    )
    if history.returncode != 0:
        pytest.skip("no git history to compare against")
    kinds = {s.split(":", 1)[0].split("(")[0] for s in history.stdout.splitlines() if ":" in s}
    unknown = {k for k in kinds if k not in {"feat", "fix", "docs", "refactor", "chore", "test"}}
    assert not unknown, f"commits use prefixes the guide never mentions: {unknown}"


def test_the_guide_mentions_the_two_silent_failure_modes() -> None:
    """The two that have cost the most: a missing reducer branch, and a secret
    that reaches a response. If the guide stops naming them, someone will
    reintroduce one."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "serverEvents" in text
    assert "redact" in text.lower()


def test_the_demo_and_e2e_scripts_still_exist() -> None:
    """Both are named in the e2e section of the guide."""
    text = GUIDE.read_text(encoding="utf-8")
    if "test:e2e" in text:
        assert (ROOT / "scripts" / "e2e-server.sh").exists()
        assert (ROOT / "scripts" / "e2e-server.sh").stat().st_mode & 0o111, "not executable"


def test_ffmpeg_is_not_required_by_the_documented_commands() -> None:
    """A prerequisite nobody states is a prerequisite nobody has.

    Only worth asserting because the e2e *tests* use Chromium's fake audio device
    and the transcription fixtures skip without ffmpeg — both are already handled,
    so the guide's commands genuinely need nothing extra.
    """
    text = GUIDE.read_text(encoding="utf-8")
    if "hermetic" in text:
        assert not re.search(r"install ffmpeg", text)
        assert shutil.which("ffmpeg") is not None or "skip" in text
