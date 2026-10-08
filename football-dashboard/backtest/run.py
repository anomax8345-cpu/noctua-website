"""CLI backtest runner.

Usage:
    python -m backtest.run --start 2025-01-01 --end 2026-10-01 \
        --leagues "Bundesliga,Premier League"

Fetches finished fixtures for the chosen leagues/seasons from API-Football,
replays them through the no-leakage engine, and stores a summary row in
`backtest_results`. Requires API_FOOTBALL_KEY and historical coverage.

Without a key / network this module still imports cleanly; it only needs the
network when actually executed.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from backtest.engine import BacktestConfig, run_backtest
from config import MODEL_VERSION, SETTINGS, LEAGUE_BY_NAME
from data.api_football import ApiFootballClient
from database.database import get_db


def fetch_history(af: ApiFootballClient, league_id: int, season: int) -> list[dict]:
    payload = af._get(  # noqa: SLF001 - intentional reuse of cached GET
        "fixtures",
        {"league": league_id, "season": season, "timezone": "UTC"},
        ttl=86400,
    )
    out = []
    for item in payload.get("response", []):
        norm = af._normalize_fixture(item)  # noqa: SLF001
        if norm and norm["home_goals"] is not None and norm["away_goals"] is not None:
            out.append(norm)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a no-leakage football backtest.")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--leagues", default="ALL", help="comma-separated names or ALL")
    ap.add_argument("--seasons", default="2024,2025", help="comma-separated years")
    args = ap.parse_args()

    af = ApiFootballClient(SETTINGS)
    names = (
        [n.strip() for n in args.leagues.split(",")]
        if args.leagues.upper() != "ALL"
        else list(LEAGUE_BY_NAME.keys())
    )
    seasons = [int(s) for s in args.seasons.split(",")]

    all_fixtures: list[dict] = []
    for name in names:
        lg = LEAGUE_BY_NAME.get(name)
        if not lg:
            print(f"  ! unknown league: {name}")
            continue
        for season in seasons:
            fx = fetch_history(af, lg.api_football_id, season)
            print(f"  {name} {season}: {len(fx)} finished fixtures")
            all_fixtures.extend(fx)

    # filter to date range
    start, end = args.start, args.end
    all_fixtures = [f for f in all_fixtures if start <= f["kickoff_utc"][:10] <= end]
    print(f"Total fixtures in range: {len(all_fixtures)}")

    summary, _ = run_backtest(all_fixtures, config=BacktestConfig())
    print(json.dumps(summary.to_dict(), indent=2))

    db = get_db()
    d = summary.to_dict()
    db.execute(
        """INSERT INTO backtest_results
           (run_utc, model_version, start_date, end_date, n_matches, brier,
            log_loss, accuracy, ece, roi, max_drawdown, win_rate, avg_edge, detail_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now(timezone.utc).isoformat(), MODEL_VERSION, start, end,
            d["n"], d["brier"], d["log_loss"], d["accuracy"], d["ece"], d["roi"],
            d["max_drawdown"], d["win_rate"], d["avg_edge"], json.dumps(d["buckets"]),
        ),
    )
    print("Stored backtest_results row.")


if __name__ == "__main__":
    main()
