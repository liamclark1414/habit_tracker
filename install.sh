#!/usr/bin/env bash
# Adds Habit Tracker to your desktop and application menu.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$DIR/app.py"
ENTRY="[Desktop Entry]
Type=Application
Name=Habit Tracker
Comment=Track your daily habits
Exec=python3 \"$DIR/app.py\"
Icon=$DIR/static/icon.svg
Terminal=false
Categories=Utility;"
mkdir -p ~/.local/share/applications
echo "$ENTRY" > ~/.local/share/applications/habit-tracker.desktop
DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP" ]; then
  echo "$ENTRY" > "$DESKTOP/habit-tracker.desktop"
  chmod +x "$DESKTOP/habit-tracker.desktop"
  gio set "$DESKTOP/habit-tracker.desktop" metadata::trusted true 2>/dev/null || true
fi
echo "Installed. Launch 'Habit Tracker' from your desktop or app menu."
