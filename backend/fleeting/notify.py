"""Best-effort desktop notifications (Linux: notify-send)."""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("fleeting.notify")


def send(summary: str, body: str = "") -> bool:
    binary = shutil.which("notify-send")
    if not binary:
        return False
    try:
        subprocess.run(
            [binary, "-a", "Fleeting", summary, body],
            timeout=5,
            capture_output=True,
        )
        return True
    except Exception:
        log.debug("notify-send failed", exc_info=True)
        return False
