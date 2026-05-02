"""
update_f1_data.py
─────────────────
Fetches from:
  • Jolpica F1 API  — driver standings, constructor standings,
                      last event result (GP or Sprint, whichever is more recent),
                      next race details, qualifying gap
  • Reddit JSON API — top 4 filtered F1 news headlines with links

Writes:  data.json  (consumed by the dashboard on page load)
"""

import json, requests
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

# ── 3. Last event result (Grand Prix or Sprint, whichever is more recent) ──

def parse_race_result(race, results_key="Results", event_type="Race"):
    """Shared parser for both GP and Sprint results."""
    results = race.get(results_key, [])
    podium  = []
    for r in results[:3]:
        podium.append({
            "pos":  int(r["position"]),
            "name": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
            "team": r["Constructor"]["name"],
            "time": r.get("Time", {}).get("time", r.get("status", "—")),
        })

    fl_driver, fl_time = "—", "—"
    for r in results:
        if r.get("FastestLap", {}).get("rank") == "1":
            fl_driver = r["Driver"]["familyName"]
            fl_time   = r["FastestLap"]["Time"]["time"]
            break

    # Sprint date is stored under "Sprint" key, GP under "date"
    date = race.get("Sprint", {}).get("date") if event_type == "Sprint" else race.get("date", "")

    return {
        "name":        race["raceName"] + (" · Sprint" if event_type == "Sprint" else ""),
        "circuit":     race["Circuit"]["circuitName"],
        "round":       int(race["round"]),
        "date":        date or race.get("date", ""),
        "event_type":  event_type,
        "podium":      podium,
        "fastest_lap": {"driver": fl_driver, "time": fl_time},
    }


def fetch_last_race():
    """
    Returns the most recent completed event — either a Grand Prix or a
    Sprint race, whichever happened most recently.
    """
    # Always fetch the last GP result
    gp_data  = get(f"{BASE}/current/last/results.json")
    gp_races = gp_data["MRData"]["RaceTable"]["Races"]
    gp       = parse_race_result(gp_races[0]) if gp_races else None

    # Try to fetch the last sprint result
    sprint = None
    try:
        sp_data  = get(f"{BASE}/current/last/sprint.json")
        sp_races = sp_data["MRData"]["RaceTable"]["Races"]
        if sp_races and sp_races[0].get("SprintResults"):
            sprint = parse_race_result(sp_races[0], "SprintResults", "Sprint")
    except Exception:
        pass  # No sprint this round — that is fine

    # Return whichever event is more recent
    if sprint and gp:
        gp_date     = datetime.strptime(gp["date"][:10],     "%Y-%m-%d").date()
        sprint_date = datetime.strptime(sprint["date"][:10], "%Y-%m-%d").date()
        today       = datetime.now(timezone.utc).date()
        # Only prefer sprint if it is more recent than the GP AND already happened
        if sprint_date > gp_date and sprint_date <= today:
            return sprint

    return gp or {}

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
    Fetches r/formula1 posts using Reddit's JSON API (works from CI servers
    unlike RSS which gets blocked). Scores each post and returns the top
    `target` most news-worthy headlines with their Reddit links.
    """
    scored = []

    # Reddit JSON API — works reliably from GitHub Actions
    # Using a descriptive User-Agent avoids 429s from Reddit
    reddit_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; F1DashboardBot/1.0; +https://github.com/bhuvan/f1-dashboard)"
    }

    for feed in ["hot", "new"]:
        url = f"https://www.reddit.com/r/formula1/{feed}.json?limit=50&raw_json=1"
        try:
            r = requests.get(url, headers=reddit_headers, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  ⚠️  Reddit {feed} fetch failed: {e}")
            continue

        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p     = post.get("data", {})
            title = p.get("title", "").strip()
            # Build the full Reddit permalink
            link  = "https://www.reddit.com" + p.get("permalink", "")

            # Skip stickied mod posts
            if p.get("stickied") or p.get("distinguished") == "moderator":
                continue

            s = score_post(title)
            if s >= 0:
                scored.append((s, title, link))

        # If we already have enough good candidates, skip /new
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

    # Last resort — return top posts that aren't hard-skipped
    if not result:
        result = [
            {"headline": t, "url": l, "score": s}
            for s, t, l in scored[:target]
        ]

    # Remove score from final output
    return [{"headline": x["headline"], "url": x["url"]} for x in result]

# ── 7. Championship gap stat ─────────────────────────────────────────

def champ_gap(drivers):
    if len(drivers) >= 2:
        return drivers[0]["pts"] - drivers[1]["pts"]
    return 0

# ── 8. Qualifying gap between P1 and P2 from the last race weekend ──

def fetch_quali_gap():
    """
    Fetches the most recent qualifying result and returns the
    gap in milliseconds between pole and P2, formatted as a string.
    Returns: { gap, pole_driver, p2_driver, race_name }
    """
    try:
        data  = get(f"{BASE}/current/last/qualifying.json")
        races = data["MRData"]["RaceTable"]["Races"]
        if not races:
            return {}

        race    = races[0]
        results = race.get("QualifyingResults", [])
        if len(results) < 2:
            return {}

        race_name = race["raceName"].replace(" Grand Prix", " GP")

        p1 = results[0]
        p2 = results[1]

        # Use Q3 time if available, fall back to Q2 then Q1
        def best_time(r):
            return r.get("Q3") or r.get("Q2") or r.get("Q1") or ""

        def parse_ms(t):
            """Convert m:ss.mmm or ss.mmm to milliseconds."""
            if not t:
                return None
            try:
                if ":" in t:
                    mins, rest = t.split(":")
                    return int(mins) * 60000 + round(float(rest) * 1000)
                return round(float(t) * 1000)
            except Exception:
                return None

        t1 = parse_ms(best_time(p1))
        t2 = parse_ms(best_time(p2))

        if t1 is None or t2 is None:
            return {}

        gap_ms  = t2 - t1
        gap_sec = gap_ms / 1000.0

        # Format as +0.000s
        gap_str = f"+{gap_sec:.3f}s"

        p1_driver = p1["Driver"]
        p2_driver = p2["Driver"]

        return {
            "gap":         gap_str,
            "gap_ms":      gap_ms,
            "pole_driver": f"{p1_driver['givenName'][0]}. {p1_driver['familyName']}",
            "pole_code":   p1_driver.get("code", p1_driver["familyName"][:3].upper()),
            "p2_driver":   f"{p2_driver['givenName'][0]}. {p2_driver['familyName']}",
            "p2_code":     p2_driver.get("code", p2_driver["familyName"][:3].upper()),
            "race_name":   race_name,
        }

    except Exception as e:
        print(f"  ⚠️  Qualifying gap fetch failed: {e}")
        return {}

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

    print("Fetching qualifying gap …")
    quali_gap = safe(fetch_quali_gap, {})

    payload = {
        "updated_at":    datetime.now(timezone.utc).isoformat(),
        "drivers":       drivers,
        "constructors":  constructors,
        "last_race":     last_race,
        "next_race":     next_race,
        "calendar":      calendar,
        "news":          news,
        "stats": {
            "champ_gap":          champ_gap(drivers),
            "champ_leader":       drivers[0]["name"]  if drivers else "—",
            "champ_runner_up":    drivers[1]["name"]  if len(drivers) > 1 else "—",
            "fastest_lap":        last_race.get("fastest_lap", {}).get("time", "—"),
            "fastest_lap_driver": last_race.get("fastest_lap", {}).get("driver", "—"),
            "quali_gap":          quali_gap.get("gap", "—"),
            "quali_pole":         quali_gap.get("pole_driver", "—"),
            "quali_p2":           quali_gap.get("p2_driver", "—"),
            "quali_race":         quali_gap.get("race_name", "—"),
        },
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2)

    print(f"✅  data.json written — {len(drivers)} drivers, "
          f"{len(constructors)} constructors, {len(news)} news items, "
          f"quali gap: {payload['stats']['quali_gap']} "
          f"({payload['stats']['quali_pole']} vs {payload['stats']['quali_p2']}).")

if __name__ == "__main__":
    main()
