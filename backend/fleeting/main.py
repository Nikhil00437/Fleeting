"""FastAPI application factory.

Production mode serves the built SPA from ../frontend/dist (falling back to a
minimal placeholder when the frontend hasn't been built).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .activity import ActivityCollector
from .config import Config, ensure_dirs
from .db import Database
from .events import EventBus
from .process import Processor
from .services.transcribe import Transcriber
from .state import AppState

log = logging.getLogger("fleeting")

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_VITE_DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def _allowed_origins(cfg: Config) -> set[str]:
    """Origins permitted to call the API: the served app plus the Vite dev server."""
    hosts = {cfg.server.host, "127.0.0.1", "localhost"}
    return {f"http://{h}:{cfg.server.port}" for h in hosts} | set(_VITE_DEV_ORIGINS)


def _maybe_backfill_embeddings(db: Database, cfg: Config, bus, st=None) -> "asyncio.Task | None":
    """Schedule the embedding migration if the corpus is on an older model.

    Turning the LLM on changes the embedding dimensionality, and vectors of
    different lengths cannot be compared — so without this, every note captured
    before the switch is invisible to semantic search, silently. `backfill_embeddings`
    existed but nothing called it, which is why that went unnoticed.

    Returns the task, or None when there is nothing to migrate (no LLM, or the
    corpus is already current — the common case, so boot stays cheap).
    """
    from .routers.settings import backfill_embeddings_stream
    from .routers.system import _embedding_status

    if cfg.llm.provider == "none":
        return None

    class _St:
        pass

    probe = _St()
    probe.cfg = cfg
    probe.db = db
    try:
        model, stale = _embedding_status(probe)
    except Exception:
        log.warning("could not check embedding freshness", exc_info=True)
        return None
    if stale == 0:
        return None

    log.info("%d note(s) on an older embedding model than %s — migrating", stale, model)

    async def _run() -> None:
        try:
            await asyncio.to_thread(backfill_embeddings_stream, db, cfg, bus)
        except Exception:
            log.exception("embedding backfill failed")
        finally:
            if st is not None:
                st.backfill_task = None

    try:
        return asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        # No running loop (e.g. called from a sync context in tests).
        return None


def _setup_logging() -> None:
    ensure_dirs()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        # read at call time: a bound import cannot be redirected, and the test
        # suite must not append to the user's real log.
        from .config import LOG_PATH

        handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def create_app(cfg: Config | None = None, *, load_from_disk: bool = True) -> FastAPI:
    _setup_logging()
    ensure_dirs()
    if cfg is None and load_from_disk:
        from .config import load_config

        cfg = load_config()
    cfg = cfg or Config()

    # #443/#444: pin the process-wide "today" and holiday set before any
    # date query can run.
    from .services import calendar_svc

    calendar_svc.configure(cfg.tasks.timezone, cfg.tasks.holidays)

    db = Database(_db_path())
    db.migrate()
    bus = EventBus()
    transcriber = Transcriber(
        cfg.transcribe,
        on_progress=lambda p: bus.publish("whisper.progress", p),
    )
    processor = Processor(db, cfg, bus, transcriber)
    st = AppState(cfg=cfg, db=db, bus=bus, transcriber=transcriber, processor=processor)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st.started_at = time.time()
        await _autodetect_llm_model(cfg)
        processor.start()

        async def rollover(day: str) -> None:
            """Midnight job: write the past-24-hours report for the finished day."""
            from .services import dailylog

            await dailylog.generate_daily_log(db, cfg, day, rolling=True)
            bus.publish("dailylog.updated", {"day": day, "kind": "daily-report"})

        async def backfill_yesterday() -> None:
            """If the machine was off at midnight, produce yesterday's report on boot."""
            from datetime import datetime, timedelta

            from .services import dailylog

            await asyncio.sleep(3)  # let the collector settle first
            yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
            if db.get_daily_log(yesterday) or not db.activity_sessions(yesterday):
                return
            try:
                await dailylog.generate_daily_log(db, cfg, yesterday, rolling=True)
                bus.publish("dailylog.updated", {"day": yesterday, "kind": "daily-report"})
                log.info("backfilled daily report for %s", yesterday)
            except Exception:
                log.exception("daily report backfill for %s failed", yesterday)

        async def backfill_weekly() -> None:
            """On a Monday, write last week's summary if it is missing.

            A week is only summarisable once it is over, so this runs on boot
            rather than at a fixed hour — same reasoning as the daily backfill:
            the laptop is usually asleep at midnight.
            """
            from .services import weeklylog

            await asyncio.sleep(5)  # let the collector settle; git scan is slower
            start = weeklylog.previous_week_start()
            if db.get_weekly_log(start):
                return
            try:
                await weeklylog.generate_weekly_log(db, cfg, start, bus=bus)
                log.info("backfilled weekly report for %s", start)
            except ValueError:
                log.info("no tracked activity in the week of %s — skipped", start)
            except Exception:
                log.exception("weekly report backfill for %s failed", start)

        digest_lock = asyncio.Lock()
        st.digest_lock = digest_lock

        async def remind_due_tasks() -> None:
            """#27: one boot-time desktop nudge about overdue/due-today tasks."""
            from . import notify
            from .services.task_reminders import due_task_summary

            await asyncio.sleep(8)
            try:
                s = due_task_summary(db)
                if not s["total"]:
                    return
                lines = "\n".join(f"• {t}" for t in s["top"])
                more = s["total"] - len(s["top"])
                if more > 0:
                    lines += f"\n…and {more} more"
                notify.send(
                    f"Fleeting — {s['overdue']} overdue, {s['today']} due today",
                    lines,
                )
            except Exception:
                log.exception("task due reminder failed")

        asyncio.get_running_loop().create_task(remind_due_tasks())

        async def generate_milestone_digest(day: str, hours: int) -> None:
            if digest_lock.locked():
                log.info("milestone digest generation for %s (%d hrs) skipped: already in progress", day, hours)
                return
            async with digest_lock:
                from .services import dailylog

                await dailylog.generate_daily_log(db, cfg, day, rolling=True)
                bus.publish("dailylog.updated", {"day": day, "kind": "daily-report", "hours": hours})

        st.activity = ActivityCollector(
            db,
            cfg.activity,
            on_day_rollover=rollover,
            on_screentime_milestone=generate_milestone_digest,
            on_tick=lambda session: bus.publish("activity.live", {"session": session}),
        )
        activity_task = None
        if cfg.activity.enabled:
            activity_task = asyncio.get_running_loop().create_task(st.activity.run())
            asyncio.get_running_loop().create_task(backfill_yesterday())

        # Weekly summary only makes sense on a Monday, and only when asked for.
        if cfg.activity.enabled and cfg.activity.auto_weekly_log:
            today = datetime.now().astimezone()
            if today.weekday() == 0:  # Monday
                asyncio.get_running_loop().create_task(backfill_weekly())

        st.vault_watcher = None
        if cfg.paths.vault_sync:
            from .config import expand_path
            from .services.vault_watcher import VaultWatcher, sync_file_change

            vault_dir = expand_path(cfg.paths.vault_dir)
            try:
                vault_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            if vault_dir.exists():
                loop = asyncio.get_running_loop()

                def on_vault_change(p: Path) -> None:
                    try:
                        if loop.is_running():
                            loop.call_soon_threadsafe(sync_file_change, p, st.db, st.bus, st.cfg)
                            return
                    except Exception:
                        pass
                    try:
                        sync_file_change(p, st.db, st.bus, st.cfg)
                    except Exception:
                        log.exception("Error syncing vault file %s", p)

                st.vault_watcher = VaultWatcher(
                    vault_dir,
                    on_change=on_vault_change,
                    db=st.db,
                    bus=st.bus,
                    cfg=st.cfg,
                )
                st.vault_watcher.start()

        recovered = await processor.recover_unfinished()
        if recovered:
            log.info("re-queued %d unfinished capture(s)", recovered)
        # The activity table grew forever: a row per window-title change,
        # including sub-second rows that reads filter out after storing them.
        # Retention knob, not a hardcoded constant, so it can be tuned without
        # a code change. Daily reports only ever look back 24h, so a short
        # window is enough.
        retention_days = max(1, int(getattr(cfg.activity, "retention_days", 30) or 30))
        cutoff = (datetime.now().astimezone() - timedelta(days=retention_days)).strftime(
            "%Y-%m-%d"
        )
        try:
            pruned = db.prune_activity(before_day=cutoff)
            if pruned:
                log.info("pruned %d activity rows older than %s", pruned, cutoff)
        except Exception:
            log.exception("activity prune failed")

        # #274: auto-purge notes whose trash retention window has lapsed.
        # Runs on boot like the activity prune — the app is a tray app, not a
        # daemon with a scheduler, so boot is the reliable tick.
        trash_days = int(getattr(cfg.notes, "trash_retention_days", 30) or 0)
        if trash_days > 0:
            from .services import markdown

            try:
                for purged in db.purge_expired_trash(
                    trash_days, audio_root=st.cfg_audio_dir(), attachments_root=st.cfg_attachments_dir()
                ):
                    markdown.remove_note(cfg.paths, purged)
                    bus.publish("note.deleted", {"id": purged["id"]})
            except Exception:
                log.exception("trash purge failed")

        # Migrate the embedding corpus if the model changed since last run.
        backfill_task = _maybe_backfill_embeddings(db, cfg, bus, st)
        if backfill_task is not None:
            st.backfill_task = backfill_task

        log.info("fleeting %s ready on http://%s:%d", __version__, cfg.server.host, cfg.server.port)
        yield
        if activity_task:
            activity_task.cancel()
        if st.vault_watcher:
            st.vault_watcher.stop()
        processor.stop()

    app = FastAPI(title="Fleeting", version=__version__, lifespan=lifespan)
    app.state.st = st

    allowed_origins = _allowed_origins(cfg)
    allowed_hosts = {h.lower() for h in {cfg.server.host, "127.0.0.1", "localhost"}}
    st.api_token = cfg.activity.api_token.strip() or None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Endpoints the SPA must reach before it can present a token, or that are
    # needed to obtain one. Health is included so the UI can still detect a
    # live server when its token is wrong.
    _TOKEN_EXEMPT = frozenset({"/api/health"})

    @app.middleware("http")
    async def guard_api(request: Request, call_next):
        """Validate Host, then require a bearer token on mutating /api calls.

        Host first: a rebound DNS name still arrives carrying the attacker's
        Host header, and the Origin check below cannot see that.
        """
        path = request.url.path
        if path.startswith("/api"):
            host = (request.headers.get("host") or "").split(":")[0].lower()
            if host and host not in allowed_hosts:
                log.warning("blocked request with foreign Host header %r", host)
                return JSONResponse({"detail": "invalid host"}, status_code=421)

        if (
            st.api_token
            and path.startswith("/api")
            and path not in _TOKEN_EXEMPT
            and request.method not in _SAFE_METHODS
        ):
            header = request.headers.get("authorization") or ""
            scheme, _, presented = header.partition(" ")
            # compare_digest avoids leaking the token through response timing.
            if scheme.lower() != "bearer" or not secrets.compare_digest(
                presented, st.api_token
            ):
                log.warning("blocked unauthenticated %s %s", request.method, path)
                return JSONResponse({"detail": "authentication required"}, status_code=401)

        return await call_next(request)

    @app.middleware("http")
    async def guard_cross_origin_writes(request: Request, call_next):
        """Reject side-effecting /api requests that arrive from a foreign origin.

        CORS stops a hostile page from *reading* a response, not from *sending* a
        simple request, so without this a plain form POST to 127.0.0.1 can kill
        processes and delete notes. A missing Origin header means a non-browser
        client (curl, the flee CLI) and is allowed through; "null" is rejected
        because it is what a sandboxed iframe sends.
        """
        if request.method not in _SAFE_METHODS and request.url.path.startswith("/api"):
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins:
                log.warning(
                    "blocked cross-origin %s %s from %s",
                    request.method,
                    request.url.path,
                    origin,
                )
                return JSONResponse(
                    {"detail": "cross-origin request blocked"}, status_code=403
                )
        return await call_next(request)

    @app.middleware("http")
    async def no_store_api(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    from .routers import (
        activity,
        assistant,
        capture,
        cleanup,
        collections,
        notes,
        processes,
        rules,
        search,
        settings,
        system,
        tasks,
    )

    app.include_router(notes.router)
    app.include_router(notes.trash_router)
    app.include_router(collections.router)
    app.include_router(rules.router)
    app.include_router(cleanup.router)
    app.include_router(capture.router)
    app.include_router(tasks.router)
    app.include_router(search.router)
    app.include_router(settings.router)
    app.include_router(system.router)
    app.include_router(activity.router)
    app.include_router(activity.daily_router)
    app.include_router(assistant.router)
    app.include_router(processes.router)
    from .routers import templates

    app.include_router(templates.router)
    app.include_router(templates.profiles_router)

    _mount_frontend(app)
    return app


def _db_path():
    from .config import DB_PATH

    return DB_PATH


async def _autodetect_llm_model(cfg: Config) -> None:
    """On first run, pick a chat-capable model from the local server.

    Embedding-only models are skipped: pointing enrichment at one makes every
    capture silently fall back to heuristics, which is worse than leaving the
    model unset and showing the user an empty picker.
    """
    import httpx

    from .services.llm import auth_headers, chat_model_names

    if cfg.llm.provider == "none" or cfg.llm.model:
        return
    base = cfg.llm.base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=4, headers=auth_headers(cfg.llm)) as client:
            if cfg.llm.provider == "ollama":
                r = await client.get(f"{base}/api/tags")
                r.raise_for_status()
                entries = r.json().get("models", [])
            else:
                r = await client.get(f"{base}/v1/models")
                r.raise_for_status()
                entries = r.json().get("data", [])
        names = chat_model_names(entries, cfg.llm.provider)
        if names:
            cfg.llm.model = names[0]
            from .config import save_config

            save_config(cfg)
            log.info("auto-detected local model: %s", names[0])
        else:
            log.info("no chat-capable model at %s — heuristic enrichment will be used", base)
    except Exception:
        log.info("no local LLM reachable at %s — heuristic enrichment will be used", base)


def _mount_frontend(app: FastAPI) -> None:
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if not dist.exists():
        # fallback: repo layout when running from a checkout elsewhere
        dist = Path.cwd() / "frontend" / "dist"

    if dist.exists() and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

        log.info("serving frontend from %s", dist)
    else:
        log.warning("frontend build not found — API-only mode")

        @app.get("/", include_in_schema=False)
        async def placeholder():
            return JSONResponse(
                {
                    "name": "fleeting",
                    "version": __version__,
                    "hint": "frontend not built — run scripts/install.sh, or see README.md",
                }
            )


app = create_app()
