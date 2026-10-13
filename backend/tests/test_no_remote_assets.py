"""The bundled frontend must not reference another origin.

`src/index.css` used to open with

    @import url('https://fonts.googleapis.com/css2?family=Inter...')

which is fetched on every page load, unconditionally, with no setting to turn it
off — on an app whose README says it needs no network and no API keys. It was
visible for a while before anyone looked at it, because nothing in the repo
checked.

So this is the check. It reads the *source*, not the build, because the build is
an artifact: it is regenerated, cleaned, and served from somewhere else, and a
guard that depends on it is a guard that stops running the moment `dist` is
deleted.

What it deliberately does not do:

- **Allow a list of "fine" hosts.** An allowlist is a hole with a comment on it.
  The app is local-first; there is no origin it legitimately needs.
- **Check only fonts.** The next remote thing will not be a font, and a test
  scoped to the bug it was written for cannot catch the next one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from repo import REPO_ROOT

SRC = REPO_ROOT / "frontend" / "src"
STYLE_FILES = sorted(
    [p for p in SRC.rglob("*.css")] + [p for p in (REPO_ROOT / "frontend").glob("*.html")]
)

# scheme://host/ — matches http, https and protocol-relative URLs.
REMOTE = re.compile(r"""(?:https?:)?//(?!localhost|127\.0\.0\.1|0\.0\.0\.0)[a-z0-9-]+\.[a-z]{2,}""", re.I)


def test_there_are_style_files_to_check() -> None:
    """Otherwise the test below passes because it looked at nothing."""
    assert STYLE_FILES, "no CSS or HTML found — the path is wrong"


@pytest.mark.parametrize("path", STYLE_FILES, ids=lambda p: p.name)
def test_no_source_file_references_another_origin(path: Path) -> None:
    hits = REMOTE.findall(path.read_text(encoding="utf-8", errors="replace"))
    assert not hits, (
        f"{path.relative_to(REPO_ROOT)} references {sorted(set(hits))} — "
        "the app is local-first and has no origin it needs"
    )


def test_the_fonts_are_vendored_rather_than_merely_unimported() -> None:
    """Deleting the `@import` would pass the check above and leave the app with
    fallback fonts. The point is that the faces still exist, locally."""
    css = (SRC / "fonts.css").read_text(encoding="utf-8")
    faces = re.findall(r"url\('([^']+)'\)", css)
    assert faces, "fonts.css declares no font files"

    missing = [f for f in faces if not (SRC / f.removeprefix("./")).exists()]
    assert not missing, f"fonts.css points at missing files: {missing}"


def test_every_family_the_theme_uses_is_vendored() -> None:
    """`--font-sans`, `--font-display` and `--font-mono` name three families.
    Missing one means the app renders in a fallback and nobody says so."""
    index = (SRC / "index.css").read_text(encoding="utf-8")
    fonts = (SRC / "fonts.css").read_text(encoding="utf-8")
    referenced = set(re.findall(r'--font-(?:sans|display|mono):\s*"([^"]+)"', index))
    assert referenced, "no font families found in the theme"
    for family in referenced:
        assert family in fonts, f"{family!r} is used by the theme but not vendored"


def test_the_offline_report_will_not_see_a_remote_stylesheet() -> None:
    """The user-visible consequence, asserted: `remoteStylesheets()` exists to
    find exactly this, and it is why the Diagnostics page named the font."""
    css = (SRC / "index.css").read_text(encoding="utf-8")
    assert "fonts.css" in css, "index.css should import the local font sheet"
    assert REMOTE.search(css) is None