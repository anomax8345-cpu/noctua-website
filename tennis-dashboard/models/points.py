"""Serve / points hierarchical model (the tennis analog of the Poisson model).

Given each player's probability of winning a point on their own serve, the
standard tennis hierarchy gives game -> set -> match win probabilities, plus the
set-score distribution (2-0 / 2-1 for best-of-3). This is what powers derived
markets (set betting, total games) on the detail page.

When real serve/return stats are unavailable (the common case in an MVP), we
*calibrate* symmetric serve edges to a target match probability (from the Elo
model) via `predict_calibrated`, so the hierarchy still produces a coherent
set-score distribution consistent with the match line. This is clearly a
derived quantity, not invented data.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

BASE_SPW = 0.64  # tour-average point win on serve (ATP-ish); configurable


def game_win_prob(p: float) -> float:
    """Probability the server wins a game given point-win prob p (closed form)."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    q = 1 - p
    deuce = (p * p) / (p * p + q * q)
    return (p ** 4
            + 4 * p ** 4 * q
            + 10 * p ** 4 * q ** 2
            + 20 * p ** 3 * q ** 3 * deuce)


def _tiebreak_win_prob(a: float, b: float) -> float:
    """Prob player A wins a 7-point tiebreak.
    a = P(A wins a point on A's serve); b = P(A wins a point on B's serve).
    Serve order: A, BB, AA, BB, ... At 6-6 use the alternating-serve deuce
    solution over a serve pair."""
    deuce = (a * b) / (a * b + (1 - a) * (1 - b)) if (a * b + (1 - a) * (1 - b)) > 0 else 0.5

    def server_is_A(points_played: int) -> bool:
        if points_played == 0:
            return True
        n = (points_played - 1) // 2
        return n % 2 == 1  # after first point, pairs: B,B,A,A,...

    states = {(0, 0): 1.0}
    win = 0.0
    # iterate until all mass resolved or 6-6 reached
    for _ in range(200):
        nxt: dict[tuple[int, int], float] = {}
        for (sa, sb), prob in states.items():
            if sa >= 7 and sa - sb >= 2:
                win += prob
                continue
            if sb >= 7 and sb - sa >= 2:
                continue
            if sa == 6 and sb == 6:
                win += prob * deuce
                continue
            pts = sa + sb
            pa = a if server_is_A(pts) else b
            nxt[(sa + 1, sb)] = nxt.get((sa + 1, sb), 0.0) + prob * pa
            nxt[(sa, sb + 1)] = nxt.get((sa, sb + 1), 0.0) + prob * (1 - pa)
        states = nxt
        if not states:
            break
    return win


def _set_win_prob(gA: float, gB: float, a: float, b: float) -> float:
    """Prob player A wins a set. gA = A's hold prob (win own serve game),
    gB = B's hold prob. A serves game 1. Tiebreak at 6-6."""
    # A wins a game on A's serve = gA; A wins a game on B's serve = 1 - gB
    tb = _tiebreak_win_prob(a, b)

    def a_serves(games_played: int) -> bool:
        return games_played % 2 == 0  # A serves games 0,2,4,...

    states = {(0, 0): 1.0}
    win = 0.0
    for _ in range(100):
        nxt: dict[tuple[int, int], float] = {}
        for (ga, gb), prob in states.items():
            if ga >= 6 and ga - gb >= 2:
                win += prob
                continue
            if gb >= 6 and gb - ga >= 2:
                continue
            if ga == 6 and gb == 6:
                win += prob * tb
                continue
            gp = ga + gb
            pa_game = gA if a_serves(gp) else (1 - gB)
            nxt[(ga + 1, gb)] = nxt.get((ga + 1, gb), 0.0) + prob * pa_game
            nxt[(ga, gb + 1)] = nxt.get((ga, gb + 1), 0.0) + prob * (1 - pa_game)
        states = nxt
        if not states:
            break
    return win


def match_win_prob(set_prob: float, best_of: int = 3) -> float:
    s = min(max(set_prob, 1e-6), 1 - 1e-6)
    if best_of == 5:
        return s ** 3 * (1 + 3 * (1 - s) + 6 * (1 - s) ** 2)
    return s ** 2 * (3 - 2 * s)


@dataclass
class PointsResult:
    p1: float
    p2: float
    set_prob_p1: float
    best_of: int
    spw1: float
    spw2: float

    def as_match(self) -> dict[str, float]:
        return {"p1": self.p1, "p2": self.p2}


def predict_from_serve(spw1: float, spw2: float, best_of: int = 3) -> PointsResult:
    """spw1/spw2: each player's point-win-on-serve probability."""
    gA = game_win_prob(spw1)                 # p1 holds serve
    gB = game_win_prob(spw2)                 # p2 holds serve
    a = spw1                                  # p1 wins point on p1 serve
    b = 1 - spw2                              # p1 wins point on p2 serve
    set_p1 = _set_win_prob(gA, gB, a, b)
    m = match_win_prob(set_p1, best_of)
    return PointsResult(p1=m, p2=1 - m, set_prob_p1=set_p1, best_of=best_of,
                        spw1=spw1, spw2=spw2)


def predict_calibrated(target_p1: float, best_of: int = 3, base: float = BASE_SPW) -> PointsResult:
    """Calibrate symmetric serve edges so the model's match prob ~ target_p1,
    then return the full hierarchy (for coherent set-score output)."""
    lo, hi = -0.34, 0.34          # negative delta => p1 is the underdog
    target_p1 = min(max(target_p1, 0.02), 0.98)
    best = None
    for _ in range(40):
        delta = (lo + hi) / 2
        res = predict_from_serve(min(max(base + delta, 0.05), 0.95),
                                 min(max(base - delta, 0.05), 0.95), best_of)
        best = res
        if res.p1 < target_p1:
            lo = delta
        else:
            hi = delta
    return best
