"""#95 reprocess the whole corpus after a model or dimension change.

Re-embedding is derived data: throw it away and the notes are unchanged, so it
is always safe to redo and needs no confirmation. Re-running enrichment is
different — it overwrites the title, summary and tags the user may have been
editing all afternoon, and `note_versions` cannot tell a pipeline edit from a
human one, so the destructive half is opt-in rather than inferred.

Kept as one pass rather than a job queue: a single-user local app has one
corpus and one process, and a queue would add a scheduler to a job that runs
once after a settings change.
"""

from __future__ import annotations

import logging
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING, Any

from .tags_vocab import apply_preferred_tags, preferred_tags, tag_prompt

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database
    from ..events import EventBus

log = logging.getLogger("fleeting.reprocess")

SCOPES = ("embeddings", "everything")

# Only notes that can be enriched are worth the loop; a note with no body has
# nothing to hand the model and would spend a call to get the same answer.
_BODY_LIMIT = 20_000


async def apply_enrichment(
    db: Database,
    cfg: Config,
    note: dict,
    enriched: dict,
    *,
    model: str = "",
) -> dict:
    """Write one note's enrichment, exactly as #20's single-note regenerate does.

    Deliberately the only place this happens. A bulk reprocess that drifted
    from the single-note path would produce different notes depending on
    whether the user pressed one button or five hundred.
    """
    fields: dict[str, Any] = {
        "title": enriched["title"],
        "summary": enriched["summary"],
        # #257 enforced here too, so a bulk re-enrich lands in the same
        # vocabulary as an automatic one.
        "tags": apply_preferred_tags(enriched["tags"], preferred_tags(cfg)),
        "review_state": "enriched",
        "enrich_confidence": enriched.get("confidence"),
    }
    if model:
        fields["enrich_model"] = model
    out = db.update_note(str(note["id"]), fields)
    if out is None:
        return {}
    from . import markdown

    try:
        markdown.sync_note(cfg.paths, out)
    except Exception:
        log.warning("vault sync failed after reprocessing %s", note["id"], exc_info=True)
    return out


def validate_reprocess(cfg: Config, scope: str, confirm: bool) -> str | None:
    """The reason this reprocess is not allowed, or None when it is.

    Called twice on purpose: once by the endpoint, so an invalid request is
    rejected synchronously rather than failing inside a background task the
    caller has already been told succeeded, and once inside the job itself so
    the rule cannot be bypassed by another caller.
    """
    if scope not in SCOPES:
        return f"unknown scope '{scope}'. Use one of: {', '.join(SCOPES)}"
    if scope == "everything" and not confirm:
        return (
            "Re-running enrichment overwrites the title, summary and tags. "
            "Send confirm=true to proceed, or use scope='embeddings' to only rebuild vectors."
        )
    if scope == "everything" and cfg.llm.provider == "none":
        return "no LLM provider configured, so there is nothing to enrich"
    return None


async def reprocess_corpus(
    db: Database,
    cfg: Config,
    bus: EventBus,
    *,
    scope: str = "embeddings",
    confirm: bool = False,
) -> dict:
    """Re-embed (and optionally re-enrich) every active note.

    Returns a result dict rather than raising: progress is published as it goes
    and the caller needs the final numbers, and one note failing must not lose
    the count for the rest.
    """
    reason = validate_reprocess(cfg, scope, confirm)
    if reason:
        return {"ok": False, "error": reason}

    from .embedding_batch import reembed_corpus

    rows = db.execute(
        "SELECT id, title, raw_text FROM notes WHERE trashed_at IS NULL AND archived = 0"
    ).fetchall()
    notes = [dict(r) for r in rows]
    total = len(notes)

    bus.publish("reprocess.progress", {"done": 0, "total": total, "scope": scope, "started": True})

    reembedded = reembed_corpus(db, cfg, batch=16)

    enriched = failed = 0
    for index, note in enumerate(notes, start=1):
        if scope == "everything":
            body = (note.get("raw_text") or "")[:_BODY_LIMIT]
            if not body.strip():
                continue
            try:
                llm_cfg = cfg.llm
                if cfg.llm.enrich_model:
                    llm_cfg = dc_replace(cfg.llm, model=cfg.llm.enrich_model)
                from .fewshot import build_few_shot
                from .llm import enrich_chain
                from .tags_vocab import tag_prompt

                result = await enrich_chain(
                    body,
                    llm_cfg,
                    few_shot=build_few_shot(db),
                    tag_vocab=tag_prompt(preferred_tags(cfg)),
                )
                if await apply_enrichment(db, cfg, note, result, model=cfg.llm.enrich_model):
                    enriched += 1
            except Exception as exc:
                failed += 1
                log.warning("reprocess: enrichment failed for %s: %s", note["id"], exc)
                bus.publish(
                    "reprocess.progress",
                    {
                        "done": index - 1,
                        "total": total,
                        "scope": scope,
                        "note_id": note["id"],
                        "title": note.get("title"),
                        "error": str(exc)[:120],
                    },
                )
                continue

        bus.publish(
            "reprocess.progress",
            {
                "done": index,
                "total": total,
                "scope": scope,
                "note_id": note["id"],
                "title": note.get("title"),
            },
        )

    out = {
        "ok": True,
        "scope": scope,
        "total": total,
        "reembedded": reembedded,
    }
    if scope == "everything":
        out.update({"enriched": enriched, "failed": failed})
    bus.publish("reprocess.progress", {**out, "finished": True})
    return out
