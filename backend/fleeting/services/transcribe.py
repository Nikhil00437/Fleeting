"""Local speech-to-text via faster-whisper.

The model is loaded lazily on first transcription and cached as a module-level
singleton. Audio is first normalized to 16 kHz mono WAV through ffmpeg so any
container the browser or yt-dlp produces works.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ..config import TranscribeConfig

log = logging.getLogger("fleeting.transcribe")

WHISPER_TIERS = ("tiny", "base", "small", "medium")
ALLOW_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


class TranscriptionError(Exception):
    pass


class Transcriber:
    def __init__(
        self,
        cfg: TranscribeConfig,
        on_progress: Callable[[dict], None] | None = None,
    ):
        self.cfg = cfg
        self._model = None
        self._lock = threading.Lock()
        self.loaded_model_size: str | None = None
        self._on_progress = on_progress
        self.progress: dict = {
            "status": "idle",
            "model": cfg.model,
            "percent": 0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed_bps": 0.0,
            "detail": "",
        }

    def _emit_progress(
        self,
        *,
        status: str,
        model: str | None = None,
        percent: int = 0,
        downloaded_bytes: int = 0,
        total_bytes: int = 0,
        speed_bps: float = 0.0,
        detail: str = "",
    ) -> None:
        payload = {
            "status": status,
            "model": model or self.cfg.model,
            "percent": max(0, min(100, int(percent))),
            "downloaded_bytes": int(downloaded_bytes),
            "total_bytes": int(total_bytes),
            "speed_bps": round(float(speed_bps), 1),
            "detail": detail,
        }
        self.progress = payload
        if self._on_progress is not None:
            try:
                self._on_progress(payload)
            except Exception:
                pass

    def set_model(self, model_name: str) -> None:
        self.cfg.model = model_name
        self._model = None
        self.loaded_model_size = None
        self._emit_progress(status="idle", model=model_name, percent=0, detail="")

    @staticmethod
    def is_model_cached(size_or_id: str) -> bool:
        p = Path(size_or_id)
        if p.is_dir() and (p / "model.bin").exists():
            return True
        try:
            import huggingface_hub
            from faster_whisper.utils import _MODELS

            repo_id = _MODELS.get(size_or_id, size_or_id)
            local_dir = huggingface_hub.snapshot_download(
                repo_id,
                allow_patterns=ALLOW_PATTERNS,
                local_files_only=True,
            )
            return (Path(local_dir) / "model.bin").exists()
        except Exception:
            return False

    def cached_models(self) -> list[str]:
        return [m for m in WHISPER_TIERS if self.is_model_cached(m)]

    def _ensure_model_downloaded(self, size_or_id: str) -> tuple[str, int]:
        """Return (local_model_dir, total_bytes). Streams byte-level progress if downloading."""
        p = Path(size_or_id)
        if p.is_dir() and (p / "model.bin").exists():
            size = (p / "model.bin").stat().st_size
            return str(p), size

        import huggingface_hub
        from faster_whisper.utils import _MODELS

        repo_id = _MODELS.get(size_or_id, size_or_id)
        try:
            local_dir = huggingface_hub.snapshot_download(
                repo_id,
                allow_patterns=ALLOW_PATTERNS,
                local_files_only=True,
            )
            model_bin = Path(local_dir) / "model.bin"
            if model_bin.exists():
                return str(local_dir), model_bin.stat().st_size
        except Exception:
            pass

        self._emit_progress(
            status="downloading",
            model=size_or_id,
            percent=2,
            downloaded_bytes=0,
            total_bytes=0,
            speed_bps=0.0,
            detail=f"Fetching '{size_or_id}' model manifest from Hugging Face…",
        )

        outer = self
        bar_lock = threading.Lock()
        state = {"last_emit": 0.0, "downloaded": 0, "total": 0}

        class _ProgressTqdm:
            def __init__(self, iterable=None, *args, **kwargs):
                self.iterable = iterable
                self.n = int(kwargs.get("initial", 0) or 0)
                self.total = int(kwargs.get("total", 0) or 0)
                self.desc = str(kwargs.get("desc", "") or "")
                self.unit = str(kwargs.get("unit", "") or "")
                self.disable = False
                self._started = time.monotonic()
                # Track the primary byte reconstruction bar (which holds true file byte totals)
                self._track_bytes = self.unit == "B" and (
                    "Reconstruct" in self.desc or "Download" not in self.desc
                )

            @property
            def format_dict(self) -> dict:
                elapsed = max(0.001, time.monotonic() - self._started)
                return {"rate": self.n / elapsed, "n": self.n, "total": self.total}

            def _report(self, force: bool = False) -> None:
                if not self._track_bytes:
                    return
                now = time.monotonic()
                with bar_lock:
                    state["downloaded"] = self.n
                    state["total"] = self.total
                    if not force and (now - state["last_emit"]) < 0.08:
                        return
                    state["last_emit"] = now
                    elapsed = max(0.001, now - self._started)
                    speed = self.n / elapsed
                    if self.total > 0:
                        ratio = min(1.0, max(0.0, self.n / self.total))
                        pct = max(2, min(94, int(round(2 + ratio * 92))))
                        dl_mb = self.n / (1024 * 1024)
                        tot_mb = self.total / (1024 * 1024)
                        spd_mb = speed / (1024 * 1024)
                        detail = (
                            f"Downloading '{size_or_id}' — "
                            f"{dl_mb:.1f} / {tot_mb:.1f} MB ({spd_mb:.1f} MB/s)"
                        )
                    else:
                        pct = 3
                        dl_mb = self.n / (1024 * 1024)
                        detail = f"Downloading '{size_or_id}' — {dl_mb:.1f} MB…"

                outer._emit_progress(
                    status="downloading",
                    model=size_or_id,
                    percent=pct,
                    downloaded_bytes=self.n,
                    total_bytes=self.total,
                    speed_bps=speed,
                    detail=detail,
                )

            def update(self, n: int | float | None = 1) -> None:
                if n:
                    self.n += int(n)
                self._report(force=(self.total > 0 and self.n >= self.total))

            def refresh(self, *args, **kwargs) -> None:
                self._report(force=False)

            def set_description(self, desc: str | None = None, refresh: bool = True) -> None:
                if desc is not None:
                    self.desc = desc

            def set_description_str(self, desc: str | None = None, refresh: bool = True) -> None:
                if desc is not None:
                    self.desc = desc

            def set_postfix(self, ordered_dict=None, refresh: bool = True, **kwargs) -> None:
                pass

            def set_postfix_str(self, s: str = "", refresh: bool = True) -> None:
                pass

            def close(self) -> None:
                self._report(force=True)

            def clear(self, *args, **kwargs) -> None:
                pass

            def display(self, *args, **kwargs) -> None:
                pass

            def reset(self, total: int | None = None) -> None:
                self.n = 0
                if total is not None:
                    self.total = int(total)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.close()

            def __iter__(self):
                if self.iterable is not None:
                    for item in self.iterable:
                        yield item
                        self.update(1)

        local_dir = huggingface_hub.snapshot_download(
            repo_id,
            allow_patterns=ALLOW_PATTERNS,
            tqdm_class=_ProgressTqdm,
        )
        total_bytes = state["total"] or state["downloaded"]
        if not total_bytes:
            model_bin = Path(local_dir) / "model.bin"
            if model_bin.exists():
                total_bytes = model_bin.stat().st_size
        return str(local_dir), int(total_bytes)

    def _get_model(self):
        with self._lock:
            if self._model is None or self.loaded_model_size != self.cfg.model:
                from faster_whisper import WhisperModel

                target_model = self.cfg.model
                log.info("loading whisper model '%s' (cpu/int8)", target_model)
                started = time.monotonic()
                try:
                    model_dir, total_bytes = self._ensure_model_downloaded(target_model)
                    self._emit_progress(
                        status="loading",
                        model=target_model,
                        percent=96,
                        downloaded_bytes=total_bytes,
                        total_bytes=total_bytes,
                        speed_bps=0.0,
                        detail=f"Loading '{target_model}' into CPU int8 memory…",
                    )
                    self._model = WhisperModel(
                        model_dir,
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=max(2, (threading.active_count() or 4)),
                    )
                    self.loaded_model_size = target_model
                    elapsed = time.monotonic() - started
                    log.info("whisper model '%s' loaded in %.1fs", target_model, elapsed)
                    self._emit_progress(
                        status="ready",
                        model=target_model,
                        percent=100,
                        downloaded_bytes=total_bytes,
                        total_bytes=total_bytes,
                        speed_bps=0.0,
                        detail=f"✓ '{target_model}' model verified & warm ({elapsed:.1f}s)",
                    )
                except Exception as exc:
                    self._emit_progress(
                        status="error",
                        model=target_model,
                        percent=0,
                        detail=f"Whisper failed to load '{target_model}': {exc}",
                    )
                    raise
            return self._model

    def is_ready(self) -> bool:
        return self._model is not None and self.loaded_model_size == self.cfg.model

    def transcribe_file(self, path: str | Path, language: str | None = None) -> dict:
        """Transcribe any audio/video file. Returns {text, duration, language}."""
        path = Path(path)
        if not path.exists() or path.stat().st_size == 0:
            raise TranscriptionError(f"audio file missing or empty: {path}")
        wav = self._to_wav(path)
        try:
            return self.transcribe_wav(wav, language)
        finally:
            wav.unlink(missing_ok=True)

    def transcribe_wav(self, wav_path: Path, language: str | None = None) -> dict:
        lang = language or (None if self.cfg.language in ("", "auto") else self.cfg.language)
        model = self._get_model()
        audio = self._load_wav16k(wav_path)
        started = time.monotonic()
        try:
            segments, info = model.transcribe(audio, language=lang, vad_filter=True)
            parts = [seg.text.strip() for seg in segments]
        except Exception as exc:
            raise TranscriptionError(f"whisper failed: {exc}") from exc
        text = " ".join(p for p in parts if p).strip()
        log.info(
            "transcribed %.1fs audio -> %d chars in %.1fs",
            info.duration or 0, len(text), time.monotonic() - started,
        )
        return {"text": text, "duration": info.duration or 0.0, "language": info.language or ""}

    @staticmethod
    def _load_wav16k(path: Path):
        """Decode a 16 kHz mono WAV to float32 without going through PyAV
        (av's decode API churns between releases; ffmpeg + wave does not)."""
        import wave

        import numpy as np

        with wave.open(str(path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getframerate() != 16000:
                raise TranscriptionError("expected 16 kHz mono wav from ffmpeg")
            frames = wf.readframes(wf.getnframes())
        return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    def _to_wav(self, path: Path) -> Path:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise TranscriptionError("ffmpeg not found on PATH — required for audio conversion")
        out = Path(tempfile.mkstemp(suffix=".wav", prefix="fleeting-")[1])
        out.unlink(missing_ok=True)
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
               "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(out)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=600)
        except subprocess.TimeoutExpired as exc:
            out.unlink(missing_ok=True)
            raise TranscriptionError("ffmpeg conversion timed out") from exc
        if proc.returncode != 0 or not out.exists():
            err = proc.stderr.decode(errors="replace")[-300:]
            raise TranscriptionError(f"ffmpeg failed: {err}")
        return out


def create_transcriber(cfg: TranscribeConfig) -> Transcriber:
    return Transcriber(cfg)
