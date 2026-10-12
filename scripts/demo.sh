#!/usr/bin/env bash
# demo.sh — run Fleeting against a throwaway seeded database.
#
#   scripts/demo.sh              seed if empty, then start the API on :7426
#   scripts/demo.sh --reseed     wipe the demo data and seed again
#   scripts/demo.sh --days 30    a longer window
#
# Nothing here touches ~/.local/share/fleeting. The demo lives entirely under
# .demo/ in this repo, via the XDG variables `fleeting.config.xdg()` already
# honours — no demo flag in the app, and no way to point it at the real
# database by accident.
#
# LLM and whisper are off, so this works with no model running and no network.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="$ROOT/.demo"
DAYS=14
RESEED=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reseed) RESEED=1; shift ;;
    --days) DAYS="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

export XDG_DATA_HOME="$DEMO_DIR/data"
export XDG_CONFIG_HOME="$DEMO_DIR/config"
export FLEETING_URL="http://127.0.0.1:7426"

mkdir -p "$XDG_DATA_HOME/fleeting" "$XDG_CONFIG_HOME/fleeting" "$DEMO_DIR/vault"

if [[ "$RESEED" == "1" ]]; then
  rm -f "$XDG_DATA_HOME/fleeting/fleeting.db"*
  echo "reseeding"
fi

cd "$ROOT/backend"
uv run python - "$DAYS" <<'PY'
import sys

from fleeting.config import DB_PATH
from fleeting.db import Database
from fleeting.seed import seed_demo

days = int(sys.argv[1])
db = Database(DB_PATH)
db.migrate()
counts = seed_demo(db, days=days)
print(
    f"seeded {counts['notes']} notes, {counts['tasks']} tasks, "
    f"{counts['activity']} activity sessions into {DB_PATH}"
)
PY

cat <<EOF

  seeded demo at .demo/data/fleeting/fleeting.db  (isolated — your real data untouched)

    XDG_DATA_HOME=$XDG_DATA_HOME
    XDG_CONFIG_HOME=$XDG_CONFIG_HOME

  starting the API on :7426 with the frontend. Ctrl-C to stop.

EOF

cd "$ROOT"
exec uv run --project backend uvicorn fleeting.main:app --host 127.0.0.1 --port 7426