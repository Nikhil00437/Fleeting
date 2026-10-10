"""One resolver for the embedding model name, and the prefix rules.

EmbeddingGemma 2 (and its family) is trained with task instructions: queries
and documents are embedded with different prefixes. `default_prompt_name` is
null in its sentence-transformers config, so there is no safe default — a
note embedded with the document prefix and a query embedded with none land in
different places in the same vector space, and every search quietly returns
noise.

The prefixes are the literal strings from the model's
`config_sentence_transformers.json`, not invented here.
"""

from __future__ import annotations

from ..config import LLMConfig
from .embedding_model import resolve_embedding_model

# query:  "task: search result | query: "
# document: "title: none | text: "  — it has a title slot, and Fleeting has a
# real title, so we fill it rather than sending the literal "none".
QUERY_PREFIX = "task: search result | query: "
DOCUMENT_PREFIX = "title: {title} | text: "

# Which models need the distinction. A model with no task-prompt training
# would just see stray text, so it is opt-in per model rather than global.
TASK_PROMPT_MODELS = frozenset({"embeddinggemma-2", "embeddinggemma"})


def is_task_prompt_model(model: str) -> bool:
    """True when `model` is trained with the search/document task prefixes.

    Matched on the model name *without its tag*, because Ollama users write
    `embeddinggemma-2:270m` as often as `embeddinggemma-2`.
    """
    base = (model or "").split(":")[0].strip().lower()
    return base in TASK_PROMPT_MODELS


def embedding_payload(
    text: str,
    model: str,
    *,
    kind: str = "document",
    title: str = "",
) -> str:
    """What actually goes over the wire for `text`.

    Documents get their real title in the title slot; queries get the query
    prefix. Models without task-prompt training get the text untouched.
    """
    if kind == "query":
        return f"{QUERY_PREFIX}{text}" if is_task_prompt_model(model) else text
    if not is_task_prompt_model(model):
        return text
    clean = (title or "").strip() or "none"
    return f"{DOCUMENT_PREFIX.format(title=clean)}\n{text}"


def resolve(cfg: LLMConfig) -> str:
    """Re-exported so callers have one import for the whole decision."""
    return resolve_embedding_model(cfg)