"""Walk-forward backtest engine — the no-look-ahead core.

The single most important correctness property of this module: when predicting
match M (kickoff T), it may only use information that existed strictly before T.
We enforce that structurally:

  * Fixtures are processed in strict chronological order of kickoff.
  * Elo ratings start neutral and are updated ONLY after a match is scored, so
    the rating used to predict M reflects results up to (but not including) M.
  * Form is computed from each team's matches that kicked off before M.

This means there is no path by which a future result can influence a past
prediction. The engine is deterministic and unit-tested with synthetic data.
"""
from __future__ import annotations

from dataclasses import dataclass

from backtest.metrics import ScoredPrediction, summarize
from models import elo as elo_mod
from models import form as form_mod
from models import poisson as poisson_mod
from models.ensemble import combine

OUTCOMES = ("home", "draw", "away")


def _actual_outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals == away_goals:
        return "draw"
    return "away"


@dataclass
class BacktestConfig:
    weights: dict | None = None
    home_advantage: float = elo_mod.DEFAULT_HOME_ADVANTAGE
    k: float = elo_mod.DEFAULT_K
    form_window: int = 10
    min_edge_pp: float = 3.0


def run_backtest(
    finished_fixtures: list[dict],
    market_prices: dict[int, dict] | None = None,
    config: BacktestConfig | None = None,
):
    """finished_fixtures: normalised fixtures with integer home_goals/away_goals,
    sorted or unsorted (we sort). market_prices: optional {fixture_id: {home,
    draw, away}} of historical market probabilities for ROI.

    Returns (BacktestSummary, list[ScoredPrediction]).
    """
    config = config or BacktestConfig()
    weights = config.weights or {
        "elo": 0.35, "poisson": 0.30, "form": 0.20, "home": 0.15,
    }
    market_prices = market_prices or {}

    fixtures = [
        f for f in finished_fixtures
        if f.get("home_goals") is not None and f.get("away_goals") is not None
    ]
    fixtures.sort(key=lambda f: f["kickoff_utc"])

    ratings: dict[int, elo_mod.EloRating] = {}
    history: dict[int, list[dict]] = {}  # team_id -> prior finished matches
    scored: list[ScoredPrediction] = []

    def rating(tid: int) -> elo_mod.EloRating:
        return ratings.setdefault(tid, elo_mod.EloRating())

    for fx in fixtures:
        hid, aid = fx["home_team_id"], fx["away_team_id"]
        hr, ar = rating(hid), rating(aid)

        # --- build prediction using only prior data ---
        elo_probs = elo_mod.match_probabilities(hr.elo, ar.elo, config.home_advantage)

        home_hist = history.get(hid, [])
        away_hist = history.get(aid, [])
        hf = form_mod.summarize(hid, home_hist, config.form_window, "all")
        af = form_mod.summarize(aid, away_hist, config.form_window, "all")

        poisson_probs = None
        if hf.played >= 3 and af.played >= 3:
            lam_h, lam_a = poisson_mod.lambdas_from_strengths(
                hf.gf_pg, hf.ga_pg, af.gf_pg, af.ga_pg
            )
            poisson_probs = poisson_mod.predict(lam_h, lam_a).as_1x2()

        form_probs = None
        if hf.played >= 3 and af.played >= 3:
            form_probs = form_mod.form_probabilities(hf.ppg, af.ppg)

        ensemble = combine(
            {
                "elo": elo_probs,
                "poisson": poisson_probs,
                "form": form_probs,
                "home": elo_probs,  # home-advantage channel reuses elo w/ HFA
            },
            weights,
        )
        probs = ensemble.probabilities
        top = ensemble.top_pick()

        actual = _actual_outcome(fx["home_goals"], fx["away_goals"])
        prob_actual = probs[actual]
        top_hit = top == actual

        # market / edge (optional)
        edge_pp = None
        market_price = None
        won = None
        mp = market_prices.get(fx["id"])
        if mp and top in mp and mp[top]:
            market_price = mp[top]
            edge_pp = (probs[top] - mp[top]) * 100.0
            won = top == actual

        scored.append(
            ScoredPrediction(
                prob_actual=prob_actual,
                top_pick_hit=top_hit,
                edge_pp=edge_pp,
                market_price=market_price,
                won=won,
            )
        )

        # --- now (and only now) update ratings & history with this result ---
        nh, na = elo_mod.update_ratings(
            hr, ar, fx["home_goals"], fx["away_goals"], config.k, config.home_advantage
        )
        ratings[hid], ratings[aid] = nh, na
        history.setdefault(hid, []).append(fx)
        history.setdefault(aid, []).append(fx)

    return summarize(scored, config.min_edge_pp), scored
