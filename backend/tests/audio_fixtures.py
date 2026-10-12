"""#393 audio and video fixtures, generated rather than committed.

The version item asks for "a fixture library of audio, videos and edge-case
notes". Committing `.webm` blobs would be the obvious reading and the wrong
one: they are opaque, they bloat the repo, and — worse — nothing about them is
assertable. A 0.6-second 8 kHz stereo file and a 0.6-second 16 kHz mono file
differ only in two header fields, and the second one has to be *wrong* on
purpose to exercise `_load_wav16k`'s channel check.

So the fixtures are generated. `wave` is in the standard library and ffmpeg is
already a hard requirement of the transcription pipeline, so this needs no
binary in the repo, no extra dependency, and every fixture is inspectable.

What is deliberately absent: anything that needs a real whisper model. A test
that downloads `base.en` would be slow, would touch the network, and would
assert on a transcript nobody can pin. `FakeWhisper` stands in, which tests the
code under test — argument assembly, word timestamps, replacements, punctuation
— rather than the model.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path


def write_wav(
    path: Path,
    *,
    seconds: float = 0.4,
    rate: int = 16_000,
    channels: int = 1,
    freq: float = 440.0,
) -> Path:
    """A tone, as a real PCM WAV. Mono 16 kHz by default — what ffmpeg emits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        out = bytearray()
        for n in range(frames):
            # A quiet sine. Amplitude is low on purpose so nothing downstream
            # mistakes the fixture for clipping.
            value = int(8000 * math.sin(2 * math.pi * freq * n / rate))
            packed = struct.pack("<h", value)
            out += packed * channels
        wf.writeframes(bytes(out))
    return path


def write_empty(path: Path) -> Path:
    """Zero bytes. `_to_wav` and `transcribe_file` both special-case this."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def write_video(path: Path, *, seconds: float = 0.6) -> Path | None:
    """A tiny MP4 with a video and an audio track, or None without ffmpeg.

    Built by ffmpeg's own synthetic sources rather than committed, so there is
    no binary to keep in sync. Returns None instead of skipping so the test
    can assert that the fixture is missing and say why.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=64x64:rate=10:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


class FakeSegment:
    """What `faster_whisper` yields: text plus optional word timings (#88)."""

    def __init__(self, text: str, start: float, end: float, words: list | None = None):
        self.text = text
        self.start = start
        self.end = end
        self.words = words


class FakeWord:
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end


class FakeInfo:
    language = "en"
    language_probability = 0.99
    duration = 1.0


class FakeWhisper:
    """Stands in for `faster_whisper.WhisperModel`.

    Records the kwargs it was called with, so tests can assert on how the
    pipeline configures the model — `vad_filter`, `initial_prompt`,
    `task="translate"` — which is otherwise only visible by reading the source.
    """

    def __init__(self, segments: list[FakeSegment] | None = None):
        self.segments = segments if segments is not None else [
            FakeSegment(" hello there ", 0.0, 1.0, [FakeWord(" hello", 0.0, 0.5)]),
            FakeSegment(" general kenobi ", 1.0, 2.0, [FakeWord(" kenobi", 1.0, 1.9)]),
        ]
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        return iter(self.segments), FakeInfo()


def attach(transcriber, model: FakeWhisper | None = None) -> FakeWhisper:
    """Give a `Transcriber` a fake model without loading whisper.

    `_get_model` only loads when `self._model` is None or the configured model
    changed, so setting both fields is enough — no download, no network, and
    the test runs in milliseconds.
    """
    fake = model or FakeWhisper()
    transcriber._model = fake
    transcriber.loaded_model_size = transcriber.cfg.model
    return fake