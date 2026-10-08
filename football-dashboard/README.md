# Football Market Analyzer — Polymarket Edge Research

A **local** web app that finds football matches in the next 48 hours, runs its
**own probability model**, compares it to **live Polymarket prices**, and shows
the **edge**, a **confidence score**, and (over time) **historical calibration**.

> It is a research/analysis tool. It is **not** a tipster. A probability of 75%
> means the model estimates this outcome at ~75% — nothing more. No "sure bets",
> no automatic orders. Paper-trading / backtesting only in this version.

---

## What it does (Phase 1 — MVP, implemented)

- Loads fixtures for the next 48h across a large, configurable league catalog
  (`config.py` — not hard-wired; enable `ALL` or a named list).
- Builds an **independent probability model** per match:
  - **Elo** (Davidson draw model, margin-of-victory updates)
  - **Poisson / xG** (Dixon-Coles corrected score matrix → 1X2, O/U, BTTS)
  - **Form** (PPG-based), split home/away
  - **Ensemble** with configurable weights that **renormalise automatically**
    when a model's data is missing.
- Finds and **matches Polymarket markets** to fixtures with an explicit
  **confidence score** — low-confidence matches are **not** auto-assigned.
- Computes **Model % − Market % = Edge (pp)** and a separate **Confidence
  (0–100)** that reflects *data quality*, not win probability.
- **Stores every prediction** (with model version) in SQLite for later
  calibration and model comparison.
- **Backtest engine** that replays history with **no data leakage** (each match
  predicted using only pre-kickoff data), reporting Brier / Log-loss / Accuracy
  / ECE / paper-ROI / drawdown, plus probability-bucket calibration.
- Dark, responsive dashboard: top edges, filterable match table, per-match
  detail with the full model breakdown.
- **Never fabricates data** — missing xG / injuries / markets show as `N/A`.

### Not yet implemented (later phases, structure is in place)
Phase 2: confirmed lineups, richer injury importance, live xG feeds.
Phase 3: scheduled result settlement + continuous recalibration.
Phase 4: paper-trading ledger UI, alerts (browser/Telegram/Discord).
Phase 5: optional live trading — intentionally out of scope and un-built.

---

## Install & run (local)

Requires Python 3.11+.

```bash
cd football-dashboard

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
# edit .env and set API_FOOTBALL_KEY=...   (get one at api-football.com)

python app.py
```

Then open **http://127.0.0.1:5000**.

Set the API key via `.env` **or** on the Settings page (stored server-side,
never shown to the browser). Shell alternative:

```bash
export API_FOOTBALL_KEY="your-key"       # macOS/Linux
$env:API_FOOTBALL_KEY="your-key"         # Windows PowerShell
```

The app runs **without** a key or network — it just shows "configure your key"
and "markets unavailable" instead of data.

> **Note on this cloud workspace:** the sandbox that generated this code blocks
> outbound access to `api-sports.io` and `polymarket.com`, so live data could
> not be exercised here. The API clients are written to the official documented
> response shapes; run the app on your own machine (open internet) to pull live
> data. All logic is covered by offline unit tests.

## Tests

```bash
python -m pytest -q
```

Covers the models, matching/confidence, graceful degradation, and the
**no-leakage** property of the backtest engine.

## Backtesting (needs a key + historical coverage)

```bash
python -m backtest.run --start 2025-01-01 --end 2026-10-01 \
    --leagues "Bundesliga,Premier League" --seasons 2024,2025
```

## Project layout

```
football-dashboard/
├── app.py               Flask app (pages + JSON API)
├── config.py            settings + league catalog (data, not hard-wired logic)
├── database/            SQLite schema + access layer
├── data/                API-Football & Polymarket clients, cache, name matching
├── models/              elo, poisson, form, xg, ensemble, calibration, confidence
├── backtest/            no-leakage engine, metrics, calibration, CLI runner
├── services/pipeline.py orchestration: data → model → market → edge → storage
├── templates/ static/   dark-mode UI
└── tests/               offline unit + smoke tests
```

## Key design guarantees

- **No look-ahead in backtests.** Fixtures are processed in kickoff order; Elo
  and form are updated *after* each match is scored (`backtest/engine.py`).
- **No invented data.** Every optional feature is real or `N/A`.
- **Secrets stay server-side.** The API key is only ever a request header.
- **Matching is conservative.** A market is attached to a fixture only above a
  confidence threshold.
