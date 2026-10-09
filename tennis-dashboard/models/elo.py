"""Tennis Elo model (overall + surface-specific).

Tennis is two-outcome (no draw), so Elo maps cleanly to a win probability via
the standard logistic expectancy:

    P(p1 beats p2) = 1 / (1 + 10^(-(R1 - R2)/400))

We keep an overall rating and a per-surface rating for each player, and blend
them for the prediction (surface form matters a lot in tennis). Ratings are
updated after each match; K is larger for players with few matches (provisional)
and smaller once established. This module has no look-ahead: the backtest engine
updates ratings only after scoring a match.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_RATING = 1500.0
SURFACE_BLEND = 0.65   # weight on surface-specific rating vs overall


@dataclass
class PlayerRating:
    elo: float = DEFAULT_RATING
    surface: dict[str, float] = field(default_factory=dict)  # {"Clay": 1700, ...}
    matches: int = 0
    last_change: float = 0.0

    def surface_elo(self, surface: str | None) -> float:
        if surface and surface in self.surface:
            return self.surface[surface]
        return self.elo

    def blended(self, surface: str | None) -> float:
        if not surface or surface not in self.surface:
            return self.elo
        return SURFACE_BLEND * self.surface[surface] + (1 - SURFACE_BLEND) * self.elo


def win_probability(rating1: float, rating2: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(rating1 - rating2) / 400.0))


def match_probabilities(r1: PlayerRating, r2: PlayerRating, surface: str | None) -> dict[str, float]:
    p1 = win_probability(r1.blended(surface), r2.blended(surface))
    return {"p1": p1, "p2": 1.0 - p1}


def _k_factor(matches: int) -> float:
    # provisional players move faster; established players are stable
    return 250.0 / ((matches + 5) ** 0.4)


def update_ratings(r1: PlayerRating, r2: PlayerRating, winner: str, surface: str | None
                   ) -> tuple[PlayerRating, PlayerRating]:
    """Return updated ratings after a finished match. winner is 'p1' or 'p2'."""
    if winner not in ("p1", "p2"):
        return r1, r2
    s1 = 1.0 if winner == "p1" else 0.0

    # overall
    exp1 = win_probability(r1.elo, r2.elo)
    k1, k2 = _k_factor(r1.matches), _k_factor(r2.matches)
    d1 = k1 * (s1 - exp1)
    new1 = PlayerRating(elo=r1.elo + d1, surface=dict(r1.surface),
                        matches=r1.matches + 1, last_change=d1)
    new2 = PlayerRating(elo=r2.elo - k2 * (s1 - exp1), surface=dict(r2.surface),
                        matches=r2.matches + 1, last_change=-k2 * (s1 - exp1))

    # surface-specific
    if surface:
        sr1 = r1.surface.get(surface, r1.elo)
        sr2 = r2.surface.get(surface, r2.elo)
        se1 = win_probability(sr1, sr2)
        new1.surface[surface] = sr1 + k1 * (s1 - se1)
        new2.surface[surface] = sr2 - k2 * (s1 - se1)
    return new1, new2
