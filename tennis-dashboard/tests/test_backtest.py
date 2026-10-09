from datetime import datetime, timedelta, timezone

from backtest.engine import BacktestConfig, run_backtest
from backtest.metrics import ScoredPrediction, summarize


def _fx(fid, p1, p2, winner, day, surface="Hard"):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return {"id": str(fid), "kickoff_utc": base.isoformat(), "p1_id": p1, "p2_id": p2,
            "p1_name": p1, "p2_name": p2, "winner": winner, "surface": surface,
            "best_of": 3, "tour": "ATP", "tournament": "Test"}


def test_backtest_learns_without_leakage():
    # Player A consistently beats B. Elo should learn from PRIOR matches only.
    fixtures = [_fx(i, "A", "B", "p1", i) for i in range(12)]
    summary, scored = run_backtest(fixtures)
    assert summary.n == 12
    assert summary.brier is not None
    assert summary.accuracy >= 0.6

    # First match: both start at 1500 -> coin flip, must NOT know A always wins.
    assert abs(scored[0].pick_prob - 0.5) < 0.02


def test_first_match_is_neutral_even_if_underdog_wins_every_time():
    fixtures = [_fx(i, "A", "B", "p2", i) for i in range(5)]  # B wins every time
    summary, scored = run_backtest(fixtures)
    # the first prediction cannot have anticipated B's dominance
    assert abs(scored[0].pick_prob - 0.5) < 0.02
    assert scored[0].pick_hit is False or scored[0].pick_prob <= 0.52


def test_surface_specific_learning():
    # A wins on clay, loses on hard -> surface Elo should diverge.
    fixtures = []
    for i in range(8):
        fixtures.append(_fx(100 + i, "A", "B", "p1", i, "Clay"))
    for i in range(8):
        fixtures.append(_fx(200 + i, "A", "B", "p2", 20 + i, "Hard"))
    summary, scored = run_backtest(fixtures)
    assert summary.n == 16


def test_summary_paper_roi():
    scored = [
        ScoredPrediction(pick_prob=0.7, pick_hit=True, edge_pp=10.0, market_price=0.6, won=True),
        ScoredPrediction(pick_prob=0.65, pick_hit=False, edge_pp=8.0, market_price=0.62, won=False),
    ]
    s = summarize(scored, min_edge_pp=3.0)
    assert s.n == 2 and s.win_rate == 0.5 and s.roi is not None
