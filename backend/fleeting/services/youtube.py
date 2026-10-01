"""YouTube ingestion via the system yt-dlp binary.

Strategy: pull metadata + captions first (fast, no big download). If captions
are unavailable and fallback is enabled (and the video is short enough),
download audio-only and transcribe locally with whisper.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from ..config import YouTubeConfig
from .transcribe import Transcriber, TranscriptionError

log = logging.getLogger("fleeting.youtube")


class YouTubeError(Exception):
    pass


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    yt_dlp = _which_ytdlp()
    cmd = [yt_dlp, *args]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise YouTubeError(f"yt-dlp timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise YouTubeError("yt-dlp not found on PATH — install it (pacman -S yt-dlp)") from exc


def _which_ytdlp() -> str:
    import shutil

    path = shutil.which("yt-dlp")
    if not path:
        raise YouTubeError("yt-dlp not found on PATH — install it (pacman -S yt-dlp)")
    return path


def fetch_metadata(url: str) -> dict:
    proc = _run(["-J", "--no-playlist", "--no-warnings", url], timeout=60)
    if proc.returncode != 0:
        raise YouTubeError(_clean_err(proc.stderr))
    try:
        meta = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise YouTubeError(f"could not parse yt-dlp metadata: {exc}") from exc
    return {
        "url": meta.get("webpage_url") or url,
        "title": meta.get("title") or "YouTube video",
        "channel": meta.get("uploader") or meta.get("channel") or "",
        "duration": meta.get("duration") or 0,
        "thumbnail": meta.get("thumbnail") or "",
        "description": (meta.get("description") or "")[:2000],
    }


def fetch_transcript(url: str, *, lang_prefs: tuple[str, ...] = ("en", "hi")) -> tuple[str, str]:
    """Return (transcript_text, method). method is 'captions' or 'whisper'."""
    tmp = Path(tempfile.mkdtemp(prefix="fleeting-yt-"))
    try:
        proc = subprocess.run(
            [_which_ytdlp(), "--skip-download", "--no-playlist", "--no-warnings",
             "--write-subs", "--write-auto-subs", "--sub-langs",
             ",".join(f"{l}.*" for l in lang_prefs),
             "--sub-format", "vtt/srt/best", "-o", "video.%(ext)s", url],
            capture_output=True, timeout=90, cwd=tmp,
        )
    except subprocess.TimeoutExpired as exc:
        raise YouTubeError("caption download timed out") from exc

    sub_files = sorted(tmp.glob("video*.vtt")) + sorted(tmp.glob("video*.srt"))
    if sub_files:
        text = _parse_subtitle(sub_files[0])
        if len(text) > 200:
            return text, "captions"

    raise YouTubeError("no usable captions found for this video")


def fetch_and_transcribe_audio(url: str, transcriber: Transcriber, cfg: YouTubeConfig) -> tuple[str, dict]:
    """Download audio-only and transcribe locally. Returns (text, meta)."""
    meta = fetch_metadata(url)
    duration = meta.get("duration") or 0
    if cfg.max_duration_min and duration > cfg.max_duration_min * 60:
        raise YouTubeError(
            f"video is {duration // 60} min — longer than the {cfg.max_duration_min} min "
            "local-transcription limit (raise it in settings)"
        )
    tmp = Path(tempfile.mkdtemp(prefix="fleeting-yt-audio-"))
    try:
        proc = subprocess.run(
            [_which_ytdlp(), "-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist",
             "--no-warnings", "-o", "audio.%(ext)s", url],
            capture_output=True, timeout=600, cwd=tmp,
        )
        if proc.returncode != 0:
            raise YouTubeError(_clean_err(proc.stderr))
        files = [p for p in tmp.iterdir() if p.name.startswith("audio.")]
        if not files:
            raise YouTubeError("audio download produced no file")
        result = transcriber.transcribe_file(files[0])
        return result["text"], meta
    except TranscriptionError:
        raise
    finally:
        for p in tmp.iterdir():
            p.unlink(missing_ok=True)
        tmp.rmdir()


def ingest(url: str, cfg: YouTubeConfig, transcriber: Transcriber) -> dict:
    """Full ingest: metadata + captions, whisper fallback if allowed.

    Returns {text, source, method}. Raises YouTubeError.
    """
    meta = fetch_metadata(url)
    try:
        text, method = fetch_transcript(url)
    except YouTubeError as cap_err:
        if not cfg.transcribe_fallback:
            raise YouTubeError(
                f"{cap_err} — enable 'transcribe fallback' in settings to download "
                "audio and transcribe it locally"
            ) from cap_err
        log.info("captions unavailable (%s), falling back to local whisper", cap_err)
        text, _ = fetch_and_transcribe_audio(url, transcriber, cfg)
        method = "whisper"

    meta["method"] = method
    return {"text": text, "source": meta}


def _clean_err(stderr: bytes) -> str:
    err = stderr.decode(errors="replace")
    lines = [ln for ln in err.splitlines() if "ERROR" in ln or "error" in ln.lower()]
    if lines:
        return lines[-1][:300]
    return err.strip()[-300:] or "yt-dlp failed"


def _parse_subtitle(path: Path) -> str:
    """VTT/SRT -> readable transcript with light timestamp anchors."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", raw)
    lines_out: list[str] = []
    last_text = ""
    seen_texts: list[str] = []

    def ts_to_secs(ts: str) -> float:
        ts = ts.replace(",", ".")
        parts = ts.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return 0.0
        return 0.0

    current_secs = 0.0
    for block in blocks:
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
                continue
            ts_match = re.match(
                r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})", line
            )
            if ts_match:
                current_secs = ts_to_secs(ts_match.group(1))
                continue
            line = re.sub(r"<[^>]+>", "", line)          # strip <c>, <00:00:...> tags
            line = re.sub(r"^\d+$", "", line).strip()      # srt counters
            if not line:
                continue
            if line == last_text:
                continue
            # rolling-window dedupe for auto captions
            if line in seen_texts[-3:]:
                continue
            # insert timestamp anchor roughly every 2 minutes
            if lines_out and current_secs and current_secs // 120 > len(
                [s for s in lines_out if s.startswith("[")]
            ):
                mins, secs = int(current_secs // 60), int(current_secs % 60)
                lines_out.append(f"[{mins}:{secs:02d}]")
            seen_texts.append(line)
            last_text = line
            lines_out.append(line)

    # group into paragraphs
    words_per_para = 90
    paras: list[str] = []
    buf: list[str] = []
    count = 0
    for line in lines_out:
        buf.append(line)
        if line.startswith("["):
            continue
        count += len(line.split())
        if count >= words_per_para:
            paras.append(" ".join(buf))
            buf, count = [], 0
    if buf:
        paras.append(" ".join(buf))
    return "\n\n".join(paras).strip()
