"""Ensemble model.

Combines the 1X2 distributions of the component models into one final
distribution. The combination is a weighted average of probabilities with the
weights **renormalised over whichever components are actually available** for a
given match — so a missing xG model does not blank out the prediction, it just
shifts weight to the remaining models.

The ensemble also records a transparent per-component breakdown so the match
detail page can explain *why* the model arrived at its number.

An optional injury adjustment nudges probabilities when key players are known
to be missing. It is applied only when injury data exists; otherwise it is a
no-op (never guessed).
"""
from __future__ import annotations

from dataclasses import dataclass, field

OUTCOMES = ("home", "draw", "away")


def _normalize(dist: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, dist.get(o, 0.0)) for o in OUTCOMES)
    if total <= 0:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    return {o: max(0.0, dist.get(o, 0.0)) / total for o in OUTCOMES}


@dataclass
class EnsembleResult:
    probabilities: dict[str, float]
    components: dict[str, dict] = field(default_factory=dict)
    weights_used: dict[str, float] = field(default_factory=dict)
    injury_adjustment: dict[str, float] | None = None

    def top_pick(self) -> str:
        return max(OUTCOMES, key=lambda o: self.probabilities[o])


def combine(
    components: dict[str, dict[str, float] | None],
    weights: dict[str, float],
    injury_delta: dict[str, float] | None = None,
) -> EnsembleResult:
    """components: {name: 1X2-dict or None}. weights: {name: weight}.

    Only components present (non-None) contribute; their weights are
    renormalised to sum to 1.
    """
    available = {k: _normalize(v) for k, v in components.items() if v is not None}
    if not available:
        probs = {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
        return EnsembleResult(probabilities=probs, components={}, weights_used={})

    w = {k: max(0.0, weights.get(k, 0.0)) for k in available}
    wsum = sum(w.values())
    if wsum <= 0:
        # equal weighting fallback
        w = {k: 1.0 for k in available}
        wsum = float(len(available))
    w = {k: v / wsum for k, v in w.items()}

    blended = {o: 0.0 for o in OUTCOMES}
    for name, dist in available.items():
        for o in OUTCOMES:
            blended[o] += w[name] * dist[o]

    adjustment = None
    if injury_delta:
        for o in OUTCOMES:
            blended[o] = max(0.0, blended[o] + injury_delta.get(o, 0.0))
        adjustment = injury_delta

    blended = _normalize(blended)
    return EnsembleResult(
        probabilities=blended,
        components={k: {o: round(v[o], 4) for o in OUTCOMES} for k, v in available.items()},
        weights_used={k: round(v, 4) for k, v in w.items()},
        injury_adjustment=adjustment,
    )


def injury_adjustment(
    home_impact: float | None, away_impact: float | None, scale: float = 0.08
) -> dict[str, float] | None:
    """Translate 'impact of missing players' (0..1 each, higher = worse) into a
    small probability shift. Returns None when BOTH sides have no data, so the
    ensemble applies nothing rather than guessing.

    If one side has data and the other does not, the unknown side is treated as
    0 impact (conservative) and we still apply the known side's effect.
    """
    if home_impact is None and away_impact is None:
        return None
    hi = home_impact or 0.0
    ai = away_impact or 0.0
    net = (ai - hi) * scale  # away worse off -> helps home
    return {"home": net, "draw": 0.0, "away": -net}
