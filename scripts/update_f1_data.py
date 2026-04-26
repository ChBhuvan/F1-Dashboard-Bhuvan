"""
update_f1_data.py
─────────────────
Fetches from:
  • Jolpica F1 API  — driver standings, constructor standings,
                      last race result, next race details
  • r/formula1 RSS  — top 4 recent headlines with links

Writes:  data.json  (consumed by the dashboard on page load)
"""

import json, requests, xml.etree.ElementTree as ET
from datetime import datetime, timezone

BASE    = "https://api.jolpi.ca/ergast/f1"
HEADERS = {"User-Agent": "BhuvanF1Dashboard/1.0"}

# ── helpers ─────────────────────────────────────────────────────────

def get(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def safe(fn, fallback=None):
    try:    return fn()
    except: return fallback

# ── 1. Driver standings (top 10) ────────────────────────────────────

def fetch_drivers():
    data = get(f"{BASE}/current/driverStandings.json")
    standings = data["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
    return [
        {
            "pos":    int(s["position"]),
            "code":   s["Driver"].get("code", s["Driver"]["familyName"][:3].upper()),
            "name":   f"{s['Driver']['givenName'][0]}. {s['Driver']['familyName']}",
            "team":   s["Constructors"][0]["name"],
            "pts":    int(float(s["points"])),
            "nat":    s["Driver"].get("nationality", ""),
        }
        for s in standings[:10]
    ]

# ── 2. Constructor standings (all teams) ────────────────────────────

def fetch_constructors():
    data = get(f"{BASE}/current/constructorStandings.json")
    standings = data["MRData"]["StandingsTable"]["StandingsLists"][0]["ConstructorStandings"]
    leader_pts = float(standings[0]["points"]) if standings else 1
    return [
        {
            "pos":       int(s["position"]),
            "name":      s["Constructor"]["name"],
            "pts":       int(float(s["points"])),
            "bar_pct":   round(float(s["points"]) / leader_pts * 100, 1),
            "nat":       s["Constructor"].get("nationality", ""),
        }
        for s in standings
    ]

# ── 3. Last race result (podium + fastest lap) ───────────────────────

def fetch_last_race():
    data = get(f"{BASE}/current/last/results.json")
    race  = data["MRData"]["RaceTable"]["Races"][0]
    results = race["Results"]

    podium = []
    for r in results[:3]:
        podium.append({
            "pos":    int(r["position"]),
            "name":   f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
            "team":   r["Constructor"]["name"],
            "time":   r.get("Time", {}).get("time", r.get("status", "—")),
        })

    # fastest lap
    fl_driver, fl_time = "—", "—"
    for r in results:
        if r.get("FastestLap", {}).get("rank") == "1":
            fl_driver = r["Driver"]["familyName"]
            fl_time   = r["FastestLap"]["Time"]["time"]
            break

    return {
        "name":        race["raceName"],
        "circuit":     race["Circuit"]["circuitName"],
        "round":       int(race["round"]),
        "date":        race["date"],
        "podium":      podium,
        "fastest_lap": {"driver": fl_driver, "time": fl_time},
    }

# ── 4. Next race details + countdown target ──────────────────────────

def fetch_next_race():
    data = get(f"{BASE}/current/next.json")
    races = data["MRData"]["RaceTable"]["Races"]
    if not races:
        return {}
    race = races[0]
    # Build ISO datetime for the countdown
    race_time = race.get("time", "14:00:00Z").replace("Z", "+00:00")
    race_dt   = f"{race['date']}T{race_time}"
    return {
        "name":      race["raceName"],
        "circuit":   race["Circuit"]["circuitName"],
        "location":  race["Circuit"]["Location"]["locality"],
        "country":   race["Circuit"]["Location"]["country"],
        "round":     int(race["round"]),
        "date":      race["date"],
        "datetime":  race_dt,
        "flag":      race["Circuit"]["Location"]["country"],
    }

# ── 5. Season calendar ───────────────────────────────────────────────

def fetch_calendar():
    data = get(f"{BASE}/current.json")
    races = data["MRData"]["RaceTable"]["Races"]
    today = datetime.now(timezone.utc).date()
    cal = []
    for race in races:
        race_date = datetime.strptime(race["date"], "%Y-%m-%d").date()
        status = "done" if race_date < today else "upcoming"
        cal.append({
            "round":    int(race["round"]),
            "name":     race["raceName"],
            "circuit":  race["Circuit"]["circuitName"],
            "country":  race["Circuit"]["Location"]["country"],
            "date":     race["date"],
            "status":   status,
        })
    return cal

# ── 6. r/formula1 RSS headlines ──────────────────────────────────────

def fetch_reddit_news():
    RSS_URL = "https://www.reddit.com/r/formula1/hot.rss?limit=20"
    r = requests.get(RSS_URL, headers={"User-Agent": "BhuvanF1Dashboard/1.0"}, timeout=15)
    r.raise_for_status()

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(r.content)
    entries = root.findall("atom:entry", ns)

    news = []
    for entry in entries:
        title = entry.findtext("atom:title", "", ns).strip()
        link  = entry.findtext("atom:link", "", ns).strip()
        # atom:link can also be an element with href attribute
        link_el = entry.find("atom:link", ns)
        if link_el is not None and link_el.get("href"):
            link = link_el.get("href")

        # Skip stickied/mod posts and mega-threads
        skip_keywords = ["megathread", "mod post", "daily discussion", "weekly"]
        if any(kw in title.lower() for kw in skip_keywords):
            continue

        # Prefer news-looking titles (contains GP names, team names, driver names, etc.)
        news.append({"headline": title, "url": link})
        if len(news) == 4:
            break

    return news

# ── 7. Championship gap stat ─────────────────────────────────────────

def champ_gap(drivers):
    if len(drivers) >= 2:
        return drivers[0]["pts"] - drivers[1]["pts"]
    return 0

# ── Assemble and write ───────────────────────────────────────────────

def main():
    print("Fetching driver standings …")
    drivers = safe(fetch_drivers, [])

    print("Fetching constructor standings …")
    constructors = safe(fetch_constructors, [])

    print("Fetching last race …")
    last_race = safe(fetch_last_race, {})

    print("Fetching next race …")
    next_race = safe(fetch_next_race, {})

    print("Fetching calendar …")
    calendar = safe(fetch_calendar, [])

    print("Fetching r/formula1 news …")
    news = safe(fetch_reddit_news, [])

    payload = {
        "updated_at":    datetime.now(timezone.utc).isoformat(),
        "drivers":       drivers,
        "constructors":  constructors,
        "last_race":     last_race,
        "next_race":     next_race,
        "calendar":      calendar,
        "news":          news,
        "stats": {
            "champ_gap":       champ_gap(drivers),
            "champ_leader":    drivers[0]["name"]    if drivers else "—",
            "champ_runner_up": drivers[1]["name"]    if len(drivers) > 1 else "—",
            "fastest_lap":     last_race.get("fastest_lap", {}).get("time", "—"),
            "fastest_lap_driver": last_race.get("fastest_lap", {}).get("driver", "—"),
        },
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2)

    print(f"✅  data.json written — {len(drivers)} drivers, "
          f"{len(constructors)} constructors, {len(news)} news items.")

if __name__ == "__main__":
    main()
