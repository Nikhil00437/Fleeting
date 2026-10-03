"""FastAPI application factory.

Production mode serves the built SPA from ../frontend/dist (falling back to a
minimal placeholder when the frontend hasn't been built).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .activity import ActivityCollector
from .config import LOG_PATH, Config, ensure_dirs
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


def _setup_logging() -> None:
    ensure_dirs()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
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

        digest_lock = asyncio.Lock()
        st.digest_lock = digest_lock

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    from .routers import activity, assistant, capture, notes, processes, search, settings, system, tasks

    app.include_router(notes.router)
    app.include_router(capture.router)
    app.include_router(tasks.router)
    app.include_router(search.router)
    app.include_router(settings.router)
    app.include_router(system.router)
    app.include_router(activity.router)
    app.include_router(assistant.router)
    app.include_router(processes.router)

    _mount_frontend(app)
    return app


def _db_path():
    from .config import DB_PATH

    return DB_PATH


async def _autodetect_llm_model(cfg: Config) -> None:
    """On first run, pick the first available model from the local server."""
    import httpx

    if cfg.llm.provider == "none" or cfg.llm.model:
        return
    base = cfg.llm.base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            if cfg.llm.provider == "ollama":
                r = await client.get(f"{base}/api/tags")
                names = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
            else:
                r = await client.get(f"{base}/v1/models")
                names = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
        if names:
            cfg.llm.model = names[0]
            from .config import save_config

            save_config(cfg)
            log.info("auto-detected local model: %s", names[0])
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
