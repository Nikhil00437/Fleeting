#!/usr/bin/env bash
# Restart the Fleeting dev/production server on 127.0.0.1:7425.
set -u
PATTERN='uvicorn fleeting'
pkill -f "$PATTERN" 2>/dev/null
sleep 1
cd "$(dirname "$0")/../backend" || exit 1
setsid uv run uvicorn fleeting.main:app --host 127.0.0.1 --port 7425 \
  > /tmp/fleeting-server.log 2>&1 < /dev/null &
sleep 4
for _ in 1 2 3 4 5; do
  if curl -sf --max-time 2 http://127.0.0.1:7425/api/health > /dev/null; then
    echo "fleeting: up on http://127.0.0.1:7425"
    exit 0
  fi
  sleep 2
done
echo "fleeting: FAILED to start — last log lines:"
tail -5 /tmp/fleeting-server.log
exit 1
