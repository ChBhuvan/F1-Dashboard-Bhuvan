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

# ── 5. Season calendar + winners ─────────────────────────────────────

def fetch_calendar():
    data  = get(f"{BASE}/current.json")
    races = data["MRData"]["RaceTable"]["Races"]
    today = datetime.now(timezone.utc).date()

    # Fetch all results for completed races to get winners
    winners = {}
    try:
        res_data  = get(f"{BASE}/current/results/1.json?limit=100")
        for race in res_data["MRData"]["RaceTable"]["Races"]:
            rnd = int(race["round"])
            if race["Results"]:
                d = race["Results"][0]["Driver"]
                fn, ln = d["givenName"], d["familyName"]
                winners[rnd] = f"{fn[0]}. {ln}"
    except Exception:
        pass  # keep going without winners if API hiccups

    cal = []
    for race in races:
        race_date = datetime.strptime(race["date"], "%Y-%m-%d").date()
        rnd       = int(race["round"])
        status    = "done" if race_date < today else "upcoming"
        cal.append({
            "round":   rnd,
            "name":    race["raceName"],
            "circuit": race["Circuit"]["circuitName"],
            "country": race["Circuit"]["Location"]["country"],
            "date":    race["date"],
            "status":  status,
            "winner":  winners.get(rnd, ""),
        })
    return cal

# ── 6. r/formula1 RSS headlines ──────────────────────────────────────

# Posts containing these words are immediately discarded
SKIP_ALWAYS = [
    "megathread", "mod post", "daily discussion", "weekly",
    "rate the race", "what did you think", "hot take",
    "unpopular opinion", "rant", "meme", "karma",
    "fantasy", "f1 game", "f1 23", "f1 24", "f1 25",
    "fan art", "wallpaper", "appreciation post",
    "[serious]", "who else", "just me or",
]

# Posts containing these words are actively preferred — real F1 news signals
NEWS_SIGNALS = [
    # Teams & manufacturers
    "mclaren", "ferrari", "mercedes", "red bull", "alpine",
    "aston martin", "williams", "haas", "racing bulls", "cadillac", "audi",
    # Drivers (2026 grid)
    "norris", "piastri", "leclerc", "hamilton", "russell", "antonelli",
    "verstappen", "sainz", "alonso", "stroll", "gasly", "ocon",
    "bearman", "lawson", "hadjar", "doohan", "bortoleto",
    # Race/season keywords
    "grand prix", " gp ", "qualifying", "race result", "fastest lap",
    "pole position", "podium", "championship", "standings",
    "contract", "signed", "confirmed", "announced", "penalty",
    "investigation", "protest", "disqualified", "upgrade",
    "power unit", "engine", "fia", "regulation", "technical",
    "crash", "collision", "retirement", "dnf", "safety car",
    "virtual safety car", "red flag", "pit stop", "strategy",
    "breaking", "exclusive", "report", "sources say",
]

# These flair tags in the title (Reddit adds them as prefixes) signal real news
NEWS_FLAIRS = [
    "news", "breaking", "rumour", "technical", "race",
    "qualifying", "feature", "video", "official",
]

def score_post(title: str) -> int:
    """
    Returns a relevance score for a Reddit post title.
    Higher = more likely to be real F1 news worth showing.
    Returns -1 if the post should be skipped entirely.
    """
    t = title.lower()

    # Hard skip
    if any(kw in t for kw in SKIP_ALWAYS):
        return -1

    # Skip posts that are clearly questions from fans
    if t.strip().endswith("?") and len(t) < 80:
        return -1

    # Skip posts starting with "I " — personal stories
    if t.strip().lower().startswith("i "):
        return -1

    score = 0

    # Bonus for news-looking flair prefix e.g. "[News]" or "News |"
    if any(t.startswith(f) or f"[{f}]" in t or f"{f} |" in t
           for f in NEWS_FLAIRS):
        score += 10

    # Bonus for each news signal keyword found
    for kw in NEWS_SIGNALS:
        if kw in t:
            score += 2

    # Bonus for titles that read like headlines (contain a verb suggesting action)
    action_verbs = [
        "wins", "takes", "confirms", "signs", "extends", "joins",
        "leaves", "announces", "reveals", "claims", "secures",
        "loses", "crashes", "penalised", "penalized", "disqualified",
        "beats", "dominates", "struggles", "upgrades", "sets",
    ]
    if any(v in t for v in action_verbs):
        score += 5

    return score


def fetch_reddit_news(target: int = 4):
    """
    Fetches r/formula1 hot posts, scores each one, returns the
    top `target` most news-worthy headlines with their Reddit links.
    Falls back to new.rss if hot doesn't yield enough results.
    """
    scored = []

    for feed in ["hot", "new"]:
        url = f"https://www.reddit.com/r/formula1/{feed}.rss?limit=50"
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "BhuvanF1Dashboard/1.0"},
                timeout=15,
            )
            r.raise_for_status()
        except Exception:
            continue

        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.content)

        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            if not title:
                continue

            # Prefer the href attribute on <link>, fall back to text content
            link_el = entry.find("atom:link", ns)
            link = (
                link_el.get("href")
                if link_el is not None and link_el.get("href")
                else entry.findtext("atom:link", "", ns).strip()
            )

            s = score_post(title)
            if s >= 0:
                scored.append((s, title, link))

        # If we already have enough good candidates, no need to hit /new
        if len([x for x in scored if x[0] >= 5]) >= target * 2:
            break

    # Sort by score descending, deduplicate by title
    seen   = set()
    result = []
    for score, title, link in sorted(scored, key=lambda x: -x[0]):
        key = title.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        result.append({"headline": title, "url": link, "score": score})
        if len(result) == target:
            break

    # Last resort — if nothing scored well, just return top posts
    # that aren't hard-skipped
    if not result:
        result = [
            {"headline": t, "url": l, "score": s}
            for s, t, l in scored[:target]
        ]

    # Remove score from final output (it's just for internal ranking)
    return [{"headline": x["headline"], "url": x["url"]} for x in result]

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
