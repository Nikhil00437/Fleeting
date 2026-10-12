"""#396 a dev-mode switch that fails calls at random.

Reaches for this when a problem only appears intermittently: a capture that
fails once in ten, an assistant reply that times out only under load. Watching
it happen in the real app is the point — a test can force a failure but cannot
tell you how the UI feels when failures are *intermittent*.

Deliberately narrow. It injects at two choke points and nowhere else:

  - `llm.request_chat`, through which every chat call already passes, and
  - `Transcriber.transcribe_file`, the single door to the model.

Bypassing a choke point would mean the switch lies about coverage, so the two
call sites are a `maybe_fail` each and nothing else changes.

Safety, in order of importance:

  - **Off unless `FLEETING_CHAOS` is set.** No default, no config key, no
    "development mode" that a production install could trip over. Every call
    site is `if CHAOS.active(...)`, which is one attribute read when unset.
  - **Seeded.** `FLEETING_CHAOS_SEED` makes a session reproducible; without
    one the seed is logged at the first injection so a note that failed can be
    traced back to the run.
  - **Loud.** Every injection logs at WARNING with what was dropped and why,
    so a chaos run never leaves you guessing whether a failure was real.

Nothing here is imported by tests. `test_chaos.py` covers the switch itself;
the failure behaviour it exercises is covered deterministically in
`test_processor_failures.py`, which is the half that has to keep working.
"""

from __future__ import annotations

import logging
import os
import random

log = logging.getLogger("fleeting.chaos")

# Targets. Adding one means adding it to `maybe_fail` call sites too — a target
# nothing calls is a setting that lies.
TARGETS = ("llm", "whisper")

# "llm=0.3,whisper=0.5" -> {"llm": 0.3, "whisper": 0.5}
def parse(spec: str) -> dict[str, float]:
    rates: dict[str, float] = {}
    for part in (spec or "").split(","):
        name, _, raw = part.partition("=")
        name = name.strip()
        if name not in TARGETS:
            continue
        try:
            rate = float(raw)
        except ValueError:
            continue
        if rate > 0:
            rates[name] = min(rate, 1.0)
    return rates


def _spec() -> dict[str, float]:
    # Read per call rather than at import: tests set the variable after the
    # module is loaded, and a switch frozen at import is a switch you cannot
    # turn on without restarting.
    return parse(os.environ.get("FLEETING_CHAOS", ""))


_rng: random.Random | None = None
_seed: int | None = None


def _rng_for(spec: dict[str, float]) -> random.Random:
    global _rng, _seed
    if _rng is None:
        _seed = os.environ.get("FLEETING_CHAOS_SEED")
        _seed = int(_seed) if _seed and _seed.isdigit() else random.randrange(1 << 30)
        _rng = random.Random(_seed)
        log.warning("chaos enabled %s seed=%d — reproducible via FLEETING_CHAOS_SEED", spec, _seed)
    return _rng


def active(target: str) -> bool:
    """True when this call should fail. The whole cost when chaos is off."""
    spec = _spec()
    if not spec:
        return False
    rate = spec.get(target)
    if not rate:
        return False
    return _rng_for(spec).random() < rate


def maybe_fail(target: str, what: str) -> None:
    """Raise if the dice say so.

    The raised exception is worded exactly like a real failure, on purpose. A
    chaos run exists to reproduce conditions you cannot otherwise see, and an
    error string that says "chaos" changes them: downstream code branching on
    the message takes a different path, and a user staring at "chaos: injected
    transcription failure" in their inbox learns nothing about what their
    machine would really do. The WARNING log is where the truth belongs — it is
    read by whoever turned the switch on, not by the note's owner.
    """
    if active(target):
        log.warning("CHAOS: failing %s (%s)", what, target)
        if target == "llm":
            from .services.llm import LLMUnavailable

            raise LLMUnavailable("request failed: ConnectionError: connection refused")
        from .services.transcribe import TranscriptionError

        raise TranscriptionError("ffmpeg failed: conversion failed")


def describe() -> str:
    """For /api/health or a log line, so a running app says it is in chaos."""
    spec = _spec()
    if not spec:
        return "off"
    return ", ".join(f"{k}={v:g}" for k, v in sorted(spec.items()))