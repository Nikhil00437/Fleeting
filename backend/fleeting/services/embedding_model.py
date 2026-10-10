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


def resolve_embedding_endpoint(cfg: LLMConfig) -> tuple[str, str]:
    """The (provider, base_url) an embedding request actually goes to.

    Chat and embedding are separate resources: a 9B chat model and a 300M
    embedder rarely share a process, and one of them is often a desktop app
    that gets closed. Both may therefore be overridden, and *both* are needed —
    the provider selects the request dialect as well as the host, and the two
    can disagree. LM Studio answers Ollama's `/api/embeddings` with HTTP 200
    and an `{"error": ...}` body, so a wrong dialect is not a crash but a
    silent fall back to hash vectors.

    Empty settings mean "whatever chat uses", which is every config that
    predates these fields.
    """
    provider = (getattr(cfg, "embedding_provider", "") or "").strip().lower()
    base = (getattr(cfg, "embedding_base_url", "") or "").strip()
    if not provider and not base:
        return (getattr(cfg, "provider", "") or "").lower(), getattr(cfg, "base_url", "")
    if not provider:
        # A URL was given without a dialect. Only Ollama speaks /api/embed*.
        # Anything else on a non-Ollama port is an OpenAI-compatible server.
        host = base.rstrip("/")
        inferred = "ollama" if host.endswith(":11434") else "custom"
        return inferred, base
    return provider, base or getattr(cfg, "base_url", "")