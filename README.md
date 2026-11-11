# Habit Tracker

A local, private habit tracker for the desktop. Pure Python standard library — no dependencies.

## Features
- Daily check-offs with current and best streaks
- Per-habit schedules (every day, weekdays, or any custom set of days)
- 18-week history heatmap — click any past day to fix it
- Light/dark mode follows your system

## Install
```bash
./install.sh
```
This adds a **Habit Tracker** icon to your desktop and app menu. Or run it directly with `python3 app.py`.

The app opens in a Chrome/Chromium app window if one is installed, otherwise your default browser. It stops itself about 90 seconds after the window is closed.

Data is stored in `~/.local/share/habit_tracker/habits.db`.
