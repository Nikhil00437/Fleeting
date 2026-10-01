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
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Database:
    """Thread-local connections against one SQLite file."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        self._local = threading.local()

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
        conn = self.conn
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= current:
                continue
            log.info("applying migration v%d", version)
            conn.executescript(script)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def commit(self) -> None:
        self.conn.commit()

    # ---- note helpers -------------------------------------------------

    def insert_note(self, note: dict) -> dict:
        note = {**note, "id": note.get("id") or new_id()}
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
        return self.get_note(note["id"])  # type: ignore[return-value]

    def update_note(self, note_id: str, changes: dict) -> dict | None:
        if not changes:
            return self.get_note(note_id)
        changes = {**changes, "updated_at": changes.get("updated_at") or now_iso()}
        sets = ", ".join(f"{key} = :{key}" for key in changes)
        changes_sql = dict(changes)
        # JSON-encode list/dict fields
        for key in ("tags", "action_items", "source"):
            if key in changes_sql and not isinstance(changes_sql[key], str):
                changes_sql[key] = json.dumps(changes_sql[key], ensure_ascii=False)
        cur = self.execute(f"UPDATE notes SET {sets} WHERE id = :_id", {**changes_sql, "_id": note_id})
        if cur.rowcount == 0:
            return None
        self.commit()
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
        open_tasks = 0
        done_tasks = 0
        for r in self.execute("SELECT action_items FROM notes WHERE archived = 0").fetchall():
            for item in json.loads(r["action_items"] or "[]"):
                if item.get("done"):
                    done_tasks += 1
                else:
                    open_tasks += 1
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
        results: list[dict] = []
        rows = self.execute(
            "SELECT id, title, action_items, created_at FROM notes "
            "WHERE archived = 0 ORDER BY created_at DESC LIMIT :limit",
            {"limit": limit},
        ).fetchall()
        for r in rows:
            for item in json.loads(r["action_items"] or "[]"):
                is_done = bool(item.get("done"))
                if include_done or not is_done:
                    results.append(
                        {
                            "note_id": r["id"],
                            "note_title": r["title"],
                            "item_id": item.get("id"),
                            "text": item.get("text", ""),
                            "done": is_done,
                            "created_at": r["created_at"],
                        }
                    )
        return results


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
            out[key] = json.dumps(val, ensure_ascii=False)
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
    out["pinned"] = int(bool(out.get("pinned")))
    out["archived"] = int(bool(out.get("archived")))
    return out


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
