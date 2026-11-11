#!/usr/bin/env python3
"""Habit Tracker - a local, dependency-free habit tracking app.

Runs a small HTTP server on localhost backed by SQLite and opens the UI in
a browser window. The server shuts itself down a while after the window closes.
"""
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("HABIT_TRACKER_PORT", "8765"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "habit_tracker"
DB_PATH = DATA_DIR / "habits.db"
IDLE_TIMEOUT = 90  # seconds without a heartbeat before shutting down

_last_seen = time.time()
_db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#4f8cff',
                days TEXT NOT NULL DEFAULT '0123456',  -- weekdays, Mon=0
                created TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS checks (
                habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                day TEXT NOT NULL,
                PRIMARY KEY (habit_id, day)
            );
            CREATE TABLE IF NOT EXISTS activity (
                habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                day TEXT NOT NULL,
                seconds INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (habit_id, day)
            );
            """
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(habits)")}
        if "goal_minutes" not in cols:
            conn.execute("ALTER TABLE habits ADD COLUMN goal_minutes INTEGER NOT NULL DEFAULT 0")
        if "auto_domain" not in cols:
            conn.execute("ALTER TABLE habits ADD COLUMN auto_domain TEXT NOT NULL DEFAULT ''")


def scheduled(days, d):
    return str(d.weekday()) in days


def streaks(days, done, today):
    """Return (current, best) streaks counted over scheduled days only."""
    if not days:
        return 0, 0
    # current: walk back from today; an unfinished today doesn't break it
    cur, d = 0, today
    if scheduled(days, d) and d.isoformat() not in done:
        d -= timedelta(days=1)
    earliest = min((date.fromisoformat(x) for x in done), default=today)
    while d >= earliest:
        if scheduled(days, d):
            if d.isoformat() in done:
                cur += 1
            else:
                break
        d -= timedelta(days=1)
    # best: scan forward from first check
    best = run = 0
    d = earliest
    while d <= today:
        if scheduled(days, d):
            if d.isoformat() in done:
                run += 1
                best = max(best, run)
            elif d != today:
                run = 0
        d += timedelta(days=1)
    return cur, max(best, cur)


def list_habits():
    today = date.today()
    with db() as conn:
        habits = conn.execute(
            "SELECT * FROM habits WHERE archived = 0 ORDER BY id"
        ).fetchall()
        out = []
        for h in habits:
            done = {r["day"] for r in conn.execute(
                "SELECT day FROM checks WHERE habit_id = ?", (h["id"],))}
            cur, best = streaks(h["days"], done, today)
            row = conn.execute(
                "SELECT seconds FROM activity WHERE habit_id = ? AND day = ?",
                (h["id"], today.isoformat())).fetchone()
            out.append({
                "id": h["id"], "name": h["name"], "color": h["color"],
                "days": h["days"], "created": h["created"],
                "checks": sorted(done), "streak": cur, "best": best,
                "goal_minutes": h["goal_minutes"], "auto_domain": h["auto_domain"],
                "today_seconds": row["seconds"] if row else 0,
            })
    return {"today": today.isoformat(), "habits": out}


def clean_domain(v):
    d = str(v or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d[:100]


def domain_matches(habit_domain, host):
    host = host.lower().removeprefix("www.")
    return bool(habit_domain) and (host == habit_domain or host.endswith("." + habit_domain))


def record_activity(conn, host, day, seconds):
    """Add browsing time to auto-tracked habits; tick them once the goal is met."""
    for h in conn.execute("SELECT * FROM habits WHERE auto_domain != ''").fetchall():
        if not domain_matches(h["auto_domain"], host):
            continue
        conn.execute(
            "INSERT INTO activity VALUES (?, ?, ?) ON CONFLICT(habit_id, day) "
            "DO UPDATE SET seconds = seconds + excluded.seconds", (h["id"], day, seconds))
        total = conn.execute("SELECT seconds FROM activity WHERE habit_id = ? AND day = ?",
                             (h["id"], day)).fetchone()["seconds"]
        if total >= h["goal_minutes"] * 60:
            conn.execute("INSERT OR IGNORE INTO checks VALUES (?, ?)", (h["id"], day))


def clean_days(v):
    return "".join(sorted({c for c in str(v) if c in "0123456"}))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        global _last_seen
        _last_seen = time.time()
        if self.path == "/api/habits":
            return self._json(list_habits())
        if self.path == "/api/ping":
            return self._json({"ok": True})
        name = "index.html" if self.path in ("/", "/index.html") else None
        if name is None:
            self.send_error(404)
            return
        body = (STATIC_DIR / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global _last_seen
        _last_seen = time.time()
        # reject cross-origin writes from other sites in the browser
        origin = self.headers.get("Origin")
        from_ext = bool(origin) and origin.startswith(("moz-extension://", "chrome-extension://"))
        if from_ext and self.path != "/api/activity":
            return self._json({"error": "forbidden"}, 403)
        if origin and not from_ext and origin not in (f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"):
            return self._json({"error": "forbidden"}, 403)
        try:
            data = self._body()
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        with _db_lock, db() as conn:
            if self.path == "/api/activity":
                # {"host": "keybr.com", "days": {"2026-11-11": 120, ...}}
                for day, secs in dict(data.get("days", {})).items():
                    day = date.fromisoformat(day).isoformat()
                    secs = max(0, min(int(secs), 86400))
                    if day <= date.today().isoformat() and secs:
                        record_activity(conn, str(data.get("host", "")), day, secs)
                return self._json({"ok": True})
            elif self.path == "/api/habits/create":
                name = str(data.get("name", "")).strip()[:80]
                if not name:
                    return self._json({"error": "name required"}, 400)
                conn.execute(
                    "INSERT INTO habits (name, color, days, created, goal_minutes, auto_domain) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (name, str(data.get("color", "#4f8cff"))[:9],
                     clean_days(data.get("days", "0123456")) or "0123456",
                     date.today().isoformat(), max(0, int(data.get("goal_minutes") or 0)),
                     clean_domain(data.get("auto_domain"))))
            elif self.path == "/api/habits/update":
                name = str(data.get("name", "")).strip()[:80]
                conn.execute(
                    "UPDATE habits SET name = ?, color = ?, days = ?, goal_minutes = ?, "
                    "auto_domain = ? WHERE id = ?",
                    (name, str(data.get("color"))[:9],
                     clean_days(data.get("days")) or "0123456",
                     max(0, int(data.get("goal_minutes") or 0)),
                     clean_domain(data.get("auto_domain")), int(data["id"])))
            elif self.path == "/api/habits/delete":
                conn.execute("DELETE FROM habits WHERE id = ?", (int(data["id"]),))
            elif self.path == "/api/toggle":
                hid, day = int(data["id"]), date.fromisoformat(data["day"]).isoformat()
                if day > date.today().isoformat():
                    return self._json({"error": "future date"}, 400)
                cur = conn.execute(
                    "DELETE FROM checks WHERE habit_id = ? AND day = ?", (hid, day))
                if cur.rowcount == 0:
                    conn.execute("INSERT INTO checks VALUES (?, ?)", (hid, day))
            else:
                return self._json({"error": "not found"}, 404)
        return self._json(list_habits())


def port_in_use():
    with socket.socket() as s:
        return s.connect_ex((HOST, PORT)) == 0


def open_window(url):
    """Prefer a chromeless app window; fall back to the default browser."""
    for b in ("google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"):
        if shutil.which(b):
            subprocess.Popen([b, f"--app={url}", "--window-size=1000,800"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    webbrowser.open(url)


def idle_watchdog(server):
    while True:
        time.sleep(15)
        if time.time() - _last_seen > IDLE_TIMEOUT:
            server.shutdown()
            return


def main():
    url = f"http://{HOST}:{PORT}/"
    if port_in_use():  # already running: just open another window
        open_window(url)
        return
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    if "--no-browser" not in sys.argv:
        threading.Thread(target=idle_watchdog, args=(server,), daemon=True).start()
        threading.Timer(0.3, open_window, args=(url,)).start()
    print(f"Habit Tracker running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
