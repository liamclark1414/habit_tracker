"""Strava integration: OAuth, activity sync, and auto-completing habits."""
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

API = "https://www.strava.com"
BACKFILL_DAYS = 365

# habit "strava_group" -> Strava sport types that count
GROUPS = {
    "run": {"Run", "TrailRun", "VirtualRun"},
    "walk": {"Walk", "Hike"},
    "ride": {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide", "EMountainBikeRide"},
    "swim": {"Swim"},
    "any": None,  # any activity
}
UNITS = {"km": "km", "mi": "mi", "min": "min", "any": "activity"}
METRES_PER_MILE = 1609.344


def init(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS strava_activities (
            id INTEGER PRIMARY KEY,
            day TEXT NOT NULL,
            sport_type TEXT NOT NULL,
            distance REAL NOT NULL DEFAULT 0,      -- metres
            moving_time INTEGER NOT NULL DEFAULT 0, -- seconds
            name TEXT
        );
        CREATE INDEX IF NOT EXISTS strava_day ON strava_activities(day);
        """
    )
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(habits)")}
    for col, ddl in (("strava_group", "TEXT NOT NULL DEFAULT ''"),
                     ("strava_metric", "TEXT NOT NULL DEFAULT 'any'"),
                     ("strava_goal", "REAL NOT NULL DEFAULT 0"),
                     ("period", "TEXT NOT NULL DEFAULT 'day'")):
        if col not in cols:
            conn.execute(f"ALTER TABLE habits ADD COLUMN {col} {ddl}")


def get(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def put(conn, key, value):
    if value is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))


def _request(url, data=None, token=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def status(conn):
    return {
        "client_id": get(conn, "strava_client_id", ""),
        "has_secret": bool(get(conn, "strava_client_secret")),
        "connected": bool(get(conn, "strava_refresh_token")),
        "athlete": get(conn, "strava_athlete", ""),
        "last_sync": get(conn, "strava_last_sync", ""),
        "error": get(conn, "strava_error", ""),
        "activities": conn.execute("SELECT COUNT(*) c FROM strava_activities").fetchone()["c"],
    }


def auth_url(conn, redirect_uri):
    state = secrets.token_urlsafe(16)
    put(conn, "strava_oauth_state", state)
    return f"{API}/oauth/authorize?" + urllib.parse.urlencode({
        "state": state,
        "client_id": get(conn, "strava_client_id"),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "activity:read_all",
    })


def _save_tokens(conn, tok):
    put(conn, "strava_access_token", tok["access_token"])
    put(conn, "strava_refresh_token", tok["refresh_token"])
    put(conn, "strava_expires_at", tok["expires_at"])


def exchange_code(conn, code, state):
    expected = get(conn, "strava_oauth_state")
    put(conn, "strava_oauth_state", None)
    if not expected or not secrets.compare_digest(expected, state):
        raise ValueError("invalid OAuth state; please click Connect again")
    tok = _request(f"{API}/oauth/token", {
        "client_id": get(conn, "strava_client_id"),
        "client_secret": get(conn, "strava_client_secret"),
        "code": code,
        "grant_type": "authorization_code",
    })
    _save_tokens(conn, tok)
    a = tok.get("athlete") or {}
    put(conn, "strava_athlete", f"{a.get('firstname', '')} {a.get('lastname', '')}".strip())
    put(conn, "strava_error", None)


def disconnect(conn):
    for k in ("strava_access_token", "strava_refresh_token", "strava_expires_at",
              "strava_athlete", "strava_last_sync", "strava_error"):
        put(conn, k, None)
    conn.execute("DELETE FROM strava_activities")


def _access_token(conn):
    if float(get(conn, "strava_expires_at", 0)) > time.time() + 120:
        return get(conn, "strava_access_token")
    tok = _request(f"{API}/oauth/token", {
        "client_id": get(conn, "strava_client_id"),
        "client_secret": get(conn, "strava_client_secret"),
        "grant_type": "refresh_token",
        "refresh_token": get(conn, "strava_refresh_token"),
    })
    _save_tokens(conn, tok)
    return tok["access_token"]


def sync(db, lock):
    """Fetch new activities from Strava and tick any habits they complete."""
    with lock, db() as conn:
        if not get(conn, "strava_refresh_token"):
            return
        try:
            token = _access_token(conn)
        except (urllib.error.URLError, KeyError, ValueError) as e:
            put(conn, "strava_error", f"Token refresh failed: {e}")
            return
        newest = conn.execute("SELECT MAX(day) d FROM strava_activities").fetchone()["d"]
    # re-fetch the last few days each time to pick up edits; backfill a year on first sync
    since = (date.fromisoformat(newest) - timedelta(days=3)) if newest else date.today() - timedelta(days=BACKFILL_DAYS)
    after = int(time.mktime(since.timetuple()))
    acts, page = [], 1
    try:
        while True:
            batch = _request(f"{API}/api/v3/athlete/activities?after={after}&per_page=200&page={page}", token=token)
            acts += batch
            if len(batch) < 200 or page >= 20:
                break
            page += 1
    except (urllib.error.URLError, ValueError) as e:
        with lock, db() as conn:
            put(conn, "strava_error", f"Sync failed: {e}")
        return
    with lock, db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO strava_activities VALUES (?, ?, ?, ?, ?, ?)",
            [(a["id"], a["start_date_local"][:10], a.get("sport_type") or a.get("type", ""),
              a.get("distance", 0), a.get("moving_time", 0), a.get("name", "")) for a in acts])
        put(conn, "strava_last_sync", time.strftime("%Y-%m-%d %H:%M"))
        put(conn, "strava_error", None)
        apply(conn)


def week_start(day):
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return d - timedelta(days=d.weekday())


def _rows(conn, group, first, last):
    types = GROUPS.get(group)
    rows = conn.execute("SELECT day, sport_type, distance, moving_time FROM strava_activities "
                        "WHERE day BETWEEN ? AND ?", (first, last))
    return [r for r in rows if types is None or r["sport_type"] in types]


def _measure(rows, metric):
    if metric == "mi":
        return round(sum(r["distance"] for r in rows) / METRES_PER_MILE, 2)
    if metric == "km":
        return round(sum(r["distance"] for r in rows) / 1000, 2)
    if metric == "min":
        return round(sum(r["moving_time"] for r in rows) / 60)
    return len(rows)


def day_value(conn, group, metric, day):
    return _measure(_rows(conn, group, day, day), metric)


def week_value(conn, group, metric, day):
    ws = week_start(day)
    return _measure(_rows(conn, group, ws.isoformat(), (ws + timedelta(days=6)).isoformat()), metric)


def activity_days(conn, group):
    return sorted({r["day"] for r in _rows(conn, group, "0000", "9999")})


def meets(metric, value, goal):
    return value >= (goal if metric in ("km", "mi", "min") and goal > 0 else 1)


def apply(conn):
    """Tick every day on which a Strava-linked habit's goal was met."""
    days = [r["day"] for r in conn.execute("SELECT DISTINCT day FROM strava_activities")]
    for h in conn.execute("SELECT * FROM habits WHERE strava_group != ''").fetchall():
        if h["period"] == "week":
            # weekly habits are fully automatic: tick the day the weekly total crosses the goal
            conn.execute("DELETE FROM checks WHERE habit_id = ?", (h["id"],))
            weeks = {}
            for r in _rows(conn, h["strava_group"], "0000", "9999"):
                weeks.setdefault(week_start(r["day"]), []).append(r)
            for rows in weeks.values():
                rows.sort(key=lambda r: r["day"])
                for i, r in enumerate(rows):
                    if meets(h["strava_metric"], _measure(rows[:i + 1], h["strava_metric"]), h["strava_goal"]):
                        conn.execute("INSERT OR IGNORE INTO checks VALUES (?, ?)", (h["id"], r["day"]))
                        break
            continue
        for day in days:
            if meets(h["strava_metric"], day_value(conn, h["strava_group"], h["strava_metric"], day), h["strava_goal"]):
                conn.execute("INSERT OR IGNORE INTO checks VALUES (?, ?)", (h["id"], day))
