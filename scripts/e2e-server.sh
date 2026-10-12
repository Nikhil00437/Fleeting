#!/usr/bin/env bash
# e2e-server.sh — seed a throwaway database and serve it for Playwright.
#
# Used as Playwright's `webServer`. Kept separate from scripts/demo.sh because
# this one must be hermetic and non-interactive: a test run must never start a
# vault watcher on the real ~/Documents/FleetingVault, poll the real Hyprland
# session, or call a real model.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${E2E_PORT:-7427}"

export XDG_DATA_HOME="$ROOT/.demo/data"
export XDG_CONFIG_HOME="$ROOT/.demo/config"

mkdir -p "$XDG_DATA_HOME/fleeting" "$XDG_CONFIG_HOME/fleeting" "$ROOT/.demo/vault"

# The XDG variables move the database and the config; they do not move
# paths.vault_dir, which defaults to ~/Documents/FleetingVault, and they do not
# switch off the activity collector or the LLM.
cat > "$XDG_CONFIG_HOME/fleeting/config.toml" <<EOF
[paths]
vault_dir = "$ROOT/.demo/vault"

[llm]
provider = "none"

[activity]
enabled = false
EOF

# Reseed from scratch every run. Sharing state between runs would let a test
# pass only because a previous run left the note it wanted behind.
cd "$ROOT/backend"
uv run python - <<'PY'
import os
from pathlib import Path

from fleeting.config import DB_PATH
from fleeting.db import Database
from fleeting.seed import seed_demo

for suffix in ("", "-wal", "-shm"):
    p = Path(str(DB_PATH) + suffix)
    if p.exists():
        os.remove(p)

db = Database(DB_PATH)
db.migrate()
print(f"seeded {seed_demo(db)} into {DB_PATH}", flush=True)
PY

cd "$ROOT"
exec uv run --project backend uvicorn fleeting.main:app \
  --host 127.0.0.1 --port "$PORT"