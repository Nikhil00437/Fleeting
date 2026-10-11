"""#264 a local benchmark of models against your own past notes.

What this measures is *faithfulness*, and the name matters. A generated title
is scored on how much of it is supported by the note it describes, using the
same token-overlap rule #263 uses to hold a summary back. That is a real,
bounded, inspectable measure. "Is this good writing" is not, and an LLM judge
cannot answer it without importing its own preferences as the answer key.

Two things this deliberately does not do:

- It never writes. Comparing models by rewriting your notes would destroy the
  corpus being measured, and a benchmark that edits your data is not one you
  would run twice.
- It never sends a sensitive note. #26 keeps those bodies in the app; a
  benchmark that quietly included them would breach that in the name of
  measuring a model.

The comparison is only meaningful because every model is run against the same
sampled notes. Different notes per model would make the means incomparable,
which is the usual way a benchmark like this produces a confident wrong answer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING, Any

from .claims import supported_ratio

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database
    from ..events import EventBus

log = logging.getLogger("fleeting.benchmark")

DEFAULT_SAMPLE = 8

# A note longer than this is not what anyone re-enriches, and a benchmark over
# transcripts measures truncation rather than the model.
_MAX_BODY = 2000


def score_output(enriched: dict, source: str) -> dict[str, Any]:
    """How much of a generated title/summary the note itself supports.

    Returns the ratio *and* the words that carried nothing, because a score
    the user cannot interrogate is a score they have to take on faith — and
    "which words did it invent?" is the first question anyone asks.
    """
    title = str((enriched or {}).get("title") or "")
    summary = str((enriched or {}).get("summary") or "")

    parts: list[tuple[float, str]] = []
    if title.strip():
        parts.append((supported_ratio(title, source), "title"))
    for sentence in _sentences(summary):
        if sentence.strip():
            parts.append((supported_ratio(sentence, source), "summary"))

    if not parts:
        # Saying nothing must not score as perfect; an average over no
        # sentences is the failure mode of every naive scorer.
        return {
            "score": 0.0,
            "title_ratio": 0.0,
            "summary_ratio": 0.0,
            "ungrounded": [],
            "sentences": 0,
        }

    scores = [p for p, _ in parts]
    title_parts = [p for p, kind in parts if kind == "title"]
    summary_parts = [p for p, kind in parts if kind == "summary"]
    ungrounded = [
        sentence.strip()
        for sentence, (ratio, _kind) in zip(
            [title] + _sentences(summary), parts
        )
        if ratio < 0.7
    ]

    return {
        "score": round(sum(scores) / len(scores), 4),
        "title_ratio": round(
            sum(title_parts) / len(title_parts) if title_parts else 0.0, 4
        ),
        "summary_ratio": round(
            sum(summary_parts) / len(summary_parts) if summary_parts else 0.0, 4
        ),
        "ungrounded": ungrounded[:5],
        "sentences": len(parts),
    }


def _sentences(text: str) -> list[str]:
    out, buf = [], []
    for char in text or "":
        if char in ".!?\n":
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(char)
    if buf:
        out.append("".join(buf))
    return out


def sample_notes(db: "Database", *, limit: int = DEFAULT_SAMPLE) -> list[dict]:
    """Recent notes worth re-enriching, in a fixed order.

    Most recent rather than random: a random sample cannot be reproduced, and a
    benchmark you cannot re-run is a number you cannot argue with. Trashed,
    archived and sensitive notes are excluded — the last one because #26 does
    not bend for measurement.
    """
    rows = db.execute(
        "SELECT * FROM notes WHERE trashed_at IS NULL AND archived = 0 "
        "AND (sensitive = 0 OR sensitive IS NULL) "
        "AND (generated = 0 OR generated IS NULL) "
        "AND raw_text IS NOT NULL AND TRIM(raw_text) != '' "
        "ORDER BY created_at DESC, id ASC LIMIT ?",
        (max(1, int(limit)),),
    ).fetchall()
    return [dict(r) for r in rows]


def _models_to_test(cfg: "Config", models: list[str] | None) -> list[str]:
    """Explicit list, or the models already configured for the fallback chain."""
    if models:
        return [m for m in (str(m).strip() for m in models) if m]
    out = [cfg.llm.model]
    for raw in (cfg.llm.fallback_models or "").split(","):
        name = raw.strip()
        if name and name not in out:
            out.append(name)
    return [m for m in out if m]


async def benchmark_models(
    db: "Database",
    cfg: "Config",
    bus: "EventBus",
    *,
    models: list[str] | None = None,
    sample: int = DEFAULT_SAMPLE,
) -> dict:
    """Score each model on the same notes. Never writes; never sees a sensitive note."""
    names = _models_to_test(cfg, models)
    if cfg.llm.provider == "none":
        return {"results": [], "error": "no LLM provider configured"}

    notes = sample_notes(db, limit=sample)
    results: list[dict[str, Any]] = []

    for model in names:
        rows: list[dict[str, Any]] = []
        started = time.monotonic()
        failed = ""
        for note in notes:
            body = (note.get("raw_text") or "")[:_MAX_BODY]
            if not body.strip():
                continue
            try:
                from .llm import enrich_chain

                llm_cfg = dc_replace(cfg.llm, model=model)
                enriched = await enrich_chain(body, llm_cfg)
                scored = score_output(enriched, body)
                rows.append(
                    {
                        "note_id": note["id"],
                        "title": note.get("title") or "",
                        **scored,
                    }
                )
            except Exception as exc:
                # One note failing is not the model's fault and must not lose
                # the model's other scores.
                failed = str(exc)[:200]
                log.info("benchmark: %s failed on note %s: %s", model, note["id"], exc)

        elapsed_ms = (time.monotonic() - started) * 1000
        mean = round(sum(r["score"] for r in rows) / len(rows), 4) if rows else 0.0
        results.append(
            {
                "model": model,
                "notes": len(rows),
                "mean_score": mean,
                "ms_per_note": round(elapsed_ms / len(rows), 1) if rows else 0.0,
                "error": failed,
                "rows": rows,
            }
        )

    return {
        "sampled": len(notes),
        "models": names,
        "results": results,
        "metric": "content-word support against the note itself",
    }