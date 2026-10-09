"""CLI backtest runner (tennis).

Usage:
    python -m backtest.run --start 2025-01-01 --end 2026-10-01

Fetches finished fixtures in the range from API-Tennis, replays them through
the no-leakage engine, and stores a summary row in `backtest_results`.
Requires API_TENNIS_KEY and network access.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from backtest.engine import BacktestConfig, run_backtest
from config import MODEL_VERSION, SETTINGS
from data.api_tennis import ApiTennisClient
from database.database import get_db


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a no-leakage tennis backtest.")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    at = ApiTennisClient(SETTINGS)
    start = datetime.fromisoformat(args.start + "T00:00:00+00:00")
    end = datetime.fromisoformat(args.end + "T23:59:59+00:00")

    # API-Tennis caps the date range per request; chunk month-by-month.
    fixtures: list[dict] = []
    cur = start
    from datetime import timedelta
    while cur < end:
        chunk_end = min(cur + timedelta(days=30), end)
        fixtures.extend(at.fixtures_between(cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    fixtures = [f for f in fixtures if f.get("winner") in ("p1", "p2")]
    print(f"Finished fixtures in range: {len(fixtures)}")

    summary, _ = run_backtest(fixtures, config=BacktestConfig())
    d = summary.to_dict()
    print(json.dumps(d, indent=2))

    db = get_db()
    db.execute(
        """INSERT INTO backtest_results
           (run_utc, model_version, start_date, end_date, n_matches, brier,
            log_loss, accuracy, ece, roi, max_drawdown, win_rate, avg_edge, detail_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now(timezone.utc).isoformat(), MODEL_VERSION, args.start, args.end,
         d["n"], d["brier"], d["log_loss"], d["accuracy"], d["ece"], d["roi"],
         d["max_drawdown"], d["win_rate"], d["avg_edge"], json.dumps(d["buckets"])),
    )
    print("Stored backtest_results row.")


if __name__ == "__main__":
    main()
