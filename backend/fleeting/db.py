"""SQLite persistence layer.

Single-connection-per-thread SQLite with WAL, schema migrations tracked in a
`schema_version` table, and an external-content FTS5 index kept in sync with
triggers. All timestamps are UTC ISO-8601 strings.
"""

from __future__ import annotations

import json
import logging
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
]


NOTE_COLUMNS = frozenset({
    "type", "title", "summary", "raw_text", "tags", "action_items", "source",
    "audio_path", "status", "error", "pinned", "archived",
    "created_at", "updated_at", "processed_at",
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
        # Attempt one-time migration if database schema exists
        try:
            self._migrate_action_items()
        except sqlite3.OperationalError:
            pass

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
        self._migrate_action_items()

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
        self.execute(
            """
            INSERT INTO notes (id, type, title, summary, raw_text, tags, action_items,
                               source, audio_path, status, error, pinned, archived,
                               created_at, updated_at, processed_at)
            VALUES (:id, :type, :title, :summary, :raw_text, :tags, :action_items,
                    :source, :audio_path, :status, :error, :pinned, :archived,
                    :created_at, :updated_at, :processed_at)
            """,
            _note_to_sql(note),
        )
        self.commit()
        if note.get("action_items"):
            self._sync_tasks_from_note(note["id"], note["action_items"])
            self._sync_note_action_items(note["id"])
        return self.get_note(note["id"])  # type: ignore[return-value]

    def update_note(self, note_id: str, changes: dict) -> dict | None:
        if not changes:
            return self.get_note(note_id)
        # Column names cannot be bound as SQL parameters, so drop anything
        # off-schema rather than splicing it into the SET clause.
        changes = {k: v for k, v in changes.items() if k in NOTE_COLUMNS}
        if not changes:
            return self.get_note(note_id)
        changes = {**changes, "updated_at": changes.get("updated_at") or now_iso()}
        sets = ", ".join(f"{key} = :{key}" for key in changes)
        changes_sql = dict(changes)
        # JSON-encode list/dict fields
        for key in ("tags", "action_items", "source"):
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

    def get_note(self, note_id: str) -> dict | None:
        row = self.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
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
    ) -> list[dict]:
        where = ["archived = :archived"]
        params: dict = {"archived": 1 if archived else 0, "limit": limit, "offset": offset}
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

    def delete_note(self, note_id: str) -> dict | None:
        note = self.get_note(note_id)
        if note:
            self.execute("DELETE FROM tasks WHERE note_id = ?", (note_id,))
            self.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self.commit()
        return note

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

    # ---- search --------------------------------------------------------

    def search(self, query: str, *, limit: int = 50) -> list[dict]:
        """FTS5 match query, ranked, with highlighted snippets."""
        rows = self.execute(
            """
            SELECT n.*, bm25(notes_fts) AS rank,
                   snippet(notes_fts, 1, '[[', ']]', '…', 24) AS snippet
            FROM notes_fts f
            JOIN notes n ON n.rowid = f.rowid
            WHERE notes_fts MATCH :q
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
            WHERE notes.archived = 0
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
            """
        ).fetchone()
        t_row = self.execute(
            """
            SELECT
              SUM(CASE WHEN t.done = 0 THEN 1 ELSE 0 END) AS open_tasks,
              SUM(CASE WHEN t.done = 1 THEN 1 ELSE 0 END) AS done_tasks
            FROM tasks t
            LEFT JOIN notes n ON t.note_id = n.id
            WHERE (n.archived = 0 OR n.id IS NULL)
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

    def open_tasks(self, limit: int = 200, include_done: bool = False) -> list[dict]:
        """Action items joined with their note (unfinished only by default)."""
        status = "all" if include_done else "open"
        tasks = self.list_tasks(status=status, limit=limit)
        return [
            {
                "note_id": t["note_id"],
                "note_title": t["note_title"],
                "item_id": t["id"],
                "text": t["text"],
                "done": t["done"],
                "created_at": t["created_at"],
            }
            for t in tasks
        ]

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
        where = ["(n.archived = 0 OR n.id IS NULL)"]
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
            WHERE (n.archived = 0 OR n.id IS NULL)
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
            WHERE t.repo IS NOT NULL AND TRIM(t.repo) != '' AND (n.archived = 0 OR n.id IS NULL)
            GROUP BY t.repo
            ORDER BY count DESC, t.repo ASC
            """
        ).fetchall()
        return [
            {"name": r["repo"], "repo": r["repo"], "count": int(r["count"])}
            for r in rows
        ]

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
    }
    for key in extra:
        if key in row.keys():
            note[key] = row[key]
    return note


def _note_to_sql(note: dict) -> dict:
    out = dict(note)
    defaults: dict[str, object] = {"tags": [], "action_items": [], "source": {}}
    for key in ("tags", "action_items", "source"):
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
    out.setdefault("audio_path", None)
    out.setdefault("processed_at", None)
    now = now_iso()
    out.setdefault("created_at", now)
    out.setdefault("updated_at", now)
    out["pinned"] = int(bool(out.get("pinned")))
    out["archived"] = int(bool(out.get("archived")))
    return out


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
