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

## Auto-tracking website time (Firefox extension)
Habits can have a daily goal in minutes and a website to auto-track (e.g. `keybr.com`, goal 15).
The extension in `extension/` counts time while a keybr tab is focused and you've typed in the last 30 seconds,
then sends it to the app. If the app is closed, time is saved in the extension and sent the next time the app runs.
The habit is ticked automatically once the goal is reached.

To track other sites, add them to `content_scripts.matches` in `extension/manifest.json`.

**Load it:** open `about:debugging#/runtime/this-firefox` → *Load Temporary Add-on…* → pick `extension/manifest.json`.
Standard Firefox removes temporary add-ons on restart; to keep it installed, sign it for free as an unlisted add-on
(`npx web-ext sign --channel=unlisted` in `extension/`, with an addons.mozilla.org API key) and install the resulting `.xpi`.

## Strava auto-tracking (runs, rides, walks, swims)
Click **⚙ Connections** and follow the steps to connect your own Strava API app (free, takes ~2 minutes;
callback domain `localhost`). Then edit a habit and pick a Strava activity type and what counts as done:
any activity, a minimum distance (km or miles), or a minimum moving time — per day or per week (e.g. 15 miles a week). The last year of activities is imported, so streaks
and history fill in straight away; new activities sync on launch and every 15 minutes while the app is open. Your full Strava history is imported, and a **Personal bests** panel shows your fastest 400m–marathon efforts across every run (worked out gradually within Strava's 100-requests-per-15-minutes limit).
Garmin users: link Garmin Connect to Strava (Garmin Connect → Settings → Connected Apps) and runs flow through.
