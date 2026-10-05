"""SQLite persistence layer.

Single-connection-per-thread SQLite with WAL, schema migrations tracked in a
`schema_version` table, and an external-content FTS5 index kept in sync with
triggers. All timestamps are UTC ISO-8601 strings.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def datetime_now_local() -> datetime:
    return datetime.now().astimezone()

log = logging.getLogger("fleeting.db")

MIGRATIONS: list[str] = [
    # v1 — initial schema
    """
    CREATE TABLE notes (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL DEFAULT 'text',
        title TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        raw_text TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        action_items TEXT NOT NULL DEFAULT '[]',
        source TEXT NOT NULL DEFAULT '{}',
        audio_path TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        error TEXT,
        pinned INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        processed_at TEXT
    );
    CREATE INDEX idx_notes_created ON notes(created_at DESC);
    CREATE INDEX idx_notes_status ON notes(status);
    CREATE VIRTUAL TABLE notes_fts USING fts5(
        title, raw_text, tags,
        content='notes', content_rowid='rowid'
    );
    CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
        INSERT INTO notes_fts(rowid, title, raw_text, tags)
        VALUES (new.rowid, new.title, new.raw_text, new.tags);
    END;
    CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
        INSERT INTO notes_fts(notes_fts, rowid, title, raw_text, tags)
        VALUES ('delete', old.rowid, old.title, old.raw_text, old.tags);
    END;
    CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
        INSERT INTO notes_fts(notes_fts, rowid, title, raw_text, tags)
        VALUES ('delete', old.rowid, old.title, old.raw_text, old.tags);
        INSERT INTO notes_fts(rowid, title, raw_text, tags)
        VALUES (new.rowid, new.title, new.raw_text, new.tags);
    END;
    """,
    # v2 — rebuild FTS index: external-content tables map columns BY NAME, so
    # the FTS columns must match notes.title/raw_text/tags exactly.
    """
    DROP TRIGGER IF EXISTS notes_ai;
    DROP TRIGGER IF EXISTS notes_ad;
    DROP TRIGGER IF EXISTS notes_au;
    DROP TABLE IF EXISTS notes_fts;
    CREATE VIRTUAL TABLE notes_fts USING fts5(
        title, raw_text, tags,
        content='notes', content_rowid='rowid'
    );
    INSERT INTO notes_fts(rowid, title, raw_text, tags)
        SELECT rowid, title, raw_text, tags FROM notes;
    CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
        INSERT INTO notes_fts(rowid, title, raw_text, tags)
        VALUES (new.rowid, new.title, new.raw_text, new.tags);
    END;
    CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
        INSERT INTO notes_fts(notes_fts, rowid, title, raw_text, tags)
        VALUES ('delete', old.rowid, old.title, old.raw_text, old.tags);
    END;
    CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
        INSERT INTO notes_fts(notes_fts, rowid, title, raw_text, tags)
        VALUES ('delete', old.rowid, old.title, old.raw_text, old.tags);
        INSERT INTO notes_fts(rowid, title, raw_text, tags)
        VALUES (new.rowid, new.title, new.raw_text, new.tags);
    END;
    """,
    # v3 — activity tracking + generated daily logs + runtime key/value store
    """
    CREATE TABLE activity (
        id INTEGER PRIMARY KEY,
        app_class TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        seconds INTEGER NOT NULL DEFAULT 0,
        day TEXT NOT NULL
    );
    CREATE INDEX idx_activity_day ON activity(day, first_seen);
    CREATE TABLE daily_logs (
        day TEXT PRIMARY KEY,
        summary_md TEXT NOT NULL,
        model TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # v4 — per-app tracking rules (settings UI toggles tracing individually)
    """
    CREATE TABLE app_rules (
        app_class TEXT PRIMARY KEY,
        tracked INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    );
    """,
    # v5 — relational tasks table with indexes
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        priority TEXT NOT NULL DEFAULT 'P2',
        due_date TEXT,
        repo TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_tasks_note_id ON tasks(note_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks(done);
    CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
    CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
    CREATE INDEX IF NOT EXISTS idx_tasks_repo ON tasks(repo);
    """,
    # v6 — note embeddings for semantic search & recall
    """
    CREATE TABLE IF NOT EXISTS note_embeddings (
        note_id TEXT PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
        embedding BLOB NOT NULL,
        dimensions INTEGER NOT NULL,
        model TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_note_embeddings_updated ON note_embeddings(updated_at);
    """,
    # v7 — weekly digest, mirroring daily_logs. A separate table rather than a
    # "YYYY-Www" key in daily_logs, so a week can never collide with a day.
    """
    CREATE TABLE IF NOT EXISTS weekly_logs (
        week_start TEXT PRIMARY KEY,
        summary_md TEXT NOT NULL,
        model TEXT,
        created_at TEXT NOT NULL
    );
    """,
    # v8 — activity-aware search. Notes were only half the record; window
    # titles and commit subjects are the other half, and both were collected
    # for the digests but never searchable.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS activity_fts USING fts5(
        app_class, title,
        content='activity', content_rowid='id'
    );
    -- Triggers live in migrate(), not here: CREATE TRIGGER ... ON activity
    -- needs that table to exist, and a database predating activity tracking
    -- would otherwise fail to migrate at all.

    CREATE TABLE IF NOT EXISTS commits (
        repo TEXT NOT NULL,
        subject TEXT NOT NULL,
        author TEXT,
        committed_at TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY (repo, subject, committed_at)
    );
    CREATE INDEX IF NOT EXISTS idx_commits_when ON commits(committed_at);
    """,
    # v9 — 0.3 capture ergonomics: idempotency key + source window title.
    # Partial unique index: retries collide, ordinary NULLs don't.
    """
    ALTER TABLE notes ADD COLUMN capture_id TEXT;
    ALTER TABLE notes ADD COLUMN source_title TEXT;
    CREATE UNIQUE INDEX idx_notes_capture_id ON notes(capture_id) WHERE capture_id IS NOT NULL;
    CREATE INDEX idx_notes_type ON notes(type);
    """,
    # v10 — 0.4 notes & organisation: lifecycle (star/trash/review), presentation
    # (colour), typed custom fields, sensitive flag, and the link table wikilinks
    # and backlinks read from. raw_text already exists (v1) and doubles as the
    # pre-clean text version history compares against.
    """
    ALTER TABLE notes ADD COLUMN starred INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE notes ADD COLUMN trashed_at TEXT;
    ALTER TABLE notes ADD COLUMN color TEXT;
    ALTER TABLE notes ADD COLUMN fields TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE notes ADD COLUMN sensitive INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE notes ADD COLUMN review_state TEXT NOT NULL DEFAULT 'enriched';
    CREATE INDEX idx_notes_trashed ON notes(trashed_at);
    CREATE INDEX idx_notes_starred ON notes(starred);
    CREATE TABLE note_links (
      src TEXT NOT NULL,
      dst TEXT NOT NULL,
      PRIMARY KEY (src, dst)
    ) WITHOUT ROWID;
    CREATE INDEX idx_note_links_dst ON note_links(dst);
    """,
    # v11 — #14 snooze: notes hidden until a wake-up timestamp. No job is
    # needed to wake them; the list query simply stops hiding them once the
    # stamp passes.
    """
    ALTER TABLE notes ADD COLUMN snoozed_until TEXT;
    CREATE INDEX idx_notes_snoozed ON notes(snoozed_until);
    """,
    # v12 — #19 version history. Each row is the state *before* an edit to
    # title/summary/raw_text, so "revert" is a plain field copy and the first
    # row per note is the original capture that #21 diffs against.
    """
    CREATE TABLE note_versions (
      id INTEGER PRIMARY KEY,
      note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
      title TEXT NOT NULL DEFAULT '',
      summary TEXT NOT NULL DEFAULT '',
      raw_text TEXT NOT NULL DEFAULT '',
      origin TEXT NOT NULL DEFAULT 'edit',
      created_at TEXT NOT NULL
    );
    CREATE INDEX idx_note_versions_note ON note_versions(note_id, created_at);
    """,
    # v13 — #267/#268/#269 collections. One table with a kind column serves
    # manual playlists, saved queries and projects (the bundle's cut/merge
    # note), so one CRUD and one sidebar section cover all three.
    """
    CREATE TABLE collections (
      id TEXT PRIMARY KEY,
      kind TEXT NOT NULL DEFAULT 'manual',
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      status TEXT,
      query TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE collection_items (
      collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
      note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
      position INTEGER NOT NULL DEFAULT 0,
      added_at TEXT NOT NULL,
      PRIMARY KEY (collection_id, note_id)
    );
    CREATE INDEX idx_collection_items_note ON collection_items(note_id);
    """,
]


# Kept insert-sync between `activity` and its FTS index. Mirrors notes_ai/ad/au.
_ACTIVITY_FTS_TRIGGERS: tuple[tuple[str, str], ...] = (
    (
        "activity_ai",
        """AFTER INSERT ON activity BEGIN
            INSERT INTO activity_fts(rowid, app_class, title)
            VALUES (new.id, new.app_class, new.title);
        END""",
    ),
    (
        "activity_ad",
        """AFTER DELETE ON activity BEGIN
            INSERT INTO activity_fts(activity_fts, rowid, app_class, title)
            VALUES ('delete', old.id, old.app_class, old.title);
        END""",
    ),
    (
        "activity_au",
        """AFTER UPDATE ON activity BEGIN
            INSERT INTO activity_fts(activity_fts, rowid, app_class, title)
            VALUES ('delete', old.id, old.app_class, old.title);
            INSERT INTO activity_fts(rowid, app_class, title)
            VALUES (new.id, new.app_class, new.title);
        END""",
    ),
)


NOTE_COLUMNS = frozenset({
    "type", "title", "summary", "raw_text", "tags", "action_items", "source",
    "audio_path", "status", "error", "pinned", "archived",
    "created_at", "updated_at", "processed_at", "capture_id", "source_title",
    "starred", "trashed_at", "color", "fields", "sensitive", "review_state",
    "snoozed_until",
})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Database:
    """Thread-local connections against one SQLite file."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        self._local = threading.local()
        # NB: no data migration here. This used to run a full scan of `notes`
        # with a per-row INSERT on *every* construction, which the request
        # threadpool does up to 40 times. `migrate()` owns it now.

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            self._local.conn = conn
        return conn

    def migrate(self) -> None:
        """Apply pending migrations, each one all-or-nothing.

        `executescript` implicitly COMMITs and then commits statement-by-
        statement, so a script that fails halfway would leave a partially
        migrated DB with no version row — the next boot re-runs migration v1,
        whose bare `CREATE TABLE notes` then fails on the table v1 itself
        created, and the service crash-loops. Running each script inside an
        explicit transaction makes a failed migration a no-op instead.

        DDL in SQLite is transactional, so this rollback is real.
        """
        conn = self.conn
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        conn.commit()
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= current:
                continue
            log.info("applying migration v%d", version)
            # The BEGIN/COMMIT must live *inside* the script: executescript()
            # issues an implicit COMMIT before it runs, which would discard an
            # externally-started transaction.
            wrapped = (
                "BEGIN;\n"
                + script
                + f"\nINSERT INTO schema_version (version) VALUES ({version});\nCOMMIT;"
            )
            try:
                conn.executescript(wrapped)
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.rollback()
                log.error(
                    "migration v%d failed and was rolled back; schema left at v%d",
                    version,
                    current,
                )
                raise
        self._backfill_activity_index()
        self._migrate_action_items()

    def _backfill_activity_index(self) -> None:
        """Index existing activity rows for the search FTS table.

        Done in Python rather than in migration v8's SQL because a database old
        enough to predate activity tracking has no `activity` table, and the
        statement would abort the whole migration.
        """
        try:
            has_activity = self.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='activity'"
            ).fetchone()
            if not has_activity:
                return
            # Triggers first: without them new sessions never reach the index.
            for name, body in _ACTIVITY_FTS_TRIGGERS:
                self.execute(f"CREATE TRIGGER IF NOT EXISTS {name} {body}")
            total = self.execute("SELECT COUNT(*) AS c FROM activity").fetchone()["c"]
            # Always rebuild rather than trying to detect staleness: COUNT(*) on
            # an external-content FTS table counts the *content* table, so it
            # cannot tell a populated index from an empty one. 'rebuild' is also
            # the documented way to (re)index — a plain INSERT ... SELECT leaves
            # the index unsearchable (rows present, MATCH returns nothing).
            # Cheap: activity is pruned to the retention window.
            self.execute("INSERT INTO activity_fts(activity_fts) VALUES('rebuild')")
            self.commit()
            if total:
                log.info("indexed %d activity rows for search", total)
        except sqlite3.OperationalError:
            log.warning("activity search backfill skipped", exc_info=True)

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def commit(self) -> None:
        self.conn.commit()

    # ---- note helpers -------------------------------------------------

    def insert_note(self, note: dict) -> dict:
        now = now_iso()
        note = {
            **note,
            "id": note.get("id") or new_id(),
            "created_at": note.get("created_at") or now,
            "updated_at": note.get("updated_at") or now,
        }
        # #332: a client retry with the same capture_id returns the original
        # note instead of 500ing on the unique index.
        if note.get("capture_id"):
            row = self.execute(
                "SELECT id FROM notes WHERE capture_id = ?", (note["capture_id"],)
            ).fetchone()
            if row:
                return self.get_note(row["id"])  # type: ignore[return-value]
        self.execute(
            """
            INSERT INTO notes (id, type, title, summary, raw_text, tags, action_items,
                               source, audio_path, status, error, pinned, archived,
                               created_at, updated_at, processed_at, capture_id, source_title,
                               starred, trashed_at, color, fields, sensitive, review_state,
                               snoozed_until)
            VALUES (:id, :type, :title, :summary, :raw_text, :tags, :action_items,
                    :source, :audio_path, :status, :error, :pinned, :archived,
                    :created_at, :updated_at, :processed_at, :capture_id, :source_title,
                    :starred, :trashed_at, :color, :fields, :sensitive, :review_state,
                    :snoozed_until)
            """,
            _note_to_sql(note),
        )
        self.commit()
        if note.get("action_items"):
            self._sync_tasks_from_note(note["id"], note["action_items"])
            self._sync_note_action_items(note["id"])
        return self.get_note(note["id"])  # type: ignore[return-value]

    # Version history keeps the last N content snapshots per note; edits are
    # rare enough that 20 comfortably covers a note's editing lifetime.
    VERSIONS_PER_NOTE = 20

    def update_note(self, note_id: str, changes: dict) -> dict | None:
        if not changes:
            return self.get_note(note_id)
        # Column names cannot be bound as SQL parameters, so drop anything
        # off-schema rather than splicing it into the SET clause.
        changes = {k: v for k, v in changes.items() if k in NOTE_COLUMNS}
        if not changes:
            return self.get_note(note_id)
        self._snapshot_before_edit(note_id, changes)
        if "raw_text" in changes:
            self._sync_note_links(note_id, str(changes["raw_text"] or ""))
        changes = {**changes, "updated_at": changes.get("updated_at") or now_iso()}
        sets = ", ".join(f"{key} = :{key}" for key in changes)
        changes_sql = dict(changes)
        # JSON-encode list/dict fields
        for key in ("tags", "action_items", "source", "fields"):
            if key in changes_sql and not isinstance(changes_sql[key], str):
                changes_sql[key] = json.dumps(
                    changes_sql[key],
                    ensure_ascii=False,
                    default=lambda o: o.model_dump() if hasattr(o, "model_dump") else (o.dict() if hasattr(o, "dict") else str(o)),
                )
        cur = self.execute(f"UPDATE notes SET {sets} WHERE id = :_id", {**changes_sql, "_id": note_id})
        if cur.rowcount == 0:
            return None
        self.commit()
        if "action_items" in changes:
            self._sync_tasks_from_note(note_id, changes["action_items"])
            self._sync_note_action_items(note_id)
        return self.get_note(note_id)

    def _snapshot_before_edit(self, note_id: str, changes: dict) -> None:
        """#19: record the current title/summary/raw_text before an edit lands.

        Only content fields trigger a snapshot — status/source churn from the
        pipeline must not fabricate history. Skips the snapshot when nothing
        actually differs (update_note is called for bookkeeping fields too).
        """
        watched = ("title", "summary", "raw_text")
        if not any(f in changes for f in watched):
            return
        cur = self.execute(
            "SELECT title, summary, raw_text, status FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if not cur:
            return
        if all(changes.get(f, cur[f]) == cur[f] for f in watched):
            return
        # A wholly-empty state (text capture pre-enrichment, voice note pre-
        # transcription) has nothing worth restoring — skip it.
        if not (cur["title"] or cur["summary"] or cur["raw_text"]):
            return
        # While the pipeline is mid-flight (status=processing) any content
        # change is automatic — transcription landing, output-mode shaping.
        origin = "pipeline" if cur["status"] == "processing" else "edit"
        self.execute(
            "INSERT INTO note_versions (note_id, title, summary, raw_text, origin, created_at) "
            "VALUES (:note_id, :title, :summary, :raw_text, :origin, :created_at)",
            {
                "note_id": note_id,
                "title": cur["title"],
                "summary": cur["summary"],
                "raw_text": cur["raw_text"],
                "origin": origin,
                "created_at": now_iso(),
            },
        )
        self.execute(
            """
            DELETE FROM note_versions WHERE note_id = :nid AND id NOT IN (
              SELECT id FROM note_versions WHERE note_id = :nid
              ORDER BY id DESC LIMIT :cap
            )
            """,
            {"nid": note_id, "cap": self.VERSIONS_PER_NOTE},
        )

    _WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]*)?\]\]")

    def _sync_note_links(self, note_id: str, raw_text: str) -> None:
        """#22: re-resolve [[wikilinks]] in the body into note_links rows.

        Targets resolve by note title (case-insensitive, trashed excluded) and
        are stored as note *ids* — so renaming either end keeps old links
        working; only new mentions re-resolve. Replaces the src's rows
        wholesale, matching the vault's render-on-write behaviour.
        """
        targets = []
        for m in self._WIKILINK_RE.findall(raw_text or ""):
            t = m.strip()
            if t and t.lower() not in {x.lower() for x in targets}:
                targets.append(t)
        if not targets:
            cur = self.execute("SELECT COUNT(*) AS c FROM note_links WHERE src = ?", (note_id,)).fetchone()
            if cur["c"]:
                self.execute("DELETE FROM note_links WHERE src = ?", (note_id,))
                self.commit()
            return
        resolved: list[str] = []
        for t in targets:
            row = self.execute(
                "SELECT id FROM notes WHERE lower(title) = lower(:t) AND trashed_at IS NULL "
                "AND id != :src LIMIT 1",
                {"t": t, "src": note_id},
            ).fetchone()
            if row:
                resolved.append(row["id"])
        self.execute("DELETE FROM note_links WHERE src = ?", (note_id,))
        if resolved:
            self.conn.executemany(
                "INSERT OR IGNORE INTO note_links (src, dst) VALUES (?, ?)",
                [(note_id, dst) for dst in resolved],
            )
        self.commit()

    def note_links(self, note_id: str) -> tuple[list[dict], list[dict]]:
        """(outgoing, backlinks) for a note; both exclude trashed notes."""
        out_rows = self.execute(
            """
            SELECT n.* FROM note_links l
            JOIN notes n ON n.id = l.dst
            WHERE l.src = :id AND n.trashed_at IS NULL
            ORDER BY n.title COLLATE NOCASE
            """,
            {"id": note_id},
        ).fetchall()
        back_rows = self.execute(
            """
            SELECT n.* FROM note_links l
            JOIN notes n ON n.id = l.src
            WHERE l.dst = :id AND n.trashed_at IS NULL
            ORDER BY n.title COLLATE NOCASE
            """,
            {"id": note_id},
        ).fetchall()
        return (
            [_row_to_note(r) for r in out_rows],
            [_row_to_note(r) for r in back_rows],
        )

    def note_versions(self, note_id: str) -> list[dict]:
        """Snapshots for a note, oldest first (index 0 = original capture)."""
        rows = self.execute(
            "SELECT id, note_id, title, summary, raw_text, origin, created_at "
            "FROM note_versions WHERE note_id = ? ORDER BY id ASC",
            (note_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_note_version(self, note_id: str, version_id: int) -> dict | None:
        row = self.execute(
            "SELECT id, note_id, title, summary, raw_text, origin, created_at "
            "FROM note_versions WHERE note_id = ? AND id = ?",
            (note_id, version_id),
        ).fetchone()
        return dict(row) if row else None

    def get_note(self, note_id: str) -> dict | None:
        row = self.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return _row_to_note(row) if row else None

    def get_note_by_capture_id(self, capture_id: str) -> dict | None:
        row = self.execute("SELECT * FROM notes WHERE capture_id = ?", (capture_id,)).fetchone()
        return _row_to_note(row) if row else None

    def list_notes(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        tag: str | None = None,
        status: str | None = None,
        note_type: str | None = None,
        archived: bool = False,
        pinned_first: bool = True,
        trashed: bool = False,
        starred: bool = False,
        include_snoozed: bool = False,
        review_state: str | None = None,
    ) -> list[dict]:
        where = ["archived = :archived"]
        # #274: trashed notes are hidden everywhere by default and only surface
        # through the explicit trash listing.
        where.append("trashed_at IS NULL" if not trashed else "trashed_at IS NOT NULL")
        params: dict = {"archived": 1 if archived else 0, "limit": limit, "offset": offset}
        if starred:
            where.append("starred = 1")
        if review_state:
            where.append("review_state = :review_state")
            params["review_state"] = review_state
        if not include_snoozed:
            # #14: snoozed notes reappear on their own once the stamp passes —
            # ISO strings share one UTC offset, so string comparison is safe.
            where.append("(snoozed_until IS NULL OR snoozed_until <= :now_ts)")
            params["now_ts"] = now_iso()
        if tag:
            where.append("EXISTS (SELECT 1 FROM json_each(notes.tags) je WHERE je.value = :tag)")
            params["tag"] = tag
        if status:
            where.append("status = :status")
            params["status"] = status
        if note_type:
            where.append("type = :note_type")
            params["note_type"] = note_type
        order = "pinned DESC, created_at DESC" if pinned_first else "created_at DESC"
        rows = self.execute(
            f"SELECT * FROM notes WHERE {' AND '.join(where)} ORDER BY {order} "
            "LIMIT :limit OFFSET :offset",
            params,
        ).fetchall()
        return [_row_to_note(r) for r in rows]

    def count_notes(self, status: str | None = None) -> int:
        if status:
            row = self.execute("SELECT COUNT(*) AS c FROM notes WHERE status = ?", (status,)).fetchone()
        else:
            row = self.execute("SELECT COUNT(*) AS c FROM notes").fetchone()
        return int(row["c"])

    def delete_note(self, note_id: str, audio_root: str | Path | None = None) -> dict | None:
        """Hard-delete a note, its tasks, and its audio file.

        This is now the *purge* path — the API's DELETE trashes first (#274).
        Only paths inside `audio_root` are unlinked, so a hand-edited or
        imported row cannot delete something outside it.
        """
        note = self.get_note(note_id)
        if note:
            self.execute("DELETE FROM tasks WHERE note_id = ?", (note_id,))
            self.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self.commit()
            self._unlink_audio(note.get("audio_path"), audio_root)
        return note

    def trashed_notes(self, limit: int = 200) -> list[dict]:
        """Notes in the trash, most recently trashed first."""
        rows = self.execute(
            "SELECT * FROM notes WHERE trashed_at IS NOT NULL "
            "ORDER BY trashed_at DESC LIMIT :limit",
            {"limit": limit},
        ).fetchall()
        return [_row_to_note(r) for r in rows]

    def snoozed_notes(self) -> list[dict]:
        """Notes currently snoozed, in wake-up order. #14 visibility surface."""
        rows = self.execute(
            "SELECT * FROM notes WHERE snoozed_until IS NOT NULL AND snoozed_until > :now "
            "AND trashed_at IS NULL ORDER BY snoozed_until ASC",
            {"now": now_iso()},
        ).fetchall()
        return [_row_to_note(r) for r in rows]

    def purge_expired_trash(self, retention_days: int, audio_root: str | Path | None = None) -> list[dict]:
        """Hard-delete notes trashed more than `retention_days` ago.

        Returns the purged notes so callers can publish `note.deleted` and
        clean up vault mirrors. Timestamps are ISO-8601 strings written by
        now_iso(), so string comparison with the cutoff is order-correct.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max(0, retention_days))
        ).isoformat(timespec="seconds")
        rows = self.execute(
            "SELECT id FROM notes WHERE trashed_at IS NOT NULL AND trashed_at < ?",
            (cutoff,),
        ).fetchall()
        purged = []
        for r in rows:
            note = self.delete_note(r["id"], audio_root=audio_root)
            if note:
                purged.append(note)
        if purged:
            log.info("purged %d trashed note(s) older than %d days", len(purged), retention_days)
        return purged

    @staticmethod
    def _unlink_audio(audio_path: str | None, audio_root: str | Path | None) -> None:
        if not audio_path or audio_root is None:
            return
        try:
            root = Path(audio_root).resolve()
            target = Path(audio_path).resolve()
            # is_relative_to guards against ../ traversal and absolute paths
            # pointing anywhere else on disk.
            if not target.is_relative_to(root):
                log.warning("refusing to unlink audio outside %s: %s", root, target)
                return
            target.unlink(missing_ok=True)
        except OSError:
            log.warning("could not remove audio file %s", audio_path, exc_info=True)

    def notes_in_status(self, *statuses: str) -> list[dict]:
        placeholders = ",".join("?" for _ in statuses)
        rows = self.execute(
            f"SELECT * FROM notes WHERE status IN ({placeholders})", statuses
        ).fetchall()
        return [_row_to_note(r) for r in rows]

    # ---- activity tracking ----------------------------------------------

    def upsert_activity(self, row: dict) -> int:
        """Insert or update one activity session. Returns its id.

        Commits immediately: the collector writes from a worker thread whose
        connection is separate from request handlers.
        """
        if row.get("id") is not None:
            self.execute(
                "UPDATE activity SET app_class=:app_class, title=:title, first_seen=:first_seen,"
                " last_seen=:last_seen, seconds=:seconds, day=:day WHERE id=:id",
                row,
            )
            self.commit()
            return int(row["id"])
        cur = self.execute(
            "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day)"
            " VALUES (:app_class, :title, :first_seen, :last_seen, :seconds, :day)",
            row,
        )
        self.commit()
        return int(cur.lastrowid)

    def activity_sessions(self, day: str) -> list[dict]:
        rows = self.execute(
            "SELECT * FROM activity WHERE day = :day AND seconds >= 1 ORDER BY first_seen",
            {"day": day},
        ).fetchall()
        return [dict(r) for r in rows]

    def activity_since(self, cutoff_iso: str) -> list[dict]:
        """Sessions still open at or after the cutoff (rolling 24h reports).

        Timestamps share the machine's single local offset, so ISO string
        comparison is order-correct here.
        """
        rows = self.execute(
            "SELECT * FROM activity WHERE last_seen >= :cutoff AND seconds >= 1 ORDER BY first_seen",
            {"cutoff": cutoff_iso},
        ).fetchall()
        return [dict(r) for r in rows]

    def activity_days(self, limit: int = 60) -> list[str]:
        rows = self.execute(
            "SELECT DISTINCT day FROM activity ORDER BY day DESC LIMIT :limit", {"limit": limit}
        ).fetchall()
        return [r["day"] for r in rows]

    def get_daily_log(self, day: str) -> dict | None:
        row = self.execute("SELECT * FROM daily_logs WHERE day = ?", (day,)).fetchone()
        return dict(row) if row else None

    def get_weekly_log(self, week_start: str) -> dict | None:
        row = self.execute(
            "SELECT * FROM weekly_logs WHERE week_start = ?", (week_start,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_weekly_log(self, week_start: str, summary_md: str, model: str) -> None:
        self.execute(
            """
            INSERT OR REPLACE INTO weekly_logs (week_start, summary_md, model, created_at)
            VALUES (:week, :md, :model, :created_at)
            """,
            {"week": week_start, "md": summary_md, "model": model, "created_at": now_iso()},
        )
        self.commit()

    def daily_logs_between(self, start_day: str, end_day: str) -> list[dict]:
        """Stored daily summaries in [start_day, end_day], oldest first."""
        rows = self.execute(
            "SELECT * FROM daily_logs WHERE day >= ? AND day <= ? ORDER BY day ASC",
            (start_day, end_day),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_daily_log(self, day: str, summary_md: str, model: str) -> None:
        self.execute(
            "INSERT INTO daily_logs (day, summary_md, model, created_at) VALUES (:day, :md, :model, :ts)"
            " ON CONFLICT(day) DO UPDATE SET summary_md=:md, model=:model, created_at=:ts",
            {"day": day, "md": summary_md, "model": model, "ts": now_iso()},
        )
        self.commit()

    # ---- key/value store (pause flags etc.) ------------------------------

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        row = self.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.commit()

    def activity_per_day(self, days: int = 7) -> list[dict]:
        """Tracked seconds per local day for the last N days (gaps filled with 0)."""
        rows = self.execute(
            "SELECT day, SUM(seconds) AS s FROM activity GROUP BY day"
        ).fetchall()
        by_day = {r["day"]: r["s"] or 0 for r in rows}
        out = []
        for i in range(days - 1, -1, -1):
            d = (datetime_now_local() - timedelta(days=i)).strftime("%Y-%m-%d")
            out.append({"day": d, "seconds": by_day.get(d, 0)})
        return out

    def notes_per_day(self, days: int = 7) -> list[dict]:
        """Captures per local day for the last N days (gaps filled with 0)."""
        days = min(max(days, 2), 60)
        rows = self.execute(
            """
            SELECT date(created_at, 'localtime') AS d, COUNT(*) AS c
            FROM notes
            WHERE created_at >= datetime('now', :offset)
            GROUP BY d
            """,
            {"offset": f"-{days} days"},
        ).fetchall()
        by_day = {r["d"]: r["c"] for r in rows}
        out = []
        for i in range(days - 1, -1, -1):
            d = (datetime_now_local() - timedelta(days=i)).strftime("%Y-%m-%d")
            out.append({"day": d, "count": by_day.get(d, 0)})
        return out

    # ---- per-app tracking rules -----------------------------------------

    def app_rules(self) -> dict[str, bool]:
        """app_class -> tracked? Only apps with an explicit rule appear."""
        rows = self.execute("SELECT app_class, tracked FROM app_rules").fetchall()
        return {r["app_class"]: bool(r["tracked"]) for r in rows}

    def set_app_rule(self, app_class: str, tracked: bool) -> None:
        self.execute(
            "INSERT INTO app_rules (app_class, tracked, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(app_class) DO UPDATE SET tracked=excluded.tracked, updated_at=excluded.updated_at",
            (app_class, int(tracked), now_iso()),
        )
        self.commit()

    def known_apps(self) -> list[dict]:
        """Apps seen in activity, with totals and their effective rule."""
        rules = self.app_rules()
        rows = self.execute(
            """
            SELECT app_class, SUM(seconds) AS seconds, COUNT(*) AS sessions, MAX(day) AS last_day
            FROM activity GROUP BY app_class ORDER BY seconds DESC
            """
        ).fetchall()
        out = [
            {
                "app_class": r["app_class"],
                "seconds": r["seconds"] or 0,
                "sessions": r["sessions"] or 0,
                "last_day": r["last_day"],
                "tracked": rules.get(r["app_class"], True),
                "has_rule": r["app_class"] in rules,
            }
            for r in rows
        ]
        # apps with rules but no activity yet
        seen = {o["app_class"] for o in out}
        for app_class, tracked in rules.items():
            if app_class not in seen:
                out.append(
                    {"app_class": app_class, "seconds": 0, "sessions": 0, "last_day": None,
                     "tracked": tracked, "has_rule": True}
                )
        return out

    # ---- activity-aware search ------------------------------------------

    def search_activity(
        self, query: str, *, limit: int = 50, since_day: str | None = None
    ) -> list[dict]:
        """FTS5 match over window sessions (title + app class), newest first.

        Zero-second sessions are excluded here exactly as `activity_sessions`
        does elsewhere: they are tab-switch noise that reads everywhere else.
        """
        params: dict = {"q": _activity_fts_query(query), "limit": max(1, int(limit))}
        where = ["activity_fts MATCH :q", "a.seconds >= 1"]
        if since_day:
            where.append("a.day >= :since_day")
            params["since_day"] = since_day
        try:
            rows = self.execute(
                f"""
                SELECT a.id, a.app_class, a.title, a.day, a.seconds,
                       bm25(activity_fts) AS rank
                FROM activity_fts f
                JOIN activity a ON a.id = f.rowid
                WHERE {' AND '.join(where)}
                ORDER BY rank
                LIMIT :limit
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            # Unparseable FTS expression: return nothing rather than everything.
            log.info("activity search rejected query %r", query)
            return []
        return [
            {
                "id": r["id"],
                "app_class": r["app_class"],
                "title": r["title"],
                "day": r["day"],
                "seconds": int(r["seconds"] or 0),
            }
            for r in rows
        ]

    def record_commit(
        self, repo: str, subject: str, author: str = "", committed_at: str | None = None
    ) -> None:
        """Store one commit subject. Idempotent — re-running a digest is fine."""
        self.execute(
            """
            INSERT OR IGNORE INTO commits (repo, subject, author, committed_at, recorded_at)
            VALUES (:repo, :subject, :author, :when, :recorded)
            """,
            {
                "repo": str(repo),
                "subject": str(subject),
                "author": str(author or ""),
                "when": committed_at or now_iso(),
                "recorded": now_iso(),
            },
        )
        self.commit()

    def search_commits(
        self, query: str, *, limit: int = 20, since: str | None = None
    ) -> list[dict]:
        """Commits whose repo or subject matches, newest first."""
        tokens = [t for t in query.split() if t]
        if not tokens:
            return []
        clauses = []
        params: dict = {"limit": max(1, int(limit))}
        for i, tok in enumerate(tokens):
            params[f"t{i}"] = f"%{tok}%"
            clauses.append(f"(repo LIKE :t{i} OR subject LIKE :t{i})")
        where = " OR ".join(clauses)
        if since:
            where += " AND committed_at >= :since"
            params["since"] = since
        rows = self.execute(
            f"""
            SELECT repo, subject, author, committed_at
            FROM commits
            WHERE {where}
            ORDER BY committed_at DESC
            LIMIT :limit
            """,
            params,
        ).fetchall()
        return [
            {
                "repo": r["repo"],
                "subject": r["subject"],
                "author": r["author"],
                "committed_at": r["committed_at"],
            }
            for r in rows
        ]

    # ---- search --------------------------------------------------------

    def search(self, query: str, *, limit: int = 50) -> list[dict]:
        """FTS5 match query, ranked, with highlighted snippets."""
        rows = self.execute(
            """
            SELECT n.*, bm25(notes_fts) AS rank,
                   snippet(notes_fts, 1, '[[', ']]', '…', 24) AS snippet
            FROM notes_fts f
            JOIN notes n ON n.rowid = f.rowid
            WHERE notes_fts MATCH :q AND n.trashed_at IS NULL
            ORDER BY rank
            LIMIT :limit
            """,
            {"q": _fts_query(query), "limit": limit},
        ).fetchall()
        return [_row_to_note(r, extra=("snippet",)) for r in rows]    # ---- tags / stats ----------------------------------------------------

    def all_tags(self) -> list[dict]:
        rows = self.execute(
            """
            SELECT je.value AS tag, COUNT(*) AS count
            FROM notes, json_each(notes.tags) je
            WHERE notes.archived = 0 AND notes.trashed_at IS NULL
            GROUP BY je.value
            ORDER BY count DESC, tag ASC
            """
        ).fetchall()
        return [{"tag": r["tag"], "count": r["count"]} for r in rows]

    def stats(self) -> dict:
        row = self.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN date(created_at, 'localtime') = date('now', 'localtime')
                       THEN 1 ELSE 0 END) AS today,
              SUM(CASE WHEN created_at >= datetime('now', '-7 days')
                       THEN 1 ELSE 0 END) AS week,
              SUM(CASE WHEN type = 'text' THEN 1 ELSE 0 END) AS text_count,
              SUM(CASE WHEN type = 'voice' THEN 1 ELSE 0 END) AS voice_count,
              SUM(CASE WHEN type = 'youtube' THEN 1 ELSE 0 END) AS youtube_count
            FROM notes
            WHERE trashed_at IS NULL
            """
        ).fetchone()
        t_row = self.execute(
            """
            SELECT
              SUM(CASE WHEN t.done = 0 THEN 1 ELSE 0 END) AS open_tasks,
              SUM(CASE WHEN t.done = 1 THEN 1 ELSE 0 END) AS done_tasks
            FROM tasks t
            LEFT JOIN notes n ON t.note_id = n.id
            WHERE ((n.archived = 0 AND n.trashed_at IS NULL) OR n.id IS NULL)
            """
        ).fetchone()
        open_tasks = int(t_row["open_tasks"] or 0)
        done_tasks = int(t_row["done_tasks"] or 0)
        return {
            "total": row["total"] or 0,
            "today": row["today"] or 0,
            "week": row["week"] or 0,
            "open_tasks": open_tasks,
            "done_tasks": done_tasks,
            "by_type": {
                "text": row["text_count"] or 0,
                "voice": row["voice_count"] or 0,
                "youtube": row["youtube_count"] or 0,
            },
        }

    # ---- tasks & action items -------------------------------------------

    def _migrate_action_items(self) -> None:
        """Idempotently migrate legacy action_items JSON arrays from notes into the tasks table."""
        check_tables = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('notes', 'tasks')"
        ).fetchall()
        table_names = {r["name"] for r in check_tables}
        if "notes" not in table_names or "tasks" not in table_names:
            return

        rows = self.execute(
            "SELECT id, action_items, created_at, updated_at, source FROM notes WHERE archived = 0"
        ).fetchall()
        for row in rows:
            try:
                items = json.loads(row["action_items"] or "[]")
            except (json.JSONDecodeError, TypeError):
                items = []
            for it in items:
                if isinstance(it, str):
                    it = {"text": it}
                task_id = it.get("id") or new_id()
                full_id = f"{row['id']}_{task_id}" if not task_id.startswith(f"{row['id']}_") else task_id

                priority = (it.get("priority") or "P2").strip().upper()
                if priority not in ("P1", "P2", "P3"):
                    priority = "P2"
                due_date = it.get("due_date") or None
                repo = (it.get("repo") or "").strip().lower() or None
                done = 1 if it.get("done") else 0
                completed_at = it.get("completed_at") or (row["updated_at"] if done else None)

                self.execute(
                    """
                    INSERT OR IGNORE INTO tasks (id, note_id, text, done, priority, due_date, repo, created_at, completed_at)
                    VALUES (:id, :note_id, :text, :done, :priority, :due_date, :repo, :created_at, :completed_at)
                    """,
                    {
                        "id": full_id,
                        "note_id": row["id"],
                        "text": (it.get("text") or "").strip(),
                        "done": done,
                        "priority": priority,
                        "due_date": due_date,
                        "repo": repo,
                        "created_at": it.get("created_at") or row["created_at"],
                        "completed_at": completed_at,
                    },
                )
        self.commit()

    def _sync_note_action_items(self, note_id: str) -> None:
        """Keep parent note's action_items JSON column in sync with tasks table."""
        rows = self.execute(
            """
            SELECT id, text, done, priority, due_date, repo, completed_at
            FROM tasks
            WHERE note_id = ?
            ORDER BY created_at ASC
            """,
            (note_id,),
        ).fetchall()
        items = [
            {
                "id": r["id"],
                "text": r["text"],
                "done": bool(r["done"]),
                "priority": r["priority"],
                "due_date": r["due_date"],
                "repo": r["repo"],
                "completed_at": r["completed_at"],
            }
            for r in rows
        ]
        self.execute(
            "UPDATE notes SET action_items = :items, updated_at = :ts WHERE id = :id",
            {
                "items": json.dumps(items, ensure_ascii=False),
                "ts": now_iso(),
                "id": note_id,
            },
        )
        self.commit()

    def _sync_tasks_from_note(self, note_id: str, action_items: list | str) -> None:
        """Keep tasks table in sync when note.action_items is directly updated."""
        if isinstance(action_items, str):
            try:
                items = json.loads(action_items)
            except Exception:
                items = []
        else:
            items = list(action_items or [])

        existing = {
            r["id"]: dict(r)
            for r in self.execute("SELECT * FROM tasks WHERE note_id = ?", (note_id,)).fetchall()
        }
        seen_ids = set()

        for it in items:
            if isinstance(it, str):
                it = {"text": it}
            elif hasattr(it, "model_dump"):
                it = it.model_dump()
            elif hasattr(it, "dict"):
                it = it.dict()
            else:
                it = dict(it)

            task_id = it.get("id") or new_id()
            full_id = task_id
            if full_id not in existing and f"{note_id}_{task_id}" in existing:
                full_id = f"{note_id}_{task_id}"
            elif full_id not in existing and not full_id.startswith(f"{note_id}_") and len(full_id) < 8:
                full_id = f"{note_id}_{task_id}"

            text = (it.get("text") or "").strip()
            done = 1 if it.get("done") else 0
            priority = (it.get("priority") or "P2").strip().upper()
            if priority not in ("P1", "P2", "P3"):
                priority = "P2"
            due_date = it.get("due_date") or None
            repo = (it.get("repo") or "").strip().lower() or None
            completed_at = it.get("completed_at")
            if done and not completed_at:
                completed_at = existing.get(full_id, {}).get("completed_at") or now_iso()
            elif not done:
                completed_at = None

            if full_id in existing:
                self.execute(
                    """
                    UPDATE tasks
                    SET text = :text, done = :done, priority = :priority,
                        due_date = :due_date, repo = :repo, completed_at = :completed_at
                    WHERE id = :id
                    """,
                    {
                        "id": full_id,
                        "text": text,
                        "done": done,
                        "priority": priority,
                        "due_date": due_date,
                        "repo": repo,
                        "completed_at": completed_at,
                    },
                )
            else:
                self.execute(
                    """
                    INSERT INTO tasks (id, note_id, text, done, priority, due_date, repo, created_at, completed_at)
                    VALUES (:id, :note_id, :text, :done, :priority, :due_date, :repo, :created_at, :completed_at)
                    """,
                    {
                        "id": full_id,
                        "note_id": note_id,
                        "text": text,
                        "done": done,
                        "priority": priority,
                        "due_date": due_date,
                        "repo": repo,
                        "created_at": it.get("created_at") or now_iso(),
                        "completed_at": completed_at,
                    },
                )
            seen_ids.add(full_id)

        for old_id in existing:
            if old_id not in seen_ids:
                self.execute("DELETE FROM tasks WHERE id = ?", (old_id,))
        self.commit()

    def _get_or_create_inbox_note(self) -> str:
        row = self.execute("SELECT id FROM notes WHERE title = 'Inbox' AND archived = 0 LIMIT 1").fetchone()
        if row:
            return str(row["id"])
        new_note = self.insert_note({
            "title": "Inbox",
            "type": "text",
            "summary": "Standalone tasks and quick action items.",
            "raw_text": "",
            "tags": ["tasks"],
        })
        return str(new_note["id"])

    def insert_task(self, task: dict) -> dict:
        task_id = task.get("id") or new_id()
        note_id = task.get("note_id")
        if not note_id:
            note_id = self._get_or_create_inbox_note()

        text = (task.get("text") or "").strip()
        done = 1 if task.get("done") else 0
        priority = (task.get("priority") or "P2").strip().upper()
        if priority not in ("P1", "P2", "P3"):
            priority = "P2"
        due_date = task.get("due_date") or None
        repo = (str(task.get("repo")).strip().lower() or None) if task.get("repo") else None
        created_at = task.get("created_at") or now_iso()
        completed_at = task.get("completed_at") or (now_iso() if done else None)

        self.execute(
            """
            INSERT INTO tasks (id, note_id, text, done, priority, due_date, repo, created_at, completed_at)
            VALUES (:id, :note_id, :text, :done, :priority, :due_date, :repo, :created_at, :completed_at)
            """,
            {
                "id": task_id,
                "note_id": note_id,
                "text": text,
                "done": done,
                "priority": priority,
                "due_date": due_date,
                "repo": repo,
                "created_at": created_at,
                "completed_at": completed_at,
            },
        )
        self.commit()
        self._sync_note_action_items(note_id)
        return self.get_task(task_id)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> dict | None:
        row = self.execute(
            """
            SELECT t.*, n.title AS note_title
            FROM tasks t
            LEFT JOIN notes n ON t.note_id = n.id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()
        return _row_to_task(row) if row else None

    def update_task(self, task_id: str, changes: dict) -> dict | None:
        current = self.get_task(task_id)
        if not current:
            return None
        if not changes:
            return current

        clean_changes = {}
        for key in ("text", "priority", "due_date", "repo", "completed_at", "note_id"):
            if key in changes:
                clean_changes[key] = changes[key]

        if "priority" in clean_changes:
            if clean_changes["priority"] is not None:
                p = str(clean_changes["priority"]).strip().upper()
                clean_changes["priority"] = p if p in ("P1", "P2", "P3") else "P2"
            else:
                clean_changes["priority"] = "P2"

        if "repo" in clean_changes:
            val = clean_changes["repo"]
            clean_changes["repo"] = str(val).strip().lower() if val else None

        if "due_date" in clean_changes:
            val = clean_changes["due_date"]
            clean_changes["due_date"] = str(val).strip() if val else None

        if "done" in changes:
            new_done = bool(changes["done"])
            clean_changes["done"] = 1 if new_done else 0
            if "completed_at" not in changes:
                clean_changes["completed_at"] = now_iso() if new_done else None

        if clean_changes:
            sets = ", ".join(f"{k} = :{k}" for k in clean_changes)
            self.execute(f"UPDATE tasks SET {sets} WHERE id = :_id", {**clean_changes, "_id": task_id})
            self.commit()

        new_task = self.get_task(task_id)
        self._sync_note_action_items(current["note_id"])
        if new_task and new_task["note_id"] != current["note_id"]:
            self._sync_note_action_items(new_task["note_id"])
        return new_task

    def toggle_task(self, task_id: str) -> dict | None:
        task = self.get_task(task_id)
        if not task:
            return None
        new_done = not task["done"]
        completed_at = now_iso() if new_done else None
        self.execute(
            "UPDATE tasks SET done = :done, completed_at = :completed_at WHERE id = :id",
            {"done": 1 if new_done else 0, "completed_at": completed_at, "id": task_id},
        )
        self.commit()
        self._sync_note_action_items(task["note_id"])
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> dict | None:
        task = self.get_task(task_id)
        if not task:
            return None
        self.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.commit()
        self._sync_note_action_items(task["note_id"])
        return task

    def list_tasks(
        self,
        status: str = "open",
        priority: str | None = None,
        repo: str | None = None,
        due: str | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        where = ["((n.archived = 0 AND n.trashed_at IS NULL) OR n.id IS NULL)"]
        params: dict = {"limit": limit, "offset": offset}

        if status == "open":
            where.append("t.done = 0")
        elif status in ("done", "completed"):
            where.append("t.done = 1")

        if priority:
            if priority.upper() in ("P1", "P2", "P3"):
                where.append("t.priority = :priority")
                params["priority"] = priority.upper()
            else:
                where.append("1 = 0")

        if repo:
            where.append("t.repo = :repo")
            params["repo"] = repo.strip().lower()

        today = datetime_now_local().strftime("%Y-%m-%d")
        if due == "overdue":
            where.append("t.due_date IS NOT NULL AND t.due_date < :today AND t.done = 0")
            params["today"] = today
        elif due == "today":
            where.append("t.due_date = :today")
            params["today"] = today
        elif due == "week":
            week_end = (datetime_now_local() + timedelta(days=7)).strftime("%Y-%m-%d")
            where.append("t.due_date IS NOT NULL AND t.due_date >= :today AND t.due_date <= :week_end")
            params["today"] = today
            params["week_end"] = week_end
        elif due == "nodate":
            where.append("t.due_date IS NULL")

        if q and q.strip():
            where.append("(t.text LIKE :q OR n.title LIKE :q)")
            params["q"] = f"%{q.strip()}%"

        where_clause = " AND ".join(where)
        sql = f"""
            SELECT t.*, n.title AS note_title
            FROM tasks t
            LEFT JOIN notes n ON t.note_id = n.id
            WHERE {where_clause}
            ORDER BY
                t.done ASC,
                CASE t.priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END ASC,
                CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END ASC,
                t.due_date ASC,
                t.created_at DESC
            LIMIT :limit OFFSET :offset
        """
        rows = self.execute(sql, params).fetchall()
        return [_row_to_task(r) for r in rows]

    def task_stats(self) -> dict:
        today = datetime_now_local().strftime("%Y-%m-%d")
        row = self.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN t.done = 0 THEN 1 ELSE 0 END) AS open,
                SUM(CASE WHEN t.done = 1 THEN 1 ELSE 0 END) AS done,
                SUM(CASE WHEN t.done = 0 AND t.priority = 'P1' THEN 1 ELSE 0 END) AS p1,
                SUM(CASE WHEN t.done = 0 AND t.priority = 'P2' THEN 1 ELSE 0 END) AS p2,
                SUM(CASE WHEN t.done = 0 AND t.priority = 'P3' THEN 1 ELSE 0 END) AS p3,
                SUM(CASE WHEN t.done = 0 AND t.due_date IS NOT NULL AND t.due_date < :today THEN 1 ELSE 0 END) AS overdue,
                SUM(CASE WHEN t.done = 0 AND t.due_date = :today THEN 1 ELSE 0 END) AS due_today
            FROM tasks t
            LEFT JOIN notes n ON t.note_id = n.id
            WHERE ((n.archived = 0 AND n.trashed_at IS NULL) OR n.id IS NULL)
            """,
            {"today": today},
        ).fetchone()

        total = int(row["total"] or 0)
        done = int(row["done"] or 0)
        open_cnt = int(row["open"] or 0)
        rate = round(done / total, 2) if total > 0 else 0.0

        return {
            "open": open_cnt,
            "done": done,
            "total": total,
            "completion_rate": rate,
            "by_priority": {
                "P1": int(row["p1"] or 0),
                "P2": int(row["p2"] or 0),
                "P3": int(row["p3"] or 0),
            },
            "overdue": int(row["overdue"] or 0),
            "due_today": int(row["due_today"] or 0),
        }

    def task_repos(self) -> list[dict]:
        rows = self.execute(
            """
            SELECT t.repo, COUNT(*) AS count
            FROM tasks t
            LEFT JOIN notes n ON t.note_id = n.id
            WHERE t.repo IS NOT NULL AND TRIM(t.repo) != '' AND ((n.archived = 0 AND n.trashed_at IS NULL) OR n.id IS NULL)
            GROUP BY t.repo
            ORDER BY count DESC, t.repo ASC
            """
        ).fetchall()
        return [
            {"name": r["repo"], "repo": r["repo"], "count": int(r["count"])}
            for r in rows
        ]

    # ---- collections (#267 manual | #269 saved_query | #268 playlist) ----

    def insert_collection(self, data: dict) -> dict:
        now = now_iso()
        coll = {
            "id": data.get("id") or new_id(),
            "kind": data.get("kind") or "manual",
            "name": data["name"],
            "description": data.get("description") or "",
            "status": data.get("status"),
            "query": data.get("query"),
            "created_at": now,
            "updated_at": now,
        }
        if coll["kind"] not in ("manual", "saved_query", "project"):
            raise ValueError(f"unknown collection kind {coll['kind']!r}")
        self.execute(
            """
            INSERT INTO collections (id, kind, name, description, status, query, created_at, updated_at)
            VALUES (:id, :kind, :name, :description, :status, :query, :created_at, :updated_at)
            """,
            {
                **coll,
                "query": json.dumps(coll["query"], ensure_ascii=False) if coll["query"] else None,
            },
        )
        self.commit()
        return coll

    def update_collection(self, coll_id: str, changes: dict) -> dict | None:
        row = self.execute("SELECT * FROM collections WHERE id = ?", (coll_id,)).fetchone()
        if not row:
            return None
        allowed = {"name", "description", "status", "query", "kind"}
        updates = {k: v for k, v in changes.items() if k in allowed and v is not None}
        if "query" in updates and not isinstance(updates["query"], str):
            updates["query"] = json.dumps(updates["query"], ensure_ascii=False)
        if not updates:
            return self.get_collection(coll_id)
        updates["updated_at"] = now_iso()
        sets = ", ".join(f"{k} = :{k}" for k in updates)
        self.execute(f"UPDATE collections SET {sets} WHERE id = :cid", {**updates, "cid": coll_id})
        self.commit()
        return self.get_collection(coll_id)

    def get_collection(self, coll_id: str) -> dict | None:
        row = self.execute("SELECT * FROM collections WHERE id = ?", (coll_id,)).fetchone()
        return _row_to_collection(row) if row else None

    def list_collections(self) -> list[dict]:
        rows = self.execute(
            "SELECT * FROM collections ORDER BY updated_at DESC"
        ).fetchall()
        counts = {
            r["collection_id"]: r["c"]
            for r in self.execute(
                "SELECT collection_id, COUNT(*) AS c FROM collection_items GROUP BY collection_id"
            ).fetchall()
        }
        out = []
        for row in rows:
            coll = _row_to_collection(row)
            coll["item_count"] = counts.get(coll["id"], 0)
            out.append(coll)
        return out

    def delete_collection(self, coll_id: str) -> bool:
        cur = self.execute("DELETE FROM collections WHERE id = ?", (coll_id,))
        self.commit()
        return (cur.rowcount or 0) > 0

    def add_note_to_collection(self, coll_id: str, note_id: str) -> bool:
        """Append at the end of a manual collection. Idempotent per (coll, note)."""
        if not self.get_note(note_id) or not self.get_collection(coll_id):
            return False
        row = self.execute("SELECT MAX(position) AS p FROM collection_items WHERE collection_id = ?", (coll_id,)).fetchone()
        self.execute(
            "INSERT OR IGNORE INTO collection_items (collection_id, note_id, position, added_at) "
            "VALUES (?, ?, ?, ?)",
            (coll_id, note_id, (row["p"] or 0) + 1, now_iso()),
        )
        self.commit()
        return True

    def remove_note_from_collection(self, coll_id: str, note_id: str) -> bool:
        cur = self.execute(
            "DELETE FROM collection_items WHERE collection_id = ? AND note_id = ?",
            (coll_id, note_id),
        )
        self.commit()
        return (cur.rowcount or 0) > 0

    def collection_notes(self, coll: dict, limit: int = 200) -> list[dict]:
        """Notes in a collection, newest first.

        Manual/project collections read their membership table; a saved_query
        executes its stored filter live, so the collection tracks future
        matches without touching it.
        """
        if coll["kind"] == "saved_query":
            q = coll.get("query") or {}
            if isinstance(q, str):
                try:
                    q = json.loads(q)
                except json.JSONDecodeError:
                    q = {}
            if q.get("text"):
                hits = self.search(str(q["text"]), limit=limit)
                notes = [
                    n for n in hits
                    if (not q.get("tag") or q["tag"] in n["tags"])
                    and (not q.get("type") or n["type"] == q["type"])
                ]
            else:
                notes = self.list_notes(
                    limit=limit,
                    tag=q.get("tag"),
                    note_type=q.get("type"),
                    starred=bool(q.get("starred")),
                )
            return notes
        rows = self.execute(
            """
            SELECT n.* FROM collection_items ci
            JOIN notes n ON n.id = ci.note_id
            WHERE ci.collection_id = :cid AND n.trashed_at IS NULL
            ORDER BY ci.position ASC
            LIMIT :limit
            """,
            {"cid": coll["id"], "limit": limit},
        ).fetchall()
        return [_row_to_note(r) for r in rows]

    def collections_for_note(self, note_id: str) -> list[dict]:
        rows = self.execute(
            """
            SELECT c.* FROM collection_items ci
            JOIN collections c ON c.id = ci.collection_id
            WHERE ci.note_id = ?
            ORDER BY c.name COLLATE NOCASE
            """,
            (note_id,),
        ).fetchall()
        return [_row_to_collection(r) for r in rows]

    # ---- note embeddings ------------------------------------------------

    def upsert_note_embedding(
        self, note_id: str, blob: bytes, dimensions: int, model: str
    ) -> None:
        self.execute(
            """
            INSERT OR REPLACE INTO note_embeddings (note_id, embedding, dimensions, model, updated_at)
            VALUES (:nid, :blob, :dim, :model, :updated_at)
            """,
            {
                "nid": note_id,
                "blob": blob,
                "dim": dimensions,
                "model": model,
                "updated_at": now_iso(),
            },
        )
        self.commit()

    def get_note_embedding(self, note_id: str) -> dict | None:
        row = self.execute(
            "SELECT note_id, embedding, dimensions, model, updated_at FROM note_embeddings WHERE note_id = ?",
            (note_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "note_id": row["note_id"],
            "embedding": bytes(row["embedding"]),
            "dimensions": int(row["dimensions"]),
            "model": row["model"],
            "updated_at": row["updated_at"],
        }

    def count_stale_embeddings(self, model: str, dimensions: int | None = None) -> int:
        """Count active notes whose embedding is not from `model`.

        Vectors of different dimensionality cannot be compared, so these notes
        are invisible to semantic search while the new model is active.
        """
        if dimensions is None:
            row = self.execute(
                "SELECT COUNT(*) AS c FROM note_embeddings WHERE model != ?", (model,)
            ).fetchone()
        else:
            row = self.execute(
                "SELECT COUNT(*) AS c FROM note_embeddings "
                "WHERE model != ? OR dimensions != ?",
                (model, dimensions),
            ).fetchone()
        return int(row["c"])

    def prune_activity(self, before_day: str, min_seconds: int = 1) -> int:
        """Delete activity rows older than `before_day`, plus empty sessions.

        Nothing ever pruned this table, and a row is written on every window
        title change — including sub-second ones that `activity_sessions` hides
        at read time, after storing them. Returns the number of rows removed.
        """
        cur = self.execute(
            "DELETE FROM activity WHERE day < ? OR seconds < ?",
            (before_day, min_seconds),
        )
        self.commit()
        removed = cur.rowcount or 0
        if removed:
            log.info("pruned %d stale activity rows (before %s)", removed, before_day)
        return removed

    def get_all_embeddings(self) -> list[dict]:
        rows = self.execute(
            "SELECT note_id, embedding, dimensions, model, updated_at FROM note_embeddings"
        ).fetchall()
        return [
            {
                "note_id": r["note_id"],
                "embedding": bytes(r["embedding"]),
                "dimensions": int(r["dimensions"]),
                "model": r["model"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def delete_note_embedding(self, note_id: str) -> None:
        self.execute("DELETE FROM note_embeddings WHERE note_id = ?", (note_id,))
        self.commit()




# ---- serialization helpers -------------------------------------------


def _row_to_note(row: sqlite3.Row, extra: tuple[str, ...] = ()) -> dict:
    note = {
        "id": row["id"],
        "type": row["type"],
        "title": row["title"],
        "summary": row["summary"],
        "raw_text": row["raw_text"],
        "tags": json.loads(row["tags"] or "[]"),
        "action_items": json.loads(row["action_items"] or "[]"),
        "source": json.loads(row["source"] or "{}"),
        "audio_path": row["audio_path"],
        "status": row["status"],
        "error": row["error"],
        "pinned": bool(row["pinned"]),
        "archived": bool(row["archived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "processed_at": row["processed_at"],
        "capture_id": row["capture_id"] if "capture_id" in row.keys() else None,
        "source_title": row["source_title"] if "source_title" in row.keys() else None,
        "starred": bool(row["starred"]) if "starred" in row.keys() else False,
        "trashed_at": row["trashed_at"] if "trashed_at" in row.keys() else None,
        "color": row["color"] if "color" in row.keys() else None,
        "fields": json.loads(row["fields"] or "{}") if "fields" in row.keys() else {},
        "sensitive": bool(row["sensitive"]) if "sensitive" in row.keys() else False,
        "review_state": row["review_state"] if "review_state" in row.keys() else "enriched",
        "snoozed_until": row["snoozed_until"] if "snoozed_until" in row.keys() else None,
    }
    for key in extra:
        if key in row.keys():
            note[key] = row[key]
    return note


def _note_to_sql(note: dict) -> dict:
    out = dict(note)
    defaults: dict[str, object] = {"tags": [], "action_items": [], "source": {}, "fields": {}}
    for key in ("tags", "action_items", "source", "fields"):
        val = out.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            val = defaults[key]
        if not isinstance(val, str):
            out[key] = json.dumps(
                val,
                ensure_ascii=False,
                default=lambda o: o.model_dump() if hasattr(o, "model_dump") else (o.dict() if hasattr(o, "dict") else str(o)),
            )
        elif key == "source" and val.strip() in ("", "null"):
            out[key] = "{}"
    out.setdefault("title", "")
    out.setdefault("summary", "")
    out.setdefault("raw_text", "")
    out.setdefault("type", "text")
    out.setdefault("status", "pending")
    out.setdefault("error", None)
    out.setdefault("pinned", 0)
    out.setdefault("archived", 0)
    out.setdefault("starred", 0)
    out.setdefault("trashed_at", None)
    out.setdefault("color", None)
    out.setdefault("sensitive", 0)
    out.setdefault("review_state", "enriched")
    out.setdefault("snoozed_until", None)
    out.setdefault("audio_path", None)
    out.setdefault("processed_at", None)
    out.setdefault("capture_id", None)
    out.setdefault("source_title", None)
    now = now_iso()
    out.setdefault("created_at", now)
    out.setdefault("updated_at", now)
    out["pinned"] = int(bool(out.get("pinned")))
    out["archived"] = int(bool(out.get("archived")))
    out["starred"] = int(bool(out.get("starred")))
    out["sensitive"] = int(bool(out.get("sensitive")))
    return out


def _row_to_collection(row: sqlite3.Row) -> dict:
    query = row["query"]
    return {
        "id": row["id"],
        "kind": row["kind"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "query": json.loads(query) if query else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_task(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "note_id": row["note_id"],
        "note_title": row["note_title"] if "note_title" in row.keys() and row["note_title"] is not None else "",
        "text": row["text"],
        "done": bool(row["done"]),
        "priority": row["priority"],
        "due_date": row["due_date"],
        "repo": row["repo"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


def _activity_fts_query(raw: str) -> str:
    """FTS5 query for window titles.

    Window titles are paths and app names ("fleeting — routers/notes.py —
    fleeting"), not prose, so the note-oriented tokeniser is wrong here: it keeps
    only alphanumerics and would fuse "routers/notes.py" into one token that
    matches nothing. Split on every separator instead, so a search for either
    "notes" or "routers/notes.py" finds the session.
    """
    tokens = re.findall(r"[A-Za-z0-9_]+", raw)
    if not tokens:
        return '""'
    return " ".join(f'"{t}"*' for t in tokens)


def _fts_query(raw: str) -> str:
    """Build an FTS5 query from raw user input.

    Plain words become prefix queries joined by AND (implicit), quoted phrases
    are preserved. Falls back to quoted literal on parse errors.
    """
    raw = raw.strip()
    if not raw:
        return '""'
    parts = []
    for token in raw.split():
        if token.startswith('"'):
            parts.append(token if token.endswith('"') else f'{token}"')
        else:
            cleaned = "".join(ch for ch in token if ch.isalnum() or ch in "-_")
            if cleaned:
                parts.append(f'"{cleaned}"*')
    return " ".join(parts) if parts else '""'
