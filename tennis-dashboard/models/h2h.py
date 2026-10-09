"""Head-to-head model.

Converts a historical H2H record into a 2-way probability using a
Beta-smoothed win rate (so a 2-0 record doesn't imply 100%). Returns None when
there is no prior meeting, so the ensemble cleanly skips it rather than
inventing a signal.
"""
from __future__ import annotations


def h2h_probabilities(p1_wins: int | None, p2_wins: int | None,
                      prior: float = 2.0) -> dict[str, float] | None:
    if not p1_wins and not p2_wins:
        return None
    p1_wins = p1_wins or 0
    p2_wins = p2_wins or 0
    total = p1_wins + p2_wins
    if total == 0:
        return None
    # Beta(prior, prior) smoothing toward 0.5
    p1 = (p1_wins + prior) / (total + 2 * prior)
    return {"p1": p1, "p2": 1.0 - p1}
