"""#495: packs over HTTP. The format is in `services/packs.py`; this is the
transport and the security envelope.

`dir` is a query parameter because the point is to install a pack from a folder
the user chose — a USB stick, a checkout, a directory of experiments — and
hardcoding one location would make that impossible. It is not a hole: this app
is local-only behind a host allow-list and a bearer token, and the caller could
already read any file it can name through a dozen other endpoints. What the
token buys is that a page in your browser cannot do this on its own.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from ..config import save_config
from ..services.packs import install_pack, load_pack_set, search_dirs

router = APIRouter(prefix="/api", tags=["packs"])
log = logging.getLogger("fleeting.packs")


@router.get("/packs")
def list_packs_endpoint(
    request: Request, dir: str | None = Query(default=None)
) -> dict:
    st = request.app.state.st
    # `dir` restricts to exactly that folder; otherwise the user's own packs
    # come first and the bundled ones fill in behind them (#400).
    dirs = [Path(dir)] if dir else search_dirs()
    packs, errors = load_pack_set(dirs, st.cfg)
    return {"packs": packs, "errors": errors}


@router.post("/packs/{name}/install")
def install_pack_endpoint(request: Request, name: str, dir: str | None = Query(default=None)) -> dict:
    st = request.app.state.st
    dirs = [Path(dir)] if dir else search_dirs()
    try:
        pack = install_pack(dirs, name, st.cfg, save_config)
    except KeyError:
        # Listing the folder is more useful than "not found": the file is
        # probably there under a different name.
        available = [p["name"] for p in load_pack_set(dirs, st.cfg)[0]]
        log.info("pack install: %r not found in %s", name, ", ".join(str(d) for d in dirs))
        raise HTTPException(404, f"no pack named {name!r}; available: {', '.join(available) or 'none'}")
    return {"installed": pack["name"], "theme": pack["theme"], "prompts": sorted(pack["prompts"])}