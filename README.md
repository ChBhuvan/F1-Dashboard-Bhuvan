# 🏁 Bhuvan's Pit Wall

> A self-updating Formula 1 2026 dashboard with a McLaren-tinted lens on the season.
> Live at **[chbhuvan.github.io/F1-Dashboard-Bhuvan](https://chbhuvan.github.io/F1-Dashboard-Bhuvan)**

A weekend project that got a little out of hand. What started as "can I track the championship in one tab?" turned into a fully-automated data pipeline that ingests live race results from multiple APIs, runs Monte Carlo simulations to project championship probabilities, classifies retirement causes, and serves it all from a static GitHub Pages site that refreshes itself after every race weekend.

Most F1 dashboards I came across try to **predict** race results. But in motorsport, weather, engine failures, pit stop fumbles, and team strategy can flip an entire race on its head, so chasing a "correct" prediction felt like the wrong problem. I went the other way: build something simple, glanceable, and grounded in what's already happened, that I'd genuinely return to every race weekend.

---

## ✨ What's on the dashboard

### 📊 Dashboard tab
The home view. Live drivers' and constructors' championships (auto-expanding to show every point-scorer), next-race countdown, the full 2026 calendar with status flags, last-race podium and fastest lap, and a featured McLaren team card with WCC points, fastest pit stop, and best result of the season.

A breaking-news widget at the bottom right pulls F1 headlines from Reddit's r/formula1 with RSS fallbacks (Google News, BBC, PlanetF1) when Reddit's bot protection kicks in. Every card is clickable.

### 🛞 Race Strategies tab
Tyre stint visualisation and pit stop breakdowns for every Grand Prix this season. Pick a race from the dropdown ("Miami GP · 2026", "Chinese GP · 2026", etc.) and see every driver's compound choices, lap windows, and box times in a horizontal bar chart layout.

### 👥 Teammates tab
Head-to-head stat cards for all 11 teams. Points, wins, podiums, poles, fastest laps, DNFs, average finishing position, and a consistency score per driver, all visualised against their teammate for instant comparison.

### 🤖 AI Insights tab
Where the analytics live. Six cards covering:
- **Championship probability** — Monte Carlo projection of each driver's title chances
- **Luck Index** — quantifies who's been robbed by reliability vs lucky despite mistakes
- **Pace consistency** — statistical scoring via finish-position standard deviation
- **Quali vs race delta** — surfaces drivers who consistently overperform on Sundays
- **Robbed points** — estimated points lost to mechanical DNFs, weighted by typical finishing position
- **Podium performer** — podium rate vs average finish

### 🟠 Papaya — the McLaren-biased AI chatbot
A chat agent powered by Claude, deployed as a Cloudflare Worker. Papaya has a defined personality (witty, sassy, McLaren-loyal) and is grounded in current season data via retrieval-augmented context injection. The frontend bundles live standings, last-race results, next-race info, and a previous-season recap into the system prompt with every request, so Papaya answers from real stats instead of stale training data.

---

## 🧠 The analytics and ML layer

### Monte Carlo championship simulation
Runs 5,000 simulated season completions to project each driver's championship probability. For every remaining race, each driver's finishing position is sampled probabilistically using a distribution weighted by their recent form (average finish position from completed races). DNFs are sampled separately from a per-driver reliability rate. Final standings are aggregated across all 5,000 runs to produce probability percentages.

The model intentionally avoids deep predictive modelling on race-by-race outcomes. F1 has too much variance (weather, regulation tweaks, mid-season car updates) for that to be honest. Instead, this gives a calibrated "given current form, here's the distribution of outcomes" view that updates as the season progresses.

### Pace consistency scoring
For each driver with ≥2 race starts, compute standard deviation of finishing positions across the season. Lower std dev = more consistent. Convert to a 0-100 score via `max(0, 100 - σ * 5)`. The multiplier of 5 (down from a more aggressive 8) was tuned to give meaningful spread with small samples — early-season F1 doesn't have enough races for tight statistical bounds.

### DNF classification
Jolpica's API returns specific mechanical causes ("Engine", "Battery", "Hydraulics") only sporadically — for 2026 it mostly returns the generic "Retired". So the classifier inverts the heuristic: any DNF status matching a driver-error keyword (accident, collision, spun off, disqualified, withdrew) is classified as `dnf_driver`. Everything else, including generic "Retired", is treated as `dnf_mech`. This matches real-world reality, drivers don't pull a healthy car off the track.

### Luck Index
Quantifies whether a driver's results were dragged down by reliability or buoyed by avoiding self-inflicted DNFs. Score formula:

```
luck_score = (dnf_mech × 8) + robbed_pts − (dnf_driver × 3)
```

Positive = robbed by the car. Negative = lucky despite own mistakes. The chart sorts by absolute magnitude so both extremes surface. When the entire field has zero mechanical DNFs (rare but happens early-season with reliable cars), the card shows a graceful "RELIABILITY: 100%" empty state instead of misleading data.

### Robbed Points estimator
Rather than assuming a flat point loss per DNF, this projects each driver's average finishing position onto F1's points table (P1=25, P2=18, P3=15, P4=12, P5=10, P6=8, P7=6, P8=4, P9=2, P10=1). A driver averaging P3 who suffers a mechanical DNF loses ~15 points; a driver averaging P15 loses 0. Total robbed points = `dnf_mech × projected_per_race_loss`.

### Quali-race delta
Compares average qualifying position to average finishing position. Positive delta = race-day improver (clean starts, good strategy, tyre management). Surfaces drivers like Sainz and Pérez who consistently gain places on Sundays despite modest grid spots.

### Data pipeline
Multi-source ingestion designed to be resilient. If a source goes down, only that segment of the dashboard goes dark; the rest still updates. Sources:
- **Jolpica F1** (Ergast successor) for standings, calendar, race results, qualifying
- **OpenF1** for tyre strategies and pit stop timing (real-time-ish)
- **Reddit r/formula1** for news (primary)
- **RSS feeds** (Google News, BBC Sport F1, PlanetF1) for news fallback when Reddit blocks the GitHub Actions runner IP

Every fetch is wrapped in a `safe()` helper that catches exceptions, logs them, and returns a sensible fallback so a single failure doesn't crash the whole pipeline.

---

## 🛠 Tech stack

### Backend / data
- **Python 3** — data ingestion, statistical computation, classification heuristics, Monte Carlo simulation
- **`requests`** — HTTP client for Jolpica, OpenF1, Reddit, and RSS endpoints
- **`xml.etree.ElementTree`** — RSS parsing for news fallback
- **Standard library statistics** — mean, standard deviation, finish-position math

### Automation
- **GitHub Actions** — scheduled CI workflow that runs the Python pipeline and commits the regenerated `data.json` back to the repo. Triggers:
  - Manual trigger via `workflow_dispatch`
  - Sundays after race finish (handles regular Grand Prix weekends)
  - Saturdays for Sprint weekends (where the sprint race is run on Saturday)
- **GitHub Pages** — serves the static site directly from the repo

### Frontend
- **Vanilla JavaScript** — no frameworks, no build step, ~140KB single-file HTML. Async fetch on page load, hydrates static markup with live data from `data.json`.
- **HTML + CSS** — design system built around papaya orange (`#FF8000`) and racing carbon (`#0E0E10`), with team-specific accent colours pulled from the F1 brand palette
- **Google Fonts** — Playfair Display for headers, JetBrains Mono for stats

### AI agent (Papaya)
- **Cloudflare Workers** — edge-hosted chat backend
- **Anthropic Claude API** — LLM provider, streamed responses
- **Cloudflare KV** — daily rate limiting per IP
- **Retrieval-augmented context injection** — live season data piped into the system prompt at request time

---

## 📁 Repo structure

```
F1-Dashboard-Bhuvan/
├── index.html              # The entire frontend (HTML + CSS + JS in one file)
├── data.json               # Auto-generated by the GitHub Action — do not edit
├── update_f1_data.py       # The data pipeline that builds data.json
├── .github/
│   └── workflows/
│       └── update-data.yml # Action that runs the pipeline on schedule
└── README.md
```

---

## 🚀 Running locally

You don't need to run anything to *view* the site — just clone and open `index.html`. But to regenerate `data.json` yourself:

```bash
git clone https://github.com/ChBhuvan/F1-Dashboard-Bhuvan.git
cd F1-Dashboard-Bhuvan
python3 update_f1_data.py
```

This will hit all the live APIs and rewrite `data.json` in place. Takes about 30 to 90 seconds depending on how cooperative OpenF1 and Reddit are on the day.

To run Papaya locally, you'd need your own Cloudflare Workers account, an Anthropic API key, and to update `WORKER_URL` in `index.html` to point at your deployed worker. The worker code lives separately in Cloudflare's dashboard.

---

## 🔧 How automated updates work

The `update-data.yml` workflow runs the pipeline and commits the resulting `data.json` back to `main`. GitHub Pages then redeploys automatically within a minute or two.

Update cadence:
- **Sundays** after most race finishes
- **Saturdays** during Sprint weekends (so sprint results show up before the main race)
- **Manual triggers** via the Actions tab for one-off refreshes

Frontend data freshness depends on the last successful Action run. Jolpica typically updates 30 to 60 minutes after a race finishes, so the dashboard won't be live during the broadcast — but it'll catch up shortly after.

---

## 🧩 Notable engineering decisions

**No frontend framework.** A 140KB single HTML file loads faster than any React bundle, has zero build pipeline, and is dead simple to debug. The whole frontend is one file you can open and read top-to-bottom.

**JSON as the API.** The Python pipeline writes `data.json` to the repo, and the frontend fetches it at page load. No database, no server, no API gateway. GitHub Pages is the CDN. Total infrastructure cost: $0.

**Static markup, dynamic hydration.** The HTML ships with placeholder content already in place, so the first paint is instant even before `data.json` arrives. JavaScript then fills in the live numbers.

**Defensive ingestion.** Every API call goes through a `safe()` wrapper that returns a sensible fallback on failure (empty list, empty dict). One broken data source can't take down the whole dashboard.

**Heuristic where ground truth is missing.** Jolpica doesn't classify DNFs as mechanical or driver-error for 2026 yet. Rather than wait for them to backfill or scrape Wikipedia for every retirement, the classifier defaults to "mechanical" for unknown causes — which matches reality (drivers rarely retire healthy cars).

**Multi-source news with graceful degradation.** Reddit blocks GitHub Actions IPs sometimes. Rather than show "Loading…" forever, the pipeline tries Reddit first, then aggregates across three RSS feeds, and if all that fails the widget shows a polite "feed unavailable" state instead of hanging.

---

## 📈 Roadmap

Things I'd add if I keep poking at this:

- Historical season comparison (2024 vs 2025 vs 2026 trends)
- Driver-of-the-day style cards based on race-day positions gained
- Lap-by-lap position chart for each completed race (data already in OpenF1)
- Predictive race-result model (with appropriate caveats about variance)
- Mobile-first layout pass (it works on mobile, but it's designed desktop-first)

---

## 🙏 Credits

- **[Jolpica F1 API](https://github.com/jolpica/jolpica-f1)** — the open Ergast successor doing the heavy lifting on race data
- **[OpenF1](https://openf1.org/)** — real-time-ish telemetry for tyres and pit stops
- **r/formula1** — news headlines that the rest of the F1 internet eventually picks up
- **F1 brand palette** — team colours sourced from public team brand guidelines
- **Anthropic Claude** — Papaya's brain

Built by [Bhuvan Chappidi](https://github.com/ChBhuvan). If you're hiring for ML or data analytics roles and this kind of work interests you, let's chat.

---

## 📜 Licence

MIT. Fork it, remix it, build your own. If you do build something cool, send it my way.
