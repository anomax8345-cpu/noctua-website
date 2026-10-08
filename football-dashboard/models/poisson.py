"""Poisson / Expected-Goals model (Model B).

Given expected goals for each side (lambda_home, lambda_away) we build a score
matrix over 0..MAX_GOALS for each team and derive every market we care about
(1X2, Over/Under, BTTS). An optional Dixon-Coles low-score correction (`rho`)
dampens the independence assumption for 0-0/1-0/0-1/1-1, which independent
Poisson is known to misprice.

Lambdas can be supplied directly (e.g. from xG) or derived from scoring form
via `lambdas_from_strengths`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MAX_GOALS = 8
LEAGUE_AVG_GOALS_PER_SIDE = 1.35  # sensible global default; refined per league later


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _dc_tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles adjustment factor for low scores."""
    if i == 0 and j == 0:
        return 1.0 - lam * mu * rho
    if i == 0 and j == 1:
        return 1.0 + lam * rho
    if i == 1 and j == 0:
        return 1.0 + mu * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


@dataclass
class PoissonResult:
    lambda_home: float
    lambda_away: float
    home: float
    draw: float
    away: float
    over15: float
    over25: float
    over35: float
    under25: float
    btts: float
    expected_total: float

    def as_1x2(self) -> dict[str, float]:
        return {"home": self.home, "draw": self.draw, "away": self.away}


def score_matrix(lambda_home: float, lambda_away: float, rho: float = -0.03):
    matrix = [[0.0] * (MAX_GOALS + 1) for _ in range(MAX_GOALS + 1)]
    total = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = _poisson_pmf(i, lambda_home) * _poisson_pmf(j, lambda_away)
            p *= _dc_tau(i, j, lambda_home, lambda_away, rho)
            p = max(p, 0.0)
            matrix[i][j] = p
            total += p
    # renormalise (truncation + DC correction perturb the sum slightly)
    if total > 0:
        for i in range(MAX_GOALS + 1):
            for j in range(MAX_GOALS + 1):
                matrix[i][j] /= total
    return matrix


def predict(lambda_home: float, lambda_away: float, rho: float = -0.03) -> PoissonResult:
    m = score_matrix(lambda_home, lambda_away, rho)
    home = draw = away = 0.0
    over15 = over25 = over35 = btts = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = m[i][j]
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
            total_goals = i + j
            if total_goals >= 2:
                over15 += p
            if total_goals >= 3:
                over25 += p
            if total_goals >= 4:
                over35 += p
            if i >= 1 and j >= 1:
                btts += p
    return PoissonResult(
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        home=home,
        draw=draw,
        away=away,
        over15=over15,
        over25=over25,
        over35=over35,
        under25=1.0 - over25,
        btts=btts,
        expected_total=lambda_home + lambda_away,
    )


def lambdas_from_strengths(
    home_gf_pg: float,
    home_ga_pg: float,
    away_gf_pg: float,
    away_ga_pg: float,
    league_avg: float = LEAGUE_AVG_GOALS_PER_SIDE,
    home_boost: float = 1.12,
) -> tuple[float, float]:
    """Derive (lambda_home, lambda_away) from per-game scoring/conceding rates.

    attack_strength = team goals-for per game / league average
    defense_weakness = opponent goals-against per game / league average
    lambda = league_avg * attack_strength * opp_defense_weakness

    `home_boost` applies a mild home scoring premium. All inputs must be real
    observed rates; callers pass None-free numbers (missing data is handled
    upstream, never faked here).
    """
    la = max(league_avg, 0.1)
    home_attack = home_gf_pg / la
    away_attack = away_gf_pg / la
    home_def_weak = home_ga_pg / la
    away_def_weak = away_ga_pg / la
    lam_home = la * home_attack * away_def_weak * home_boost
    lam_away = la * away_attack * home_def_weak / home_boost
    # clamp to sane football range
    lam_home = min(max(lam_home, 0.1), 5.0)
    lam_away = min(max(lam_away, 0.1), 5.0)
    return lam_home, lam_away
