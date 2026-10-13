"""#499: plugins over HTTP. The format and its validation are in
`services/plugins.py`; this is transport.

`dir` is a query parameter for the same reason as #495's packs: the point is to
inspect a folder you were sent before installing anything from it. This app is
local-only behind a host allow-list and a bearer token, and listing a directory
reads nothing but `plugin.json`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request

from ..services.plugins import API_VERSION, load_plugins, search_dirs

router = APIRouter(prefix="/api", tags=["plugins"])


@router.get("/plugins")
def list_plugins_endpoint(request: Request, dir: str | None = Query(default=None)) -> dict:
    st = request.app.state.st
    dirs = [Path(dir)] if dir else search_dirs()
    plugins, errors = load_plugins(dirs[0], st.cfg)
    return {
        "plugins": plugins,
        "errors": errors,
        "api_version": API_VERSION,
    }