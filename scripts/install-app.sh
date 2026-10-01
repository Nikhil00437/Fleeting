#!/usr/bin/env bash
# Install Fleeting as a desktop app: icon, .desktop entry, CLI symlinks.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

echo "==> app icon (hicolor)"
ICON_DIR="$HOME/.local/share/icons/hicolor"
mkdir -p "$ICON_DIR/scalable/apps" "$ICON_DIR/512x512/apps"
cp deploy/fleeting.svg "$ICON_DIR/scalable/apps/fleeting.svg"
if command -v rsvg-convert > /dev/null 2>&1; then
  rsvg-convert -w 512 -h 512 deploy/fleeting.svg -o "$ICON_DIR/512x512/apps/fleeting.png"
fi

echo "==> desktop entry"
mkdir -p "$HOME/.local/share/applications"
sed "s|/home/nikhil/Projects/fleeting|$ROOT|g" deploy/fleeting.desktop > "$HOME/.local/share/applications/fleeting.desktop"

echo "==> CLI tools on PATH"
mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/bin/flee" "$HOME/.local/bin/flee"
ln -sf "$ROOT/bin/fleeting-app" "$HOME/.local/bin/fleeting-app"

update-desktop-database "$HOME/.local/share/applications" 2> /dev/null || true
gtk-update-icon-cache -f -t "$ICON_DIR" 2> /dev/null || true

cat <<'EOF'

Installed:
  - "Fleeting" in your app launcher (wofi/rofi) — opens as a desktop window
  - `flee` CLI for quick capture from any shell

Optional service (starts the backend at login):
  cp deploy/fleeting.service ~/.config/systemd/user/
  systemctl --user daemon-reload && systemctl --user enable --now fleeting
EOF
