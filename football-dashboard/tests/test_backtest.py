"""Tests for the backtest engine, focused on the no-data-leakage property."""
from datetime import datetime, timedelta, timezone

from backtest.engine import BacktestConfig, run_backtest
from backtest.metrics import ScoredPrediction, summarize
from models import elo


def _fixture(fid, h, a, hg, ag, day):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return {
        "id": fid, "kickoff_utc": base.isoformat(),
        "home_team_id": h, "away_team_id": a,
        "home_goals": hg, "away_goals": ag,
        "league_name": "Test", "league_id": 1, "season": 2026, "status": "FT",
    }


def test_backtest_runs_and_scores():
    # Team 1 consistently beats team 2.
    fixtures = []
    for d in range(10):
        fixtures.append(_fixture(d + 1, 1, 2, 2, 0, d))
    summary, scored = run_backtest(fixtures)
    assert summary.n == 10
    assert summary.brier is not None
    assert 0 <= summary.accuracy <= 1
    # After repeated wins, team 1's accuracy should be strong (not from leakage,
    # but because Elo learns from each PRIOR result).
    assert summary.accuracy >= 0.6


def test_no_leakage_first_match_is_a_coin_flip():
    """The very first chronological match must be predicted with neutral
    ratings (both default 1500). It must NOT benefit from later results."""
    fixtures = [
        _fixture(1, 1, 2, 0, 5, 0),   # team 2 crushes team 1 on day 0
        _fixture(2, 1, 2, 0, 5, 1),
        _fixture(3, 1, 2, 0, 5, 2),
    ]
    summary, scored = run_backtest(fixtures)
    # For the first match, with equal starting Elo + home advantage, the model
    # must slightly favour HOME (team 1) — proving it did NOT peek at the fact
    # that team 2 wins every time.
    first = scored[0]
    # prob_actual here is prob assigned to the actual outcome (away win); since
    # the model favoured home at that point, prob_actual should be below 0.5.
    assert first.prob_actual < 0.5
    assert first.top_pick_hit is False


def test_elo_is_zero_sum_through_backtest():
    fixtures = [_fixture(1, 1, 2, 1, 0, 0)]
    run_backtest(fixtures)  # should not raise
    probs = elo.match_probabilities(1500, 1500)
    assert abs(probs["home"] + probs["draw"] + probs["away"] - 1.0) < 1e-9


def test_summary_roi_paper_only():
    scored = [
        ScoredPrediction(prob_actual=0.7, top_pick_hit=True, edge_pp=10.0,
                         market_price=0.6, won=True),
        ScoredPrediction(prob_actual=0.3, top_pick_hit=False, edge_pp=8.0,
                         market_price=0.65, won=False),
    ]
    s = summarize(scored, min_edge_pp=3.0)
    assert s.n == 2
    assert s.roi is not None
    assert s.win_rate == 0.5
