"""Ensemble model (tennis, 2-way).

Weighted average of the component models' {p1, p2} distributions, with weights
renormalised over whichever components are available for the match. Records a
transparent per-component breakdown for the detail page.
"""
from __future__ import annotations

from dataclasses import dataclass, field

OUTCOMES = ("p1", "p2")


def _normalize(dist: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, dist.get(o, 0.0)) for o in OUTCOMES)
    if total <= 0:
        return {"p1": 0.5, "p2": 0.5}
    return {o: max(0.0, dist.get(o, 0.0)) / total for o in OUTCOMES}


@dataclass
class EnsembleResult:
    probabilities: dict[str, float]
    components: dict[str, dict] = field(default_factory=dict)
    weights_used: dict[str, float] = field(default_factory=dict)

    def top_pick(self) -> str:
        return "p1" if self.probabilities["p1"] >= self.probabilities["p2"] else "p2"


def combine(components: dict[str, dict[str, float] | None],
            weights: dict[str, float]) -> EnsembleResult:
    available = {k: _normalize(v) for k, v in components.items() if v is not None}
    if not available:
        return EnsembleResult(probabilities={"p1": 0.5, "p2": 0.5})

    w = {k: max(0.0, weights.get(k, 0.0)) for k in available}
    wsum = sum(w.values())
    if wsum <= 0:
        w = {k: 1.0 for k in available}
        wsum = float(len(available))
    w = {k: v / wsum for k, v in w.items()}

    blended = {o: 0.0 for o in OUTCOMES}
    for name, dist in available.items():
        for o in OUTCOMES:
            blended[o] += w[name] * dist[o]
    blended = _normalize(blended)
    return EnsembleResult(
        probabilities=blended,
        components={k: {o: round(v[o], 4) for o in OUTCOMES} for k, v in available.items()},
        weights_used={k: round(v, 4) for k, v in w.items()},
    )
