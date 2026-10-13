"""#497 example hook: append a line to a log when a note is captured.

Copy this file to `~/.config/fleeting/hooks/` and edit it. Anything that is not
an `on_*` function is ignored, so helpers and imports are fine.

The payload is a dict — for `note.created` it has at least `id`, `title`,
`raw_text`, `created_at` and `tags`.

Runs as a subprocess with a 10 second timeout. A hook that raises is logged and
skipped; it never stops the note being saved. Keep it fast.
"""

import json
import os
import pathlib

LOG = pathlib.Path(os.environ.get("FLEETING_HOOK_LOG", "~/fleeting-hooks.log")).expanduser()


def on_note_created(payload):
    """Appended to on every capture. No network, no secrets, no blocking calls."""
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "at": payload.get("created_at"),
                    "id": payload.get("id"),
                    "title": (payload.get("title") or "")[:80],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
