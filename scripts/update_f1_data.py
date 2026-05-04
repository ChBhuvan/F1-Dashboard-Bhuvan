"""
update_f1_data.py
─────────────────
Fetches everything the dashboard needs in one run. Writes data.json.

Sources:
  Jolpica F1 API  (https://api.jolpi.ca/ergast/f1)
    - Driver standings
    - Constructor standings
    - Last event result (GP or Sprint)
    - Next race details
    - Full season calendar + winners
    - All race results  (for Teammates + AI Insights)
    - All qualifying results (for Teammates + AI Insights)
    - Qualifying gap stat

  OpenF1 API  (https://api.openf1.org/v1)
    - Tyre stints per race  (for Strategies tab)
    - Pit stop data per race (for Strategies tab)

  Reddit JSON API
    - Top 4 filtered F1 news headlines

Output: data.json
"""

import json
import time
import requests
from datetime import datetime, timezone

# ── Constants ────────────────────────────────────────────────────────────────

JOLPICA    = "https://api.jolpi.ca/ergast/f1"
OPENF1     = "https://api.openf1.org/v1"
YEAR       = datetime.now(timezone.utc).year

JOLPICA_HEADERS = {"User-Agent": "BhuvanF1Dashboard/1.0"}
REDDIT_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (compatible; F1DashboardBot/1.0; "
                  "+https://github.com/bhuvan/f1-dashboard)"
}

# 2026 teammate pairings — update when grid changes
TEAM_PAIRINGS = [
    {"team": "McLaren",      "color": "#FF8000",
     "d1": "norris",    "d2": "piastri"},
    {"team": "Mercedes",     "color": "#27F4D2",
     "d1": "russell",   "d2": "antonelli"},
    {"team": "Ferrari",      "color": "#E8002D",
     "d1": "leclerc",   "d2": "hamilton"},
    {"team": "Red Bull",     "color": "#3671C6",
     "d1": "verstappen","d2": "lawson"},
    {"team": "Aston Martin", "color": "#229971",
     "d1": "alonso",    "d2": "stroll"},
    {"team": "Alpine",       "color": "#0093CC",
     "d1": "gasly",     "d2": "doohan"},
    {"team": "Williams",     "color": "#64C4FF",
     "d1": "sainz",     "d2": "albon"},
    {"team": "Racing Bulls", "color": "#6692FF",
     "d1": "hadjar",    "d2": "bearman"},
    {"team": "Haas",         "color": "#B6BABD",
     "d1": "ocon",      "d2": "bortoleto"},
    {"team": "Audi",         "color": "#00877C",
     "d1": "hulkenberg","d2": "schumacher"},
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_jolpica(path, retries=3):
    url = f"{JOLPICA}{path}"
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=JOLPICA_HEADERS, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise e

def get_openf1(path, retries=3):
    url = f"{OPENF1}{path}"
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise e

def safe(fn, fallback=None):
    try:
        return fn()
    except Exception as e:
        print(f"  ⚠️  {fn.__name__} failed: {e}")
        return fallback

def avg(lst):
    return round(sum(lst) / len(lst), 2) if lst else 0

def std_dev(lst):
    if len(lst) < 2:
        return 0
    m = avg(lst)
    return round((sum((x - m) ** 2 for x in lst) / len(lst)) ** 0.5, 2)


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD TAB
# ════════════════════════════════════════════════════════════════════════════

def fetch_driver_standings():
    print("  Fetching driver standings…")
    data = get_jolpica("/current/driverStandings.json")
    rows = data["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
    return [
        {
            "pos":  int(s["position"]),
            "code": s["Driver"].get("code", s["Driver"]["familyName"][:3].upper()),
            "name": f"{s['Driver']['givenName'][0]}. {s['Driver']['familyName']}",
            "full_name": f"{s['Driver']['givenName']} {s['Driver']['familyName']}",
            "driver_id": s["Driver"]["driverId"],
            "team": s["Constructors"][0]["name"],
            "pts":  int(float(s["points"])),
            "wins": int(s["wins"]),
            "nat":  s["Driver"].get("nationality", ""),
        }
        for s in rows[:20]  # all drivers not just top 10
    ]


def fetch_constructor_standings():
    print("  Fetching constructor standings…")
    data = get_jolpica("/current/constructorStandings.json")
    rows = data["MRData"]["StandingsTable"]["StandingsLists"][0]["ConstructorStandings"]
    leader_pts = float(rows[0]["points"]) if rows else 1

    # Power unit map — Jolpica doesn't provide this
    PU_MAP = {
        "McLaren":      "Mercedes PU",
        "Mercedes":     "Mercedes PU",
        "Ferrari":      "Ferrari PU",
        "Red Bull":     "Ford PU",
        "Aston Martin": "Mercedes PU",
        "Alpine":       "Renault PU",
        "Williams":     "Mercedes PU",
        "Racing Bulls": "Honda PU",
        "Haas":         "Ferrari PU",
        "Cadillac":     "Ferrari PU",
        "Audi":         "Audi PU",
        "Sauber":       "Audi PU",
    }

    return [
        {
            "pos":      int(s["position"]),
            "name":     s["Constructor"]["name"],
            "pts":      int(float(s["points"])),
            "wins":     int(s["wins"]),
            "bar_pct":  round(float(s["points"]) / leader_pts * 100, 1),
            "nat":      s["Constructor"].get("nationality", ""),
            "pu":       PU_MAP.get(s["Constructor"]["name"], "—"),
        }
        for s in rows
    ]


def fetch_last_event():
    """Returns the most recent completed event — GP or Sprint."""
    print("  Fetching last event…")

    def parse_event(race, results_key="Results", event_type="Race"):
        results = race.get(results_key, [])
        podium = []
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
        date = race.get("date", "")
        return {
            "name":        race["raceName"] + (" · Sprint" if event_type == "Sprint" else ""),
            "circuit":     race["Circuit"]["circuitName"],
            "round":       int(race["round"]),
            "date":        date,
            "event_type":  event_type,
            "podium":      podium,
            "fastest_lap": {"driver": fl_driver, "time": fl_time},
        }

    gp_data  = get_jolpica("/current/last/results.json")
    gp_races = gp_data["MRData"]["RaceTable"]["Races"]
    gp = parse_event(gp_races[0]) if gp_races else None

    sprint = None
    try:
        sp_data  = get_jolpica("/current/last/sprint.json")
        sp_races = sp_data["MRData"]["RaceTable"]["Races"]
        if sp_races and sp_races[0].get("SprintResults"):
            sprint = parse_event(sp_races[0], "SprintResults", "Sprint")
    except Exception:
        pass

    if sprint and gp:
        today = datetime.now(timezone.utc).date()
        gp_date     = datetime.strptime(gp["date"][:10], "%Y-%m-%d").date()
        sprint_date = datetime.strptime(sprint["date"][:10], "%Y-%m-%d").date()
        if sprint_date > gp_date and sprint_date <= today:
            return sprint
    return gp or {}


def fetch_next_race():
    print("  Fetching next race…")
    data  = get_jolpica("/current/next.json")
    races = data["MRData"]["RaceTable"]["Races"]
    if not races:
        return {}
    race      = races[0]
    race_time = race.get("time", "14:00:00Z").replace("Z", "+00:00")
    return {
        "name":     race["raceName"],
        "circuit":  race["Circuit"]["circuitName"],
        "location": race["Circuit"]["Location"]["locality"],
        "country":  race["Circuit"]["Location"]["country"],
        "round":    int(race["round"]),
        "date":     race["date"],
        "datetime": f"{race['date']}T{race_time}",
    }


def fetch_calendar():
    print("  Fetching calendar…")
    data  = get_jolpica("/current.json")
    races = data["MRData"]["RaceTable"]["Races"]
    today = datetime.now(timezone.utc).date()

    # Fetch winners for all completed races
    winners = {}
    try:
        res = get_jolpica("/current/results/1.json?limit=100")
        for race in res["MRData"]["RaceTable"]["Races"]:
            rnd = int(race["round"])
            if race["Results"]:
                d = race["Results"][0]["Driver"]
                winners[rnd] = f"{d['givenName'][0]}. {d['familyName']}"
    except Exception:
        pass

    cal = []
    for race in races:
        race_date = datetime.strptime(race["date"], "%Y-%m-%d").date()
        rnd       = int(race["round"])
        cal.append({
            "round":   rnd,
            "name":    race["raceName"],
            "circuit": race["Circuit"]["circuitName"],
            "country": race["Circuit"]["Location"]["country"],
            "date":    race["date"],
            "status":  "done" if race_date < today else "upcoming",
            "winner":  winners.get(rnd, ""),
        })
    return cal


def fetch_quali_gap():
    print("  Fetching qualifying gap…")
    data  = get_jolpica("/current/last/qualifying.json")
    races = data["MRData"]["RaceTable"]["Races"]
    if not races:
        return {}
    race    = races[0]
    results = race.get("QualifyingResults", [])
    if len(results) < 2:
        return {}

    def best_time(r):
        return r.get("Q3") or r.get("Q2") or r.get("Q1") or ""

    def parse_ms(t):
        if not t:
            return None
        try:
            if ":" in t:
                mins, rest = t.split(":")
                return int(mins) * 60000 + round(float(rest) * 1000)
            return round(float(t) * 1000)
        except Exception:
            return None

    p1, p2 = results[0], results[1]
    t1, t2 = parse_ms(best_time(p1)), parse_ms(best_time(p2))
    if t1 is None or t2 is None:
        return {}

    gap_sec = (t2 - t1) / 1000.0
    return {
        "gap":         f"+{gap_sec:.3f}s",
        "pole_driver": f"{p1['Driver']['givenName'][0]}. {p1['Driver']['familyName']}",
        "pole_code":   p1["Driver"].get("code", "—"),
        "p2_driver":   f"{p2['Driver']['givenName'][0]}. {p2['Driver']['familyName']}",
        "race_name":   race["raceName"].replace(" Grand Prix", " GP"),
    }


# ════════════════════════════════════════════════════════════════════════════
# STRATEGIES TAB — OpenF1 stints + pit stops per race
# ════════════════════════════════════════════════════════════════════════════

def fetch_all_race_sessions():
    """Get all completed race session keys for the current year."""
    print("  Fetching OpenF1 race sessions…")
    sessions = get_openf1(f"/sessions?year={YEAR}&session_name=Race")
    today    = datetime.now(timezone.utc)
    return [
        s for s in sessions
        if s.get("session_key") and
        datetime.fromisoformat(
            s["date_start"].replace("Z", "+00:00")
        ) < today
    ]


def fetch_strategies(sessions):
    """
    For each completed race session, fetch tyre stints and pit stops.
    Also fetches driver info once per session for name/code mapping.
    """
    print(f"  Fetching strategy data for {len(sessions)} sessions…")
    strategies = []

    for session in sessions:
        key          = session["session_key"]
        meeting_name = session.get("meeting_name", f"Round {session.get('meeting_key','?')}")
        print(f"    → {meeting_name} (session {key})")

        try:
            # Fetch drivers, stints, pits in parallel using separate calls
            drivers_raw = get_openf1(f"/drivers?session_key={key}")
            stints_raw  = get_openf1(f"/stints?session_key={key}")
            pits_raw    = get_openf1(f"/pit?session_key={key}")

            # Build driver map: number → {name, code, team}
            driver_map = {}
            for d in drivers_raw:
                driver_map[d["driver_number"]] = {
                    "name": d.get("last_name", f"#{d['driver_number']}"),
                    "code": d.get("name_acronym", "???"),
                    "team": d.get("team_name", ""),
                    "team_colour": d.get("team_colour", "888888"),
                }

            # Build stints per driver
            stints_by_driver = {}
            for s in stints_raw:
                dn = s["driver_number"]
                if dn not in stints_by_driver:
                    stints_by_driver[dn] = []
                stints_by_driver[dn].append({
                    "stint":    s.get("stint_number", 1),
                    "compound": (s.get("compound") or "UNKNOWN").upper(),
                    "lap_start": s.get("lap_start", 1),
                    "lap_end":   s.get("lap_end", 0),
                    "fresh":     s.get("tyre_age_at_start", 0) == 0,
                })
            # Sort each driver's stints by stint number
            for dn in stints_by_driver:
                stints_by_driver[dn].sort(key=lambda x: x["stint"])

            # Build pit stops per driver
            pits_by_driver = {}
            for p in pits_raw:
                dn = p["driver_number"]
                if dn not in pits_by_driver:
                    pits_by_driver[dn] = []
                dur = p.get("pit_duration")
                if dur and dur > 0:
                    pits_by_driver[dn].append({
                        "lap":      p.get("lap_number", 0),
                        "duration": round(dur, 3),
                    })

            # Find fastest pit stop overall
            all_stops = [
                {"driver": dn, "lap": stop["lap"], "duration": stop["duration"],
                 "code": driver_map.get(dn, {}).get("code", f"#{dn}")}
                for dn, stops in pits_by_driver.items()
                for stop in stops
            ]
            fastest_stop = None
            if all_stops:
                fastest_stop = min(all_stops, key=lambda x: x["duration"])

            # Total laps in race
            max_lap = max(
                (s["lap_end"] for stints in stints_by_driver.values()
                 for s in stints if s["lap_end"]),
                default=0
            )

            # Assemble per-driver strategy
            drivers_strategy = []
            for dn, stints in stints_by_driver.items():
                d = driver_map.get(dn, {"name": f"#{dn}", "code": f"#{dn}", "team": ""})
                drivers_strategy.append({
                    "driver_number": dn,
                    "code":   d["code"],
                    "name":   d["name"],
                    "team":   d["team"],
                    "stints": stints,
                    "pits":   pits_by_driver.get(dn, []),
                })

            # Sort by driver code for consistent display
            drivers_strategy.sort(key=lambda x: x["code"])

            strategies.append({
                "session_key":  key,
                "meeting_key":  session.get("meeting_key"),
                "name":         meeting_name,
                "date":         session.get("date_start", "")[:10],
                "total_laps":   max_lap,
                "fastest_stop": fastest_stop,
                "drivers":      drivers_strategy,
            })

            # Be polite to the API
            time.sleep(0.5)

        except Exception as e:
            print(f"    ⚠️  Failed for {meeting_name}: {e}")
            continue

    return strategies


# ════════════════════════════════════════════════════════════════════════════
# TEAMMATES + AI INSIGHTS — detailed per-driver stats from Jolpica
# ════════════════════════════════════════════════════════════════════════════

MECH_DNF_KEYWORDS = [
    "engine", "gearbox", "hydraulics", "brakes", "electrical",
    "power unit", "oil", "water", "mechanical", "turbo", "exhaust",
    "suspension", "driveshaft", "clutch", "fuel",
]

def fetch_detailed_driver_stats():
    """
    Fetches all race results + qualifying for the current season.
    Computes per-driver stats needed by both Teammates and AI Insights tabs.
    """
    print("  Fetching all race results…")
    results_data = get_jolpica("/current/results.json?limit=1000")
    all_races    = results_data["MRData"]["RaceTable"]["Races"]

    print("  Fetching all qualifying results…")
    quali_data = get_jolpica("/current/qualifying.json?limit=1000")
    all_quali  = quali_data["MRData"]["RaceTable"]["Races"]

    # Per-driver accumulator
    drivers = {}

    def ensure(driver_id, given, family, code):
        if driver_id not in drivers:
            drivers[driver_id] = {
                "driver_id":    driver_id,
                "name":         f"{given[0]}. {family}",
                "full_name":    f"{given} {family}",
                "code":         code,
                "points":       0,
                "wins":         0,
                "podiums":      0,
                "poles":        0,
                "fastest_laps": 0,
                "dnf_mech":     0,
                "dnf_driver":   0,
                "p10_finishes": 0,
                "finish_positions":  [],
                "grid_positions":    [],
                "quali_positions":   [],
                "race_by_race":      [],  # [{round, grid, finish, points, status}]
            }
        return drivers[driver_id]

    # Process race results
    for race in all_races:
        rnd       = int(race["round"])
        race_name = race["raceName"].replace(" Grand Prix", " GP")
        for r in race.get("Results", []):
            d       = r["Driver"]
            did     = d["driverId"]
            driver  = ensure(did, d["givenName"], d["familyName"],
                             d.get("code", d["familyName"][:3].upper()))
            pos     = int(r["position"])
            grid    = int(r.get("grid", 0))
            pts     = float(r.get("points", 0))
            status  = r.get("status", "Finished")

            driver["finish_positions"].append(pos)
            if grid > 0:
                driver["grid_positions"].append(grid)

            if pos == 1:
                driver["wins"] += 1
            if pos <= 3:
                driver["podiums"] += 1
            if pos <= 10:
                driver["p10_finishes"] += 1
            if r.get("FastestLap", {}).get("rank") == "1":
                driver["fastest_laps"] += 1

            # DNF classification
            if status != "Finished" and not status.startswith("+"):
                if any(kw in status.lower() for kw in MECH_DNF_KEYWORDS):
                    driver["dnf_mech"] += 1
                else:
                    driver["dnf_driver"] += 1

            driver["race_by_race"].append({
                "round":  rnd,
                "name":   race_name,
                "grid":   grid,
                "finish": pos,
                "points": pts,
                "status": status,
            })

    # Process qualifying
    for race in all_quali:
        rnd = int(race["round"])
        for r in race.get("QualifyingResults", []):
            d    = r["Driver"]
            did  = d["driverId"]
            driver = ensure(did, d["givenName"], d["familyName"],
                            d.get("code", d["familyName"][:3].upper()))
            pos = int(r["position"])
            driver["quali_positions"].append(pos)
            if pos == 1:
                driver["poles"] += 1

    # Compute aggregate stats
    for did, d in drivers.items():
        fp = d["finish_positions"]
        gp = d["grid_positions"]
        qp = d["quali_positions"]

        d["races_started"]    = len(fp)
        d["avg_finish"]       = avg(fp)
        d["avg_grid"]         = avg(gp)
        d["avg_quali"]        = avg(qp)
        d["finish_std_dev"]   = std_dev(fp)
        d["consistency_score"]= round(max(0, 100 - d["finish_std_dev"] * 8), 1)

        # Quali vs race delta — positive means finishes better than qualifies
        if gp and fp:
            d["quali_race_delta"] = round(avg(gp) - avg(fp), 2)
        else:
            d["quali_race_delta"] = 0

        # Estimated robbed points (mechanical DNFs × 12pt average loss)
        d["robbed_points"] = d["dnf_mech"] * 12

        # Podium rate %
        d["podium_rate"] = round(
            (d["podiums"] / d["races_started"] * 100) if d["races_started"] > 0 else 0,
            1
        )

    return list(drivers.values())


def build_teammates(driver_stats, standings):
    """
    Cross-references team pairings with detailed driver stats.
    Returns a list of team comparison objects ready for the dashboard.
    """
    print("  Building teammate comparisons…")

    # Map driver_id → stats
    stats_map = {d["driver_id"]: d for d in driver_stats}

    # Map driver_id → current championship points from live standings
    pts_map = {s["driver_id"]: s["pts"] for s in standings}

    teams = []
    for pairing in TEAM_PAIRINGS:
        # Find driver IDs by partial match
        def find_driver(partial):
            for did in stats_map:
                if partial.lower() in did.lower():
                    return did
            # also try against standings
            for s in standings:
                if partial.lower() in s["driver_id"].lower():
                    return s["driver_id"]
            return None

        d1id = find_driver(pairing["d1"])
        d2id = find_driver(pairing["d2"])

        if not d1id or not d2id:
            print(f"    ⚠️  Could not match drivers for {pairing['team']}")
            continue

        s1 = stats_map.get(d1id, {})
        s2 = stats_map.get(d2id, {})

        teams.append({
            "team":  pairing["team"],
            "color": pairing["color"],
            "d1": {
                "id":            d1id,
                "name":          s1.get("full_name", d1id),
                "code":          s1.get("code", "—"),
                "points":        pts_map.get(d1id, s1.get("points", 0)),
                "wins":          s1.get("wins", 0),
                "podiums":       s1.get("podiums", 0),
                "poles":         s1.get("poles", 0),
                "fastest_laps":  s1.get("fastest_laps", 0),
                "dnfs":          s1.get("dnf_mech", 0) + s1.get("dnf_driver", 0),
                "dnf_mech":      s1.get("dnf_mech", 0),
                "p10_finishes":  s1.get("p10_finishes", 0),
                "avg_finish":    s1.get("avg_finish", 0),
                "consistency":   s1.get("consistency_score", 0),
            },
            "d2": {
                "id":            d2id,
                "name":          s2.get("full_name", d2id),
                "code":          s2.get("code", "—"),
                "points":        pts_map.get(d2id, s2.get("points", 0)),
                "wins":          s2.get("wins", 0),
                "podiums":       s2.get("podiums", 0),
                "poles":         s2.get("poles", 0),
                "fastest_laps":  s2.get("fastest_laps", 0),
                "dnfs":          s2.get("dnf_mech", 0) + s2.get("dnf_driver", 0),
                "dnf_mech":      s2.get("dnf_mech", 0),
                "p10_finishes":  s2.get("p10_finishes", 0),
                "avg_finish":    s2.get("avg_finish", 0),
                "consistency":   s2.get("consistency_score", 0),
            },
        })

    return teams


def build_ai_insights(driver_stats, standings, total_races, total_rounds):
    """
    Computes all 6 AI insight metrics from pre-fetched driver stats.
    Returns a structured object ready to be JSON-serialised.
    """
    print("  Computing AI insights…")

    total_remaining = total_rounds - total_races

    # ── 1. Championship Probability (Monte Carlo) ─────────────────────────
    POINTS_SYSTEM = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
    SIM_RUNS      = 5000

    top8 = sorted(standings[:8], key=lambda x: -x["pts"])
    sim_wins = {d["driver_id"]: 0 for d in top8}
    import random

    for _ in range(SIM_RUNS):
        sim_pts = {d["driver_id"]: d["pts"] for d in top8}
        for _ in range(total_remaining):
            shuffled = top8[:]
            random.shuffle(shuffled)
            for pos, driver in enumerate(shuffled):
                sim_pts[driver["driver_id"]] += POINTS_SYSTEM[pos] if pos < 10 else 0
        winner = max(sim_pts, key=lambda k: sim_pts[k])
        sim_wins[winner] += 1

    champ_prob = sorted([
        {
            "driver_id": did,
            "name":  next((d["name"] for d in standings if d["driver_id"] == did), did),
            "prob":  round(wins / SIM_RUNS * 100, 1),
        }
        for did, wins in sim_wins.items()
    ], key=lambda x: -x["prob"])

    # ── 2. Luck Index ─────────────────────────────────────────────────────
    luck_index = sorted([
        {
            "driver_id":    d["driver_id"],
            "name":         d["name"],
            "dnf_mech":     d["dnf_mech"],
            "dnf_driver":   d["dnf_driver"],
            "robbed_pts":   d["robbed_points"],
            "luck_score":   d["dnf_driver"] * 6 - d["robbed_points"],
        }
        for d in driver_stats
        if d["races_started"] > 0
    ], key=lambda x: -x["luck_score"])[:10]

    # ── 3. Pace Consistency ───────────────────────────────────────────────
    pace_consistency = sorted([
        {
            "driver_id":  d["driver_id"],
            "name":       d["name"],
            "score":      d["consistency_score"],
            "std_dev":    d["finish_std_dev"],
            "avg_finish": d["avg_finish"],
        }
        for d in driver_stats
        if d["races_started"] >= 2
    ], key=lambda x: -x["score"])[:10]

    # ── 4. Quali vs Race Delta ────────────────────────────────────────────
    quali_race_delta = sorted([
        {
            "driver_id": d["driver_id"],
            "name":      d["name"],
            "delta":     d["quali_race_delta"],
            "avg_quali": d["avg_quali"],
            "avg_finish":d["avg_finish"],
        }
        for d in driver_stats
        if d["races_started"] >= 2 and d["avg_quali"] > 0
    ], key=lambda x: -x["delta"])[:10]

    # ── 5. Robbed Points ─────────────────────────────────────────────────
    robbed_points = sorted([
        {
            "driver_id":  d["driver_id"],
            "name":       d["name"],
            "dnf_mech":   d["dnf_mech"],
            "robbed_pts": d["robbed_points"],
        }
        for d in driver_stats
        if d["robbed_points"] > 0
    ], key=lambda x: -x["robbed_pts"])

    # ── 6. Podium Performer ───────────────────────────────────────────────
    podium_performer = sorted([
        {
            "driver_id":   d["driver_id"],
            "name":        d["name"],
            "podium_rate": d["podium_rate"],
            "podiums":     d["podiums"],
            "avg_finish":  d["avg_finish"],
        }
        for d in driver_stats
        if d["races_started"] >= 2
    ], key=lambda x: -x["podium_rate"])[:10]

    return {
        "sim_runs":          SIM_RUNS,
        "total_remaining":   total_remaining,
        "champ_probability": champ_prob,
        "luck_index":        luck_index,
        "pace_consistency":  pace_consistency,
        "quali_race_delta":  quali_race_delta,
        "robbed_points":     robbed_points,
        "podium_performer":  podium_performer,
    }


# ════════════════════════════════════════════════════════════════════════════
# REDDIT NEWS
# ════════════════════════════════════════════════════════════════════════════

SKIP_ALWAYS = [
    "megathread", "mod post", "daily discussion", "weekly",
    "rate the race", "hot take", "unpopular opinion", "rant",
    "meme", "fantasy", "f1 game", "fan art", "wallpaper",
    "appreciation post", "who else", "just me or",
]

NEWS_SIGNALS = [
    "mclaren", "ferrari", "mercedes", "red bull", "alpine",
    "aston martin", "williams", "haas", "racing bulls", "cadillac", "audi",
    "norris", "piastri", "leclerc", "hamilton", "russell", "antonelli",
    "verstappen", "sainz", "alonso", "stroll", "gasly", "ocon",
    "bearman", "lawson", "hadjar", "doohan", "bortoleto",
    "grand prix", " gp ", "qualifying", "race result", "fastest lap",
    "pole position", "podium", "championship", "standings",
    "contract", "signed", "confirmed", "announced", "penalty",
    "investigation", "disqualified", "upgrade", "fia", "regulation",
    "crash", "collision", "retirement", "safety car", "red flag",
    "breaking", "exclusive", "report", "sources say",
]

ACTION_VERBS = [
    "wins", "takes", "confirms", "signs", "extends", "joins", "leaves",
    "announces", "reveals", "claims", "secures", "loses", "crashes",
    "penalised", "penalized", "disqualified", "beats", "dominates",
    "upgrades", "sets", "breaks",
]

def score_post(title):
    t = title.lower()
    if any(kw in t for kw in SKIP_ALWAYS):
        return -1
    if t.strip().endswith("?") and len(t) < 80:
        return -1
    if t.strip().startswith("i "):
        return -1
    score = 0
    for kw in NEWS_SIGNALS:
        if kw in t:
            score += 2
    if any(v in t for v in ACTION_VERBS):
        score += 5
    if any(f"[{f}]" in t or f"{f} |" in t
           for f in ["news", "breaking", "rumour", "official"]):
        score += 10
    return score


def fetch_reddit_news(target=4):
    print("  Fetching Reddit news…")
    scored = []
    for feed in ["hot", "new"]:
        url = f"https://www.reddit.com/r/formula1/{feed}.json?limit=50&raw_json=1"
        try:
            r = requests.get(url, headers=REDDIT_HEADERS, timeout=20)
            r.raise_for_status()
            posts = r.json().get("data", {}).get("children", [])
        except Exception as e:
            print(f"    ⚠️  Reddit {feed} failed: {e}")
            continue

        for post in posts:
            p = post.get("data", {})
            if p.get("stickied") or p.get("distinguished") == "moderator":
                continue
            title = p.get("title", "").strip()
            link  = "https://www.reddit.com" + p.get("permalink", "")
            s = score_post(title)
            if s >= 0:
                scored.append((s, title, link))

        if len([x for x in scored if x[0] >= 5]) >= target * 2:
            break

    seen, result = set(), []
    for score, title, link in sorted(scored, key=lambda x: -x[0]):
        key = title.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        result.append({"headline": title, "url": link})
        if len(result) == target:
            break

    return result or [{"headline": t, "url": l} for _, t, l in scored[:target]]


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print(f"F1 Dashboard Update — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    print("\n[1/7] Dashboard data…")
    drivers      = safe(fetch_driver_standings, [])
    constructors = safe(fetch_constructor_standings, [])
    last_event   = safe(fetch_last_event, {})
    next_race    = safe(fetch_next_race, {})
    calendar     = safe(fetch_calendar, [])
    quali_gap    = safe(fetch_quali_gap, {})

    print("\n[2/7] Detailed driver stats (Teammates + AI)…")
    driver_stats = safe(fetch_detailed_driver_stats, [])

    total_races  = len([r for r in calendar if r.get("status") == "done"])
    total_rounds = len(calendar) or 23

    print("\n[3/7] Building teammate comparisons…")
    teammates = safe(lambda: build_teammates(driver_stats, drivers), [])

    print("\n[4/7] Computing AI insights…")
    ai_insights = safe(
        lambda: build_ai_insights(driver_stats, drivers, total_races, total_rounds),
        {}
    )

    print("\n[5/7] Strategy data from OpenF1…")
    sessions   = safe(fetch_all_race_sessions, [])
    strategies = safe(lambda: fetch_strategies(sessions), [])

    print("\n[6/7] Reddit news…")
    news = safe(fetch_reddit_news, [])

    print("\n[7/7] Assembling data.json…")
    payload = {
        "updated_at":    datetime.now(timezone.utc).isoformat(),
        "season":        YEAR,
        # ── Dashboard tab ──────────────────────────────────────────
        "drivers":       drivers,
        "constructors":  constructors,
        "last_race":     last_event,
        "next_race":     next_race,
        "calendar":      calendar,
        "news":          news,
        "stats": {
            "champ_gap":          (drivers[0]["pts"] - drivers[1]["pts"]) if len(drivers) >= 2 else 0,
            "champ_leader":       drivers[0]["name"]    if drivers else "—",
            "champ_runner_up":    drivers[1]["name"]    if len(drivers) > 1 else "—",
            "fastest_lap":        last_event.get("fastest_lap", {}).get("time", "—"),
            "fastest_lap_driver": last_event.get("fastest_lap", {}).get("driver", "—"),
            "quali_gap":          quali_gap.get("gap", "—"),
            "quali_pole":         quali_gap.get("pole_driver", "—"),
            "quali_p2":           quali_gap.get("p2_driver", "—"),
            "quali_race":         quali_gap.get("race_name", "—"),
        },
        # ── Strategies tab ─────────────────────────────────────────
        "strategies":    strategies,
        # ── Teammates tab ──────────────────────────────────────────
        "teammates":     teammates,
        # ── AI Insights tab ────────────────────────────────────────
        "ai_insights":   ai_insights,
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2)

    size_kb = len(json.dumps(payload)) / 1024
    print(f"\n{'=' * 60}")
    print(f"✅ data.json written")
    print(f"   Drivers:     {len(drivers)}")
    print(f"   Teams:       {len(constructors)}")
    print(f"   Races done:  {total_races} / {total_rounds}")
    print(f"   Strategies:  {len(strategies)} sessions")
    print(f"   Teammates:   {len(teammates)} team cards")
    print(f"   News items:  {len(news)}")
    print(f"   AI metrics:  {len(ai_insights)} sections")
    print(f"   File size:   {size_kb:.1f} KB")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
