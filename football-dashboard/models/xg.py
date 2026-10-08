"""xG model.

If expected-goals data is available for both teams, we turn it into Poisson
lambdas and reuse the Poisson machinery. When xG is unavailable (very common
outside the big-5 leagues), this model returns None so the ensemble cleanly
falls back to the other models — we never fabricate xG.
"""
from __future__ import annotations

from models.poisson import PoissonResult, lambdas_from_strengths, predict


def xg_available(home_xg, home_xga, away_xg, away_xga) -> bool:
    return all(v is not None for v in (home_xg, home_xga, away_xg, away_xga))


def predict_from_xg(
    home_xg_pg: float | None,
    home_xga_pg: float | None,
    away_xg_pg: float | None,
    away_xga_pg: float | None,
    league_avg: float = 1.35,
) -> PoissonResult | None:
    """Build a Poisson prediction from per-game xG/xGA rates.

    Returns None when any xG input is missing (triggers ensemble fallback).
    """
    if not xg_available(home_xg_pg, home_xga_pg, away_xg_pg, away_xga_pg):
        return None
    lam_home, lam_away = lambdas_from_strengths(
        home_gf_pg=home_xg_pg,
        home_ga_pg=home_xga_pg,
        away_gf_pg=away_xg_pg,
        away_ga_pg=away_xga_pg,
        league_avg=league_avg,
    )
    return predict(lam_home, lam_away)
