# Implementation Plan: Semantic Recall & "Ask Fleeting" Assistant

**Date:** 2026-10-02  
**Spec:** `docs/superpowers/specs/2026-10-02-semantic-recall-ask-fleeting-design.md`  
**Sub-Project:** 4 of 4  
**Ledger:** `.superpowers/sdd/2026-10-02-semantic-recall-ask-fleeting/progress.md`

---

## Pre-flight Compatibility Matrix

| Task Pair | Produces | Consumes | Risk / Coupling | Ruling |
| :--- | :--- | :--- | :--- | :--- |
| **Task 1 $\rightarrow$ Task 2** | `note_embeddings` table & `embed_text`, `get_all_embeddings`, `cosine_similarity` | `hybrid_search` in `semantic_search.py` | Vector dimensionality and serialization consistency | Standard IEEE 754 float32 byte pack (`struct.pack`); unit tests enforce dot product equivalence |
| **Task 2 $\rightarrow$ Task 3** | `hybrid_search` function with score and snippet outputs | Multi-source context assembler in `assistant.py` | Retrieval latency and citation formatting | Limit context retrieval to top 5 notes and 5 tasks; structured citation markers `[[note:id\|title]]` |
| **Task 3 $\rightarrow$ Task 4** | `POST /api/assistant/chat` & `GET /api/assistant/suggestions` | Frontend `api.ts` client & `AssistantView.tsx` | Schema alignment for messages and source references | Strict Pydantic models (`ChatMessage`, `SourceRef`, `AssistantChatOut`) matched 1:1 with TypeScript interfaces |

---

## Detailed Task Breakdown

### Task 1: Vector Storage, SQLite Migration & Embedding Engine

**Files:**
- Modify: `backend/fleeting/db.py`
- Create: `backend/fleeting/services/embeddings.py`
- Test: `backend/tests/test_embeddings.py`

**Interfaces:**
- Produces:
  - Migration `v6` in `MIGRATIONS`: `note_embeddings` table.
  - DB methods: `upsert_note_embedding(note_id, blob, dimensions, model)`, `get_all_embeddings()`, `delete_note_embedding(note_id)`.
  - Service functions in `services/embeddings.py`:
    - `pack_vector(vec: list[float]) -> bytes`
    - `unpack_vector(blob: bytes) -> list[float]`
    - `cosine_similarity(u: list[float], v: list[float]) -> float`
    - `LocalHashVectorizer`: 384-dimensional deterministic sub-word hashing with TF-IDF weights and L2 normalization.
    - `embed_text(text: str, cfg: Config) -> list[float]` (uses remote embedding endpoint if configured, falls back to `LocalHashVectorizer`).
    - `embed_note(note: dict, db: Database, cfg: Config) -> None`
    - `backfill_embeddings(db: Database, cfg: Config) -> int`

**Steps:**
1. Write unit tests in `backend/tests/test_embeddings.py` testing packing/unpacking, cosine similarity, deterministic hash vectorizer similarity, remote fallback, and database upsert/retrieval.
2. Add migration `v6` to `MIGRATIONS` in `backend/fleeting/db.py` and implement embedding DB helpers.
3. Implement `backend/fleeting/services/embeddings.py`.
4. Run: `cd backend && uv run pytest tests/test_embeddings.py`.
5. Commit: `feat(embeddings): implement vector storage, local hash vectorizer, and embedding service`.

---

### Task 2: Hybrid Search Engine & Search API Enhancements

**Files:**
- Create: `backend/fleeting/services/semantic_search.py`
- Modify: `backend/fleeting/routers/search.py`
- Test: `backend/tests/test_semantic_search.py`

**Interfaces:**
- Consumes: `note_embeddings` & `embed_text` from Task 1.
- Produces:
  - `hybrid_search(db: Database, query: str, cfg: Config, *, mode: str = "hybrid", limit: int = 50, alpha: float = 0.5, filter_type: str | None = None, repo: str | None = None) -> list[dict]`
  - Enhanced endpoint `GET /api/search` with query params `mode`, `type`, `repo`.

**Steps:**
1. Write unit tests in `backend/tests/test_semantic_search.py` testing keyword mode (FTS5), semantic mode (cosine similarity), hybrid mode (RRF rank fusion), and facet filtering (type, repo).
2. Implement `backend/fleeting/services/semantic_search.py`.
3. Update `backend/fleeting/routers/search.py` to route search requests through `hybrid_search`.
4. Run: `cd backend && uv run pytest tests/test_semantic_search.py` and full suite.
5. Commit: `feat(search): add hybrid search combining BM25 keyword matching and vector semantic similarity`.

---

### Task 3: "Ask Fleeting" Assistant Service & REST Router

**Files:**
- Create: `backend/fleeting/services/assistant.py`
- Create: `backend/fleeting/routers/assistant.py`
- Modify: `backend/fleeting/main.py`
- Test: `backend/tests/test_assistant_api.py`

**Interfaces:**
- Consumes: `hybrid_search` from Task 2, `st.db.list_tasks`, `st.db.execute("SELECT * FROM daily_logs")`.
- Produces:
  - `ask_assistant(query: str, history: list[dict], db: Database, cfg: Config) -> dict`
  - Router mounted at `/api/assistant`:
    - `POST /api/assistant/chat`: `{ messages, repo?, type? } -> { message, sources, context_used }`
    - `GET /api/assistant/suggestions`: `-> list[str]` (dynamic query suggestions based on open tasks and recent captures).

**Steps:**
1. Write unit tests in `backend/tests/test_assistant_api.py` testing context assembly, citation extraction, LLM generation, offline extractive fallback, and router endpoints.
2. Implement `backend/fleeting/services/assistant.py` with RAG prompt assembly and citation parsing.
3. Implement `backend/fleeting/routers/assistant.py` and register it in `backend/fleeting/main.py`.
4. Run: `cd backend && uv run pytest tests/test_assistant_api.py` and full suite.
5. Commit: `feat(assistant): add grounded RAG assistant service and REST endpoints`.

---

### Task 4: Frontend "Ask Fleeting" UI, Search View Overhaul & Navigation Integration

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/components/AssistantView.tsx`
- Modify: `frontend/src/components/SearchView.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/__tests__/AssistantView.test.tsx`

**Interfaces:**
- Consumes: `/api/assistant/chat`, `/api/assistant/suggestions`, and `/api/search` with mode parameter.
- Produces:
  - First-class `"assistant"` tab in sidebar with shortcut `A` and `Ctrl+A`.
  - Conversational chat interface with starter chips, message bubbles, markdown rendering, and clickable citation pills that open the `NoteDrawer`.
  - Mode toggle chips in `SearchView.tsx` (`Hybrid`, `Keyword`, `Semantic`) and match confidence badges.

**Steps:**
1. Update `frontend/src/types.ts` and `frontend/src/api.ts`.
2. Write unit tests in `frontend/src/components/__tests__/AssistantView.test.tsx` verifying message rendering, suggested prompt click, and citation click handlers.
3. Implement `frontend/src/components/AssistantView.tsx`.
4. Update `frontend/src/components/SearchView.tsx` with search mode chips and score display.
5. Update `frontend/src/App.tsx` with `"assistant"` view, navigation item, and Command Palette entry.
6. Verify: `cd frontend && npm test`, `cd frontend && npm run build`, `cd backend && uv run pytest`.
7. Commit: `feat(ui): add Ask Fleeting assistant workbench and hybrid search controls`.

---

## Whole-Branch Final Verification
- Pytest suite: 100% pass across all test modules.
- Vitest suite: 100% pass across all component tests.
- Production build: `tsc -b && vite build` clean with 0 errors.
- Whole-branch review with `pro` model.
