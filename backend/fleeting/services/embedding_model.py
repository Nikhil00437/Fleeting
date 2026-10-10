"""The embedding model name, resolved in exactly one place.

There used to be two resolvers — `embed_text_with_model` and the
`_embedding_status` helper in routers/system.py — that had to agree and
already disagreed about the non-ollama default. When they disagree,
`/api/health` reports a model that never embedded anything, every row
counts as stale, and `_maybe_backfill_embeddings` retries the whole corpus
on every boot forever.
"""

from __future__ import annotations

from ..config import LLMConfig

# Used when the user has configured neither a dedicated embedding model nor a
# general one — i.e. the defaults that predate #92's per-role models.
PROVIDER_DEFAULT_EMBEDDING = {
    "ollama": "nomic-embed-text",
    "lmstudio": "text-embedding-3-small",
    "custom": "text-embedding-3-small",
}


def resolve_embedding_model(cfg: LLMConfig) -> str:
    """Which model embeddings are requested from.

    Dedicated setting first, then the general model (so existing configs keep
    working), then the provider default. Never returns None — callers store
    this string on every embedding row and compare against it to decide what
    needs migrating, so an empty string here would make every row "stale"
    forever.

    Reads the fields with getattr because config-like objects genuinely exist
    in this codebase that are not a full LLMConfig: the tests build
    SimpleNamespace stubs, and `main._maybe_backfill_embeddings` builds an `_St`
    holder. A missing attribute means "not configured", which is exactly what
    it means here.
    """
    for candidate in (
        (getattr(cfg, "embedding_model", "") or "").strip(),
        (getattr(cfg, "model", "") or "").strip(),
    ):
        if candidate:
            return candidate
    provider = (getattr(cfg, "provider", "") or "").lower()
    return PROVIDER_DEFAULT_EMBEDDING.get(provider, "nomic-embed-text")