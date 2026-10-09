"""Calibration metrics (Brier, Log loss, reliability buckets, ECE).

Operates on (predicted_probability, outcome_bool) pairs. Tennis is binary so
this is a natural fit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_BINS = [
    (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75),
    (0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 0.95), (0.95, 1.01),
]


def brier_score(pairs: list[tuple[float, bool]]) -> float | None:
    if not pairs:
        return None
    return sum((p - (1.0 if hit else 0.0)) ** 2 for p, hit in pairs) / len(pairs)


def log_loss(pairs: list[tuple[float, bool]], eps: float = 1e-12) -> float | None:
    if not pairs:
        return None
    total = 0.0
    for p, hit in pairs:
        p = min(max(p, eps), 1 - eps)
        total += -(math.log(p) if hit else math.log(1 - p))
    return total / len(pairs)


@dataclass
class Bucket:
    lo: float
    hi: float
    n: int = 0
    predicted_sum: float = 0.0
    hits: int = 0

    @property
    def predicted_rate(self) -> float | None:
        return self.predicted_sum / self.n if self.n else None

    @property
    def actual_rate(self) -> float | None:
        return self.hits / self.n if self.n else None

    def to_row(self) -> dict:
        return {
            "range": f"{int(self.lo*100)}-{int(min(self.hi,1.0)*100)}%",
            "n": self.n,
            "predicted": round(self.predicted_rate * 100, 1) if self.predicted_rate else None,
            "actual": round(self.actual_rate * 100, 1) if self.actual_rate else None,
        }


def reliability_buckets(pairs: list[tuple[float, bool]], bins=DEFAULT_BINS) -> list[Bucket]:
    buckets = [Bucket(lo, hi) for lo, hi in bins]
    for p, hit in pairs:
        for b in buckets:
            if b.lo <= p < b.hi:
                b.n += 1
                b.predicted_sum += p
                b.hits += 1 if hit else 0
                break
    return buckets


def expected_calibration_error(pairs: list[tuple[float, bool]], bins=DEFAULT_BINS) -> float | None:
    if not pairs:
        return None
    buckets = reliability_buckets(pairs, bins)
    n = len(pairs)
    ece = 0.0
    for b in buckets:
        if b.n and b.predicted_rate is not None and b.actual_rate is not None:
            ece += (b.n / n) * abs(b.predicted_rate - b.actual_rate)
    return ece


def calibration_quality_from_ece(ece: float | None) -> float | None:
    if ece is None:
        return None
    return max(0.0, 1.0 - ece / 0.15)
