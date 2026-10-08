"""Elo rating model (Model A).

Two responsibilities:
  1. Maintain/update Elo ratings from match results (used chronologically by
     the backtest engine so there is never any look-ahead).
  2. Turn a pair of ratings into 1X2 probabilities.

For 1X2 we use the **Davidson (1970) model for ties**, which extends the
Bradley-Terry/Elo expectancy with a principled draw term controlled by a single
parameter `nu`. This is symmetric and well understood — not an ad-hoc fudge:

    h = 10^((R_home + HFA) / 400)
    a = 10^(R_away / 400)
    d = nu * sqrt(h * a)
    P(home) = h / (h + a + d)
    P(draw) = d / (h + a + d)
    P(away) = a / (h + a + d)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_RATING = 1500.0
DEFAULT_HOME_ADVANTAGE = 65.0   # Elo points; ~ historical home edge
DEFAULT_K = 24.0                # update speed
DEFAULT_NU = 0.60               # draw tendency for football


@dataclass
class EloRating:
    elo: float = DEFAULT_RATING
    elo_home: float = DEFAULT_RATING
    elo_away: float = DEFAULT_RATING
    games: int = 0
    last_change: float = 0.0


def expected_score(rating_a: float, rating_b: float) -> float:
    """Classic Elo expectancy of A vs B (draw counts as 0.5)."""
    return 1.0 / (1.0 + 10 ** (-(rating_a - rating_b) / 400.0))


def match_probabilities(
    home_elo: float,
    away_elo: float,
    home_advantage: float = DEFAULT_HOME_ADVANTAGE,
    nu: float = DEFAULT_NU,
) -> dict[str, float]:
    """Davidson-model 1X2 probabilities. Returns keys home/draw/away."""
    h = 10 ** ((home_elo + home_advantage) / 400.0)
    a = 10 ** (away_elo / 400.0)
    d = nu * math.sqrt(h * a)
    total = h + a + d
    return {
        "home": h / total,
        "draw": d / total,
        "away": a / total,
    }


def update_ratings(
    home: EloRating,
    away: EloRating,
    home_goals: int,
    away_goals: int,
    k: float = DEFAULT_K,
    home_advantage: float = DEFAULT_HOME_ADVANTAGE,
) -> tuple[EloRating, EloRating]:
    """Return updated (home, away) ratings after a finished match.

    Margin-of-victory scaling (FiveThirtyeight-style) rewards bigger wins but
    with diminishing returns. Also maintains venue-specific ratings.
    """
    if home_goals is None or away_goals is None:
        return home, away

    exp_home = expected_score(home.elo + home_advantage, away.elo)
    if home_goals > away_goals:
        score_home = 1.0
    elif home_goals == away_goals:
        score_home = 0.5
    else:
        score_home = 0.0

    margin = abs(home_goals - away_goals)
    mov = math.log(max(margin, 1) + 1.0)  # 1->0.69, 2->1.10, 3->1.39 ...
    delta = k * mov * (score_home - exp_home)

    new_home = EloRating(
        elo=home.elo + delta,
        elo_home=home.elo_home + delta,   # this match was a home game for `home`
        elo_away=home.elo_away,
        games=home.games + 1,
        last_change=delta,
    )
    new_away = EloRating(
        elo=away.elo - delta,
        elo_home=away.elo_home,
        elo_away=away.elo_away - delta,   # away game for `away`
        games=away.games + 1,
        last_change=-delta,
    )
    return new_home, new_away
