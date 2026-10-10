"""Batched embedding calls, for the backfill and any whole-corpus rebuild.

`/api/embed` (Ollama, llama.cpp, LM Studio) accepts an array and returns one
vector per input. The legacy `/api/embeddings` takes a single `prompt`, which
is what Fleeting still calls — so migrating a corpus is one HTTP round trip per
note. On 27 notes that is irrelevant; on a few thousand it is the difference
between a minute and an hour.

Each note gets its own payload (the document prefix carries its title), so
batching is over *inputs*, not over a shared string.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from .embedding_model import resolve_embedding_endpoint, resolve_embedding_model
from .embedding_prompt import embedding_payload
from .llm import auth_headers

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database

log = logging.getLogger("fleeting.embeddings")

# Big enough to amortise the connection, small enough that a partial failure
# loses little work. Above ~64 the request/response bodies get unwieldy and
# some servers start timing out.
DEFAULT_BATCH = 32


def _normalize(vec: list[float]) -> list[float]:
    n = sum(x * x for x in vec) ** 0.5
    return [x / n for x in vec] if n > 0.0 else list(vec)


def embed_batch(
    texts: list[str], cfg: Config, *, kind: str = "document", titles: list[str] | None = None
) -> list[list[float] | None]:
    """Embed many texts in one request. A failure yields None per item, not an exception.

    A batch is not all-or-nothing: one malformed input must not cost the other
    31 notes their vectors, so callers can retry just the gaps.
    """
    if not texts:
        return []
    if cfg is None or cfg.llm.provider == "none":
        return [None] * len(texts)

    provider, url = resolve_embedding_endpoint(cfg.llm)
    base = url.rstrip("/")
    model = resolve_embedding_model(cfg.llm)
    titles = titles or [""] * len(texts)

    if provider == "ollama":
        url = f"{base}/api/embed"
        payload: dict[str, Any] = {"model": model, "input": texts}
    else:
        url = f"{base}/v1/embeddings"
        payload = {
            "model": model,
            "input": [
                embedding_payload(t, model, kind=kind, title=ti)
                for t, ti in zip(texts, titles)
            ],
        }

    try:
        with httpx.Client(
            timeout=float(cfg.llm.timeout_secs), headers=auth_headers(cfg.llm)
        ) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        # Consistent with the single-text path: warn, never raise. A silent
        # downgrade is exactly what the health panel exists to surface.
        log.warning(
            "Batched embedding failed (%s: %s) — %d note(s) keep their old vectors",
            type(exc).__name__,
            exc,
            len(texts),
        )
        return [None] * len(texts)

    vectors = _extract(data, len(texts))
    return [_normalize(v) if v else None for v in vectors]


def _extract(data: dict, expected: int) -> list[list[float] | None]:
    """Pull vectors out of either response shape, padded to `expected`."""
    out: list[list[float] | None] = [None] * expected
    raw = data.get("embeddings")  # /api/embed (ollama)
    if raw is None:
        raw = [item.get("embedding") for item in data.get("data") or []]  # /v1/embeddings
    if not isinstance(raw, list):
        return out
    for i, vec in enumerate(raw[:expected]):
        if isinstance(vec, list) and vec:
            out[i] = [float(x) for x in vec]
    return out


def reembed_corpus(
    db: Database,
    cfg: Config,
    *,
    model: str | None = None,
    batch: int = DEFAULT_BATCH,
    on_progress: Any = None,
) -> int:
    """Re-embed every active note in batches. Returns the count rewritten.

    Reuses `embedding_text_for` so batched and one-at-a-time paths build
    byte-identical payloads — a corpus where half the vectors were built a
    different way is a corpus where half the similarity scores are wrong.
    """
    from .embeddings import embedding_text_for, pack_vector

    target = model or resolve_embedding_model(cfg.llm)
    rows = db.execute(
        "SELECT * FROM notes WHERE trashed_at IS NULL AND archived = 0"
    ).fetchall()

    pending: list[dict] = []
    for row in rows:
        note = dict(row)
        if not embedding_text_for(note):
            continue
        pending.append(note)

    done = 0
    for start in range(0, len(pending), batch):
        chunk = pending[start : start + batch]
        vectors = embed_batch(
            [embedding_text_for(n) for n in chunk],
            cfg,
            kind="document",
            titles=[str(n.get("title") or "") for n in chunk],
        )
        for note, vec in zip(chunk, vectors):
            if vec is None:
                continue
            db.upsert_note_embedding(
                note["id"], pack_vector(vec), len(vec), target
            )
            done += 1
        if on_progress is not None:
            on_progress(done)
    return done