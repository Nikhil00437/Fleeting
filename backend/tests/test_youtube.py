"""YouTube caption fetching.

Exists mostly for one line: `fetch_transcript` used to run yt-dlp, ignore its
exit code, and then report "no usable captions found for this video". A broken
or missing yt-dlp therefore looked like a problem with the user's video, and
the error sent them to look at the wrong thing entirely. Its sibling
`fetch_and_transcribe_audio` has checked this all along.
"""

from __future__ import annotations

import subprocess

import pytest

from fleeting.services import youtube
from fleeting.services.youtube import YouTubeError


class _Proc:
    def __init__(self, returncode: int, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = b""


@pytest.mark.parametrize(
    "call",
    [
        lambda **kw: youtube.fetch_transcript("https://youtu.be/x", **kw),
    ],
)
def test_a_failed_yt_dlp_is_reported_as_a_tool_failure(monkeypatch, call) -> None:
    def boom(*a, **kw):
        return _Proc(1, b"ERROR: [youtube] xxxx: Video unavailable")

    monkeypatch.setattr(youtube.subprocess, "run", boom)

    with pytest.raises(YouTubeError) as exc:
        call()

    # The tool's own words, not "no usable captions" — the distinction is the
    # whole point: one is the user's video, the other is the installation.
    assert "unavailable" in str(exc.value).lower()
    assert "captions" not in str(exc.value).lower()


def test_a_timeout_is_still_reported_as_a_timeout(monkeypatch) -> None:
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=90)

    monkeypatch.setattr(youtube.subprocess, "run", boom)

    with pytest.raises(YouTubeError, match="timed out"):
        youtube.fetch_transcript("https://youtu.be/x")


def test_a_successful_run_still_reports_no_captions(monkeypatch, tmp_path) -> None:
    """A clean run that produced nothing is still 'no usable captions'."""
    monkeypatch.setattr(youtube.subprocess, "run", lambda *a, **kw: _Proc(0))

    with pytest.raises(YouTubeError, match="no usable captions"):
        youtube.fetch_transcript("https://youtu.be/x")