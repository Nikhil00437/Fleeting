"""Vector embeddings, serialization, and local hash vectorizer service.

Provides float vector packing/unpacking, cosine similarity, a deterministic
384-dimensional offline LocalHashVectorizer, remote provider embedding with
graceful local fallback, and database persistence helpers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import struct
from collections import Counter
from typing import TYPE_CHECKING, Callable

import httpx

from .llm import auth_headers

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database

log = logging.getLogger("fleeting.embeddings")


def pack_vector(vec: list[float]) -> bytes:
    """Pack a list of 32-bit floats into raw bytes (IEEE 754 float32)."""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> list[float]:
    """Unpack raw bytes into a list of 32-bit floats."""
    num_floats = len(blob) // 4
    return list(struct.unpack(f"{num_floats}f", blob))


def cosine_similarity(u: list[float], v: list[float]) -> float:
    """Compute cosine similarity between two float vectors.

    Safe against small floating-point drift and automatically normalizes non-unit vectors.
    Returns a float in [-1.0, 1.0].
    """
    if len(u) != len(v) or not u:
        return 0.0
    dot = 0.0
    norm_u_sq = 0.0
    norm_v_sq = 0.0
    for a, b in zip(u, v):
        dot += a * b
        norm_u_sq += a * a
        norm_v_sq += b * b
    if norm_u_sq <= 0.0 or norm_v_sq <= 0.0:
        return 0.0
    sim = dot / (math.sqrt(norm_u_sq) * math.sqrt(norm_v_sq))
    return max(-1.0, min(1.0, float(sim)))


class LocalHashVectorizer:
    """Deterministic 384-dimensional sub-word / character 3-gram feature hashing vectorizer.

    100% offline, zero-network, and fast fallback vectorizer for semantic recall.
    """

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def tokenize(self, text: str) -> list[str]:
        words = re.findall(r"[\w\u0900-\u097F]+", text.lower())
        tokens: list[str] = list(words)
        for w in words:
            if len(w) >= 3:
                for i in range(len(w) - 2):
                    tokens.append(w[i : i + 3])
        return tokens

    def embed(self, text: str) -> list[float]:
        tokens = self.tokenize(text)
        if not tokens:
            return [0.0] * self.dimensions

        counts = Counter(tokens)
        vec = [0.0] * self.dimensions
        for tok, count in counts.items():
            digest = hashlib.md5(tok.encode("utf-8"), usedforsecurity=False).digest()
            bucket = int.from_bytes(digest, "big") % self.dimensions
            # Sign determined by highest bit of hash: +1.0 if bit is 1, -1.0 if 0
            sign = 1.0 if (digest[0] & 0x80) else -1.0
            weight = sign * (1.0 + math.log(count))
            vec[bucket] += weight

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]
        return vec


def embed_text_with_model(
    text: str, cfg: Config | None = None
) -> tuple[list[float], str]:
    """Generate an embedding vector and model name for text, falling back to LocalHashVectorizer."""
    if not text or not text.strip():
        return LocalHashVectorizer().embed(""), "local-hash-384"

    if cfg is not None and getattr(cfg, "llm", None) and cfg.llm.provider != "none":
        provider = cfg.llm.provider.lower()
        base_url = cfg.llm.base_url.rstrip("/")
        timeout = min(float(cfg.llm.timeout_secs), 5.0)
        try:
            with httpx.Client(timeout=timeout, headers=auth_headers(cfg.llm)) as client:
                if provider == "ollama":
                    model = cfg.llm.model or "nomic-embed-text"
                    resp = client.post(
                        f"{base_url}/api/embeddings",
                        json={"model": model, "prompt": text},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    vec = data.get("embedding")
                    if isinstance(vec, list) and vec:
                        norm = math.sqrt(sum(x * x for x in vec))
                        if norm > 0.0:
                            vec = [x / norm for x in vec]
                        return [float(x) for x in vec], model
                elif provider in ("lmstudio", "openai"):
                    model = cfg.llm.model or "text-embedding-3-small"
                    resp = client.post(
                        f"{base_url}/v1/embeddings",
                        json={"model": model, "input": text},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("data")
                    if isinstance(items, list) and items and "embedding" in items[0]:
                        vec = items[0]["embedding"]
                        if isinstance(vec, list) and vec:
                            norm = math.sqrt(sum(x * x for x in vec))
                            if norm > 0.0:
                                vec = [x / norm for x in vec]
                            return [float(x) for x in vec], model
        except Exception as exc:
            # WARNING, not DEBUG: the app runs at INFO, so a silent downgrade
            # means the user never learns their semantic index is not real.
            log.warning(
                "Remote embedding failed (%s: %s) — falling back to the offline "
                "local-hash-384 vector; semantic search will be lexical-only until "
                "the LLM is reachable",
                type(exc).__name__,
                exc,
            )

    return LocalHashVectorizer().embed(text), "local-hash-384"


def embed_text(text: str, cfg: Config | None = None) -> list[float]:
    """Generate a vector for text using configured provider or local fallback."""
    vec, _ = embed_text_with_model(text, cfg)
    return vec


def embed_note(
    note: dict | sqlite3.Row, db: Database, cfg: Config | None = None
) -> list[float] | None:
    """Compose note content, compute embedding, upsert into database, and return vector.

    Returns None if the note has no textual content.
    """
    if not isinstance(note, dict):
        note = dict(note)

    title = (note.get("title") or "").strip()
    summary = (note.get("summary") or "").strip()
    raw_text = (note.get("raw_text") or "").strip()
    raw_snippet = raw_text[:2000].strip()

    tags = note.get("tags") or []
    tags_list: list[str] = []
    if isinstance(tags, list):
        tags_list = [str(t).strip() for t in tags if str(t).strip()]
    elif isinstance(tags, str):
        tags_str = tags.strip()
        if tags_str.startswith("["):
            try:
                parsed = json.loads(tags_str)
                if isinstance(parsed, list):
                    tags_list = [str(t).strip() for t in parsed if str(t).strip()]
            except Exception:
                pass
        if not tags_list and tags_str:
            tags_list = [t.strip() for t in tags_str.split(",") if t.strip()]

    tags_formatted = " ".join(f"#{t.lstrip('#')}" for t in tags_list)

    parts: list[str] = []
    if title:
        parts.append(title)
    if tags_formatted:
        parts.append(tags_formatted)
    if summary:
        parts.append(summary)
    if raw_snippet:
        parts.append(raw_snippet)

    combined = "\n\n".join(parts).strip()
    if not combined:
        return None

    vec, model_name = embed_text_with_model(combined, cfg)
    packed = pack_vector(vec)
    db.upsert_note_embedding(note["id"], packed, len(vec), model_name)
    return vec


def backfill_embeddings(
    db: Database,
    cfg: Config | None = None,
    *,
    provider: str | None = None,
    dimensions: int | None = None,
    on_progress: "Callable[[int], None] | None" = None,
) -> int:
    """Re-embed active notes that are missing an embedding or use a stale model.

    Notes embedded by the offline `local-hash-384` fallback cannot be compared
    with vectors from a real model (different dimensionality), so switching the
    LLM on silently empties semantic search until every old note is redone.

    `provider` selects notes stored under a different model. `dimensions` is
    optional and only tightens the match: the new model's width is not known
    until something is embedded with it, so callers normally pass `provider`
    alone and let `embed_note` record whatever it gets.

    `on_progress(count)` fires after each note, for callers that need to report
    a long migration.

    Returns the count of notes (re-)embedded.
    """
    params: dict = {}
    if provider is not None:
        # Select a note when it has NO embedding, OR its embedding is not the
        # current model. Two independent NOT IN clauses OR'd together — joining
        # them with AND would exclude every stale row (both clauses are false
        # for a row that exists but is outdated).
        match = "model = :provider"
        params["provider"] = provider
        if dimensions is not None:
            match += " AND dimensions = :dims"
            params["dims"] = dimensions
        where = (
            "archived = 0 AND ("
            "id NOT IN (SELECT note_id FROM note_embeddings) OR "
            f"id NOT IN (SELECT note_id FROM note_embeddings WHERE {match})"
            ")"
        )
    else:
        where = "archived = 0 AND id NOT IN (SELECT note_id FROM note_embeddings)"
    rows = db.execute(f"SELECT * FROM notes WHERE {where}", params).fetchall()

    count = 0
    for r in rows:
        note_dict = dict(r)
        try:
            vec = embed_note(note_dict, db, cfg)
        except Exception:
            # One unreachable note must not abandon the rest of the migration.
            log.warning("backfill: could not embed note %s", note_dict.get("id"), exc_info=True)
            continue
        if vec is not None:
            count += 1
        if on_progress is not None:
            on_progress(count)
    if on_progress is not None:
        on_progress(count)
    return count
