# Design Spec: Semantic Recall & "Ask Fleeting" Assistant

**Date:** 2026-10-02  
**Status:** Approved  
**Sub-Project:** 4 of 4  
**Context:** Fleeting — Local-first capture & memory inbox (FastAPI + SQLite + React + TypeScript + Tailwind)

---

## 1. Overview & Motivation

Fleeting stores voice captures, text snippets, bookmarks, tasks, and desktop activity logs in local SQLite. While SQLite FTS5 provides fast exact-keyword matching, personal note-taking demands **conceptual and semantic retrieval**:
- Natural language recall: *"What was that auth issue I noted last Tuesday in repo:fleeting?"*, *"Ideas I had about the dictation engine"*, *"What tasks are blocked on deployment?"*
- Cross-domain synthesis: Connecting notes, active action items, and daily activity logs to answer queries about what the user did, thought, and planned.

Sub-Project 4 delivers:
1. **Local & Provider Vector Embeddings**: Normalized vector embeddings stored directly in SQLite (`note_embeddings` table) with zero external database dependencies. A dual-mode engine supports Ollama/OpenAI/LM Studio embedding endpoints with a fast local hash/TF-IDF vectorizer fallback so semantic search and tests run 100% offline without crashing.
2. **Hybrid Search Engine**: Reciprocal Rank Fusion (RRF) combining SQLite BM25 full-text search with vector cosine similarity, supporting facet filters (`type`, `repo`, `tags`, `since`).
3. **"Ask Fleeting" Conversational Assistant**: Grounded RAG assistant with context assembly across notes, relational tasks, and daily activity logs, generating Markdown responses with structured citation pills `[[note:id|title]]` and `[[task:id|text]]`.
4. **Desktop Workbench & Assistant UI**:
   - First-class `"assistant"` navigation tab in `App.tsx` (`Ask Fleeting` with shortcut `A` and Command Palette integration).
   - Conversational chat interface (`AssistantView.tsx`) with suggested starter prompts, citation chips, and note drawer integration.
   - Search enhancements in `SearchView.tsx` with Hybrid/Keyword/Semantic mode toggle and similarity confidence badges.

---

## 2. Architecture & Data Flow

```
                      +---------------------------------------+
                      |         Frontend (React / Vite)       |
                      |  - AssistantView.tsx                  |
                      |  - SearchView.tsx (Hybrid Toggle)     |
                      |  - App.tsx (Nav & Command Palette)    |
                      +-------------------+-------------------+
                                          | REST
                                          v
+-----------------------------------------------------------------------------------+
|                            FastAPI Backend                                        |
|                                                                                   |
|  +------------------------+      +--------------------+      +-----------------+  |
|  | /api/assistant/chat    |      | /api/search (mode) |      | /api/assistant/ |  |
|  | (Grounded Synthesis)   |      | (Hybrid RRF)       |      | suggestions     |  |
|  +-----------+------------+      +---------+----------+      +-----------------+  |
|              |                             |                                      |
|              +--------------+--------------+                                      |
|                             v                                                     |
|             +-------------------------------+                                     |
|             | services/semantic_search.py   |                                     |
|             |  - RRF(BM25, CosineSimilarity)|                                     |
|             +---------------+---------------+                                     |
|                             |                                                     |
|             +---------------+---------------+                                     |
|             |                               |                                     |
|             v                               v                                     |
|  +---------------------+      +-----------------------------+                     |
|  | services/embeddings |      | SQLite 3 (WAL mode)         |                     |
|  |  - Ollama/OpenAI    |      |  - notes & notes_fts (FTS5) |                     |
|  |  - Fast local vec   |      |  - note_embeddings (v6 BLOB)|                     |
|  |  - pack/unpack vec  |      |  - tasks & daily_logs       |                     |
|  +---------------------+      +-----------------------------+                     |
+-----------------------------------------------------------------------------------+
```

---

## 3. Database Schema Migration (v6)

Added to `MIGRATIONS` in `backend/fleeting/db.py`:
```sql
-- v6 — note embeddings for semantic search & recall
CREATE TABLE IF NOT EXISTS note_embeddings (
    note_id TEXT PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,
    dimensions INTEGER NOT NULL,
    model TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_note_embeddings_updated ON note_embeddings(updated_at);
```

### Vector Serialization
- Packed as IEEE 754 32-bit floats using standard Python `struct.pack(f"{len(vec)}f", *vec)`.
- Unpacked with `struct.unpack(f"{len(blob)//4}f", blob)`.
- Normalization: Vectors are L2-normalized so cosine similarity is computed via pure dot product:
  $$\text{sim}(\mathbf{u}, \mathbf{v}) = \sum_{i=1}^d u_i \cdot v_i$$
- For thousands of personal notes, dot product over packed float32 arrays in Python takes less than 2 milliseconds, requiring no external vector DB daemon.

---

## 4. Embedding Engine (`services/embeddings.py`)

### Providers
1. **Remote/Local Server (`ollama`, `openai`, `lmstudio`)**:
   - Ollama: `POST {base_url}/api/embeddings` or `/api/embed` with model (e.g. `nomic-embed-text` or `cfg.llm.model`).
   - OpenAI / LM Studio: `POST {base_url}/v1/embeddings`.
2. **Local Fallback (Zero-Dependency Vectorizer)**:
   - When LLM provider is `"none"` or the server is offline/unreachable:
   - Uses a deterministic 384-dimensional sub-word / character $n$-gram feature hashing vectorizer with TF-IDF weighting and L2 normalization.
   - Guaranteed 100% offline functionality and instantaneous test execution with 0 external network dependencies.

### Ingestion Hook
- When a note is processed or updated in `Processor._process` and `sync_file_change`:
  - `embeddings_service.embed_note(note, db, cfg)` generates and writes the embedding to `note_embeddings`.
- Startup / Backfill method:
  - `ensure_embeddings(db, cfg)` embeds any active notes missing an embedding row.

---

## 5. Hybrid Search (`services/semantic_search.py`)

### Reciprocal Rank Fusion (RRF)
Combines two independent retrieval channels:
1. **Keyword Retrieval ($R_{FTS}$)**: SQLite FTS5 matching on `notes_fts(title, raw_text, tags)` ordered by BM25.
2. **Semantic Retrieval ($R_{VEC}$)**: Cosine similarity of query vector against all rows in `note_embeddings`.

Combined score for document $d$:
$$Score(d) = \frac{\alpha}{60 + \text{rank}_{FTS}(d)} + \frac{1 - \alpha}{60 + \text{rank}_{VEC}(d)}$$
where $\alpha \in [0, 1]$ (default $0.5$ for balanced hybrid search).

### Filters
- `type`: filter by note type (`text`, `voice`, `youtube`).
- `repo`: filter by repository tag in note source or associated tasks.
- `tag`: filter by topic tag.
- `mode`: `"hybrid"` | `"keyword"` | `"semantic"`.

---

## 6. "Ask Fleeting" Assistant (`services/assistant.py` & `/api/assistant`)

### Retrieval-Augmented Generation (RAG) Flow
1. **Multi-Source Context Retrieval**:
   - Semantic retrieval finds top 5 relevant notes.
   - Task query finds top 5 active/relevant tasks from `tasks` table.
   - Activity query retrieves recent daily log summaries (`daily_logs`).
2. **Prompt Assembly**:
   - Injects current ISO date/time.
   - Assembles system prompt with strict grounding instructions:
     - Answer based *only* on the provided personal notes, tasks, and activity.
     - Emit citations in the format `[[note:id|title]]` and `[[task:id|text]]`.
     - Maintain privacy and a concise, helpful tone.
3. **Model Generation & Extractive Fallback**:
   - Calls `request_chat` with configured LLM.
   - If the LLM is unreachable or disabled, falls back to a clean extractive summary that highlights matching notes, relevant tasks, and activity snippets.
4. **Structured Output**:
   ```json
   {
     "message": {
       "role": "assistant",
       "content": "You noted an authentication token refresh issue in repo:fleeting on Tuesday..."
     },
     "sources": [
       { "id": "abc123", "title": "Auth Token Expiry Bug", "type": "text", "snippet": "..." }
     ],
     "context_used": {
       "notes_count": 3,
       "tasks_count": 2,
       "logs_count": 1
     }
   }
   ```

---

## 7. Frontend Integration

### 1. Dedicated Assistant Workbench (`AssistantView.tsx`)
- Chat stream with message history and auto-scroll.
- Suggested prompt chips:
  - *"What did I capture today?"*
  - *"What urgent P1 tasks do I have?"*
  - *"Review notes about audio transcription"*
  - *"Summarize recent activity in repo:fleeting"*
- Clickable citation pills in assistant replies that open the `NoteDrawer` or jump to the Task Workbench.
- Clear chat button and copy message button.

### 2. Main Navigation in `App.tsx`
- New nav tab `"assistant"`:
  `{ id: "assistant", label: "Ask Fleeting", hint: "A", icon: <BotIcon className="h-4 w-4 text-[#f09d73]" /> }`
- Command Palette action: `"act:assistant"` ("Open Ask Fleeting Assistant").
- Global shortcut: `Ctrl+A` or `A` in navigation mode.

### 3. Enhanced Search View (`SearchView.tsx`)
- Search mode toggle chips: `Hybrid (Smart)` / `Keyword (FTS)` / `Semantic`.
- Confidence score pill on search results (e.g. `92% match`).

---

## 8. Non-Functional & Safety Constraints
- **Offline Reliability**: The entire system must function 100% offline without errors if no LLM server is active.
- **Fast Execution**: Cosine similarity calculations must complete in $< 10\text{ms}$ for up to 10,000 notes.
- **Non-Destructive**: Deleting or archiving notes cascades cleanly (`ON DELETE CASCADE`) in `note_embeddings`.
