

from fastapi import HTTPException

from ..config import Config


def require_experimental(cfg: Config, flag: str) -> None:
    """404 unless `[experimental].<flag>` is on. #195

    404 rather than 403 on purpose. A 403 confirms the route exists, which is
    the thing you are trying to avoid saying; 404 is what an endpoint that was
    never written looks like, and it keeps the API contract check quiet about a
    frontend calling a route the server does not serve.

    The flag is for taste, not access control. Every route still inherits the
    host guard, the bearer token and the origin check, and turning a flag off
    must never be what keeps someone out of something they could already reach
    by another route.
    """
    if not getattr(cfg.experimental, flag, False):
        raise HTTPException(404, "Not Found")
