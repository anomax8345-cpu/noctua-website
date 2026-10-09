# Tennis Market Analyzer — Polymarket Edge Research

A **local** web app that finds tennis matches in the next 48 hours, runs its
**own probability model**, compares it to **live Polymarket prices**, and shows
the **edge**, a **confidence score**, and (over time) **historical calibration**.
It is the tennis sibling of the football dashboard and is a completely separate
project (own data provider, own model, own database, own port).

> Research/analysis tool — **not** a tipster. A probability of 75% means the
> model estimates that outcome at ~75%, nothing more. No "sure bets", no
> automatic orders. Paper-trading / backtesting only in this version.

## What it does (Phase 1 — MVP, implemented)

- Loads tennis matches for the next 48h across a configurable tour catalog
  (ATP, WTA, Challenger, ITF, Grand Slam, team events) — `ENABLED_TOURS=ALL` or a list.
- Builds an **independent 2-way model** per match (tennis has no draw):
  - **Elo — overall + surface-specific** (Hard/Clay/Grass/Carpet), blended.
    Surface is decisive in tennis, so each player carries per-surface ratings.
  - **Serve/points hierarchical model** — game → set → match win probability
    (the tennis analog of a Poisson model), also yielding the set-win
    probability. Calibrated to the Elo match line when raw serve stats are
    absent, so set/derived markets stay coherent.
  - **Form** (recent win %, overall and on the match surface).
  - **Head-to-head** (Beta-smoothed, skipped when there's no prior meeting).
  - **Ensemble** with configurable weights that **renormalise automatically**
    when a component's data is missing.
- Finds and **matches Polymarket tennis markets** to fixtures with an explicit
  **confidence score** (surname-aware name matching) — low-confidence matches
  are **not** auto-assigned.
- Computes **Model % − Market % = Edge (pp)** plus a separate **Confidence
  (0–100)** reflecting *data quality* (both players rated, surface known/rated,
  H2H present, market liquidity/spread, historical calibration), not win odds.
- **Stores every prediction** (with model version) in SQLite for calibration.
- **No-leakage backtest engine**: replays matches chronologically, updating
  overall + surface Elo only after each result; reports Brier/Log-loss/Accuracy/
  ECE/paper-ROI/drawdown and probability-bucket calibration.
- Dark, responsive dashboard (top edges, filter table, per-match breakdown).
- **Never fabricates data** — missing surface / H2H / market → `N/A`.

### Later phases (structure in place)
Phase 2: real serve/return stats, player injuries/withdrawals, fatigue (matches
in last N days, travel). Phase 3: scheduled result settlement + recalibration.
Phase 4: paper-trading ledger, alerts. Phase 5: optional live trading (not built).

## Install & run (local)

Python 3.11+.

```bash
cd tennis-dashboard
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # set API_TENNIS_KEY=...  (api-tennis.com)
python app.py
```

Open **http://127.0.0.1:5001** (port 5001 so it can run alongside the football
dashboard on 5000).

> **Data provider note:** API-Sports (the football provider) does **not** cover
> tennis, so this app uses **API-Tennis (api-tennis.com)** with a separate key
> `API_TENNIS_KEY`. The client is written to that provider's documented
> method-based responses and is isolated in `data/api_tennis.py`, so swapping to
> another tennis provider is a localised change.
>
> **Sandbox note:** the cloud workspace that generated this code blocks outbound
> access to api-tennis.com and polymarket.com, so live data wasn't exercised
> here. Run it locally (open internet) for live data. All logic is covered by
> offline unit tests.

## Tests
```bash
python -m pytest -q      # 31 tests: models, serve math, matching, no-leakage backtest, smoke
```

## Backtesting (needs a key)
```bash
python -m backtest.run --start 2025-01-01 --end 2026-10-01
```

## Layout
```
tennis-dashboard/
├── app.py               Flask app (port 5001)
├── config.py            settings + tour catalog + surface classification
├── database/            SQLite schema + access layer
├── data/                API-Tennis & Polymarket clients, cache, name matching
├── models/              elo (+surface), points (serve), form, h2h, ensemble, calibration, confidence
├── backtest/            no-leakage engine, metrics, calibration, CLI runner
├── services/pipeline.py orchestration: data → model → market → edge → storage
├── templates/ static/   dark-mode UI
└── tests/               offline unit + smoke tests
```

## Key guarantees
- **No look-ahead in backtests** (chronological; Elo/form/H2H updated after scoring).
- **No invented data** — optional features are real or `N/A`.
- **API key server-side only** (a query param built on the server, never sent to the browser).
- **Conservative matching** — a market attaches to a fixture only above a confidence threshold.
