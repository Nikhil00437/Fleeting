#!/usr/bin/env bash
# Fleeting one-shot installer: backend env + frontend build.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

echo "==> backend: uv sync"
(cd backend && uv sync)

echo "==> frontend: bun install + build"
(cd frontend && bun install && bun run build) || {
  echo "bun failed, trying npm…"
  (cd frontend && npm install && npm run build)
}

echo "==> tools check"
for tool in ffmpeg yt-dlp; do
  command -v "$tool" > /dev/null || echo "  ⚠ '$tool' missing — install it: sudo pacman -S $tool"
done
curl -sf --max-time 2 http://127.0.0.1:11434/api/tags > /dev/null \
  && echo "  ✓ ollama reachable" \
  || echo "  ⚠ ollama not reachable — notes will use heuristic enrichment"

cat <<EOF

Done. Start the server:

  $ROOT/scripts/dev-restart.sh      # or:
  systemctl --user enable --now fleeting   # after copying deploy/fleeting.service

Then open http://127.0.0.1:7425
EOF
