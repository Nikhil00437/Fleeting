"""The README embeds `assets/demo.gif`, and a dead image link is invisible.

Nothing fails when a GIF is deleted, renamed or zeroed out: the markdown still
renders, the repo still builds, and the README just shows a broken image on
GitHub. Same class as the roadmap and contributor-guide checks — the fact lives
in the repo, so check it.
"""

from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


def _embedded_images() -> list[str]:
    text = README.read_text(encoding="utf-8")
    return [p for p in __import__("re").findall(r"!\[[^\]]*\]\(([^)]+)\)", text)]


def test_the_readme_embeds_the_demo() -> None:
    assert "assets/demo.gif" in _embedded_images(), (
        "the README no longer shows the demo image"
    )


def test_the_demo_file_exists_and_is_not_a_stub() -> None:
    """Not empty, and not a few kilobytes. A 2 KB GIF is a broken render, not a
    demo, and the markdown would still look fine."""
    path = ROOT / "assets" / "demo.gif"
    assert path.exists(), "assets/demo.gif is missing"
    assert path.stat().st_size > 100_000, (
        f"assets/demo.gif is {path.stat().st_size} bytes — too small to be a real recording"
    )


def test_the_demo_is_a_real_animated_gif() -> None:
    """Header, not extension. A PNG renamed to .gif breaks on GitHub silently."""
    path = ROOT / "assets" / "demo.gif"
    blob = path.read_bytes()[:16]
    assert blob[:6] in (b"GIF87a", b"GIF89a"), f"not a GIF: {blob[:6]!r}"

    body = path.read_bytes()
    assert body[-1] == 0x3B, "no GIF trailer"

    # Walk the block structure, counting image descriptors. The walk has to
    # handle the global colour table, extensions with sub-blocks, and local
    # colour tables — an earlier version counted one frame because it treated
    # every extension as a terminator.
    def walk(pos: int) -> tuple[int, int]:
        flags = body[10]
        if flags & 0x80:
            pos += 3 * (2 ** ((flags & 0x07) + 1))
        frames = 0
        sizes: list[tuple[int, int]] = []
        while pos < len(body):
            block = body[pos]
            if block == 0x2C:  # image descriptor
                w, h = struct.unpack("<HH", body[pos + 5 : pos + 9])
                sizes.append((w, h))
                frames += 1
                local = body[pos + 9]
                pos += 10
                if local & 0x80:
                    pos += 3 * (2 ** ((local & 0x07) + 1))
                pos += 1  # LZW minimum code size
                while body[pos] != 0:  # data sub-blocks
                    pos += body[pos] + 1
                pos += 1
            elif block == 0x21:  # extension
                pos += 2
                while body[pos] != 0:
                    pos += body[pos] + 1
                pos += 1
            elif block == 0x3B:  # trailer
                break
            else:
                break
        return frames, len(sizes)

    frames, _ = walk(13 if body[:6] == b"GIF89a" else 10)
    assert frames >= 10, f"only {frames} frames — unlikely to be a real recording"


def test_the_recorder_script_is_checked_in_and_runnable() -> None:
    """The GIF has to be re-recordable, or it goes stale as the UI moves."""
    script = ROOT / "frontend" / "scripts" / "record-demo.mjs"
    assert script.exists(), "the recorder is not checked in"
    assert "e2e-server.sh" in script.read_text(encoding="utf-8"), (
        "the recorder no longer uses the seeded demo server"
    )


def test_the_recorder_is_not_part_of_the_test_suite() -> None:
    """It must not run in CI: it records frames and shells out to ffmpeg."""
    config = ROOT / "frontend" / "playwright.config.ts"
    assert config.exists()
    text = config.read_text(encoding="utf-8")
    assert "record-demo" not in text, "the recorder has been wired into the test suite"
    assert "./e2e" in text
