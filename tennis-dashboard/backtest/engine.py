"""Walk-forward backtest engine (tennis) — the no-look-ahead core.

Matches are processed in strict chronological order. Elo (overall + surface) is
updated ONLY after a match is scored, and form/H2H are computed from prior
matches only, so a future result can never influence a past prediction.
"""
from __future__ import annotations

from dataclasses import dataclass

from backtest.metrics import ScoredPrediction, summarize
from models import elo as elo_mod
from models import form as form_mod
from models import h2h as h2h_mod
from models import points as points_mod
from models.ensemble import combine


@dataclass
class BacktestConfig:
    weights: dict | None = None
    form_window: int = 15
    min_edge_pp: float = 3.0


def run_backtest(finished_fixtures: list[dict],
                 market_prices: dict[str, dict] | None = None,
                 config: BacktestConfig | None = None):
    config = config or BacktestConfig()
    weights = config.weights or {"elo_surface": 0.45, "points": 0.20, "form": 0.20, "h2h": 0.15}
    market_prices = market_prices or {}

    fixtures = [f for f in finished_fixtures if f.get("winner") in ("p1", "p2")]
    fixtures.sort(key=lambda f: f["kickoff_utc"])

    ratings: dict[str, elo_mod.PlayerRating] = {}
    history: dict[str, list[dict]] = {}
    h2h_record: dict[tuple[str, str], list[int]] = {}
    scored: list[ScoredPrediction] = []

    def rating(pid: str) -> elo_mod.PlayerRating:
        return ratings.setdefault(pid, elo_mod.PlayerRating())

    for fx in fixtures:
        p1, p2 = fx["p1_id"], fx["p2_id"]
        surface = fx.get("surface")
        r1, r2 = rating(p1), rating(p2)

        elo_probs = elo_mod.match_probabilities(r1, r2, surface)

        f1 = form_mod.summarize(p1, history.get(p1, []), config.form_window)
        f2 = form_mod.summarize(p2, history.get(p2, []), config.form_window)
        form_probs = (form_mod.form_probabilities(f1.win_pct, f2.win_pct)
                      if f1.played >= 3 and f2.played >= 3 else None)

        rec = h2h_record.get((p1, p2)) or h2h_record.get((p2, p1))
        h2h_probs = None
        if rec:
            # rec stored as [p1_key_wins, p2_key_wins] relative to the stored key order
            if (p1, p2) in h2h_record:
                h2h_probs = h2h_mod.h2h_probabilities(rec[0], rec[1])
            else:
                flipped = h2h_mod.h2h_probabilities(rec[1], rec[0])
                h2h_probs = flipped

        points_probs = points_mod.predict_calibrated(
            elo_probs["p1"], best_of=fx.get("best_of", 3)
        ).as_match()

        ensemble = combine(
            {"elo_surface": elo_probs, "points": points_probs,
             "form": form_probs, "h2h": h2h_probs},
            weights,
        )
        probs = ensemble.probabilities
        top = ensemble.top_pick()
        pick_prob = probs[top]
        actual = fx["winner"]
        pick_hit = top == actual

        edge_pp = market_price = won = None
        mp = market_prices.get(fx["id"])
        if mp and top in mp and mp[top]:
            market_price = mp[top]
            edge_pp = (pick_prob - mp[top]) * 100.0
            won = pick_hit

        scored.append(ScoredPrediction(pick_prob=pick_prob, pick_hit=pick_hit,
                                       edge_pp=edge_pp, market_price=market_price, won=won))

        # update AFTER scoring (no leakage)
        n1, n2 = elo_mod.update_ratings(r1, r2, actual, surface)
        ratings[p1], ratings[p2] = n1, n2
        history.setdefault(p1, []).append(fx)
        history.setdefault(p2, []).append(fx)
        key = (p1, p2)
        rec2 = h2h_record.setdefault(key, [0, 0])
        if actual == "p1":
            rec2[0] += 1
        else:
            rec2[1] += 1

    return summarize(scored, config.min_edge_pp), scored
