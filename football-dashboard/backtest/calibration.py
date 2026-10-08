"""Calibration reporting over stored predictions.

Reads settled predictions from the DB (`predictions` joined with
`prediction_results`) and produces probability-bucket calibration plus the
headline metrics, broken down optionally by league / probability range /
model version. This is what the "MODEL PERFORMANCE" dashboard page renders.
"""
from __future__ import annotations

from models.calibration import (
    brier_score,
    expected_calibration_error,
    log_loss,
    reliability_buckets,
)


def performance_from_results(rows: list[dict]) -> dict:
    """rows: dicts with keys predicted_prob (prob of actual outcome),
    top_pick_hit (0/1), top_pick_prob (prob of model pick), edge, confidence.
    """
    if not rows:
        return {
            "n": 0,
            "accuracy": None,
            "brier": None,
            "log_loss": None,
            "ece": None,
            "avg_edge": None,
            "avg_confidence": None,
            "buckets": [],
        }

    cal_pairs = [(r["top_pick_prob"], bool(r["top_pick_hit"])) for r in rows]
    actual_pairs = [(r["predicted_prob"], True) for r in rows]
    edges = [r["edge"] for r in rows if r.get("edge") is not None]
    confs = [r["confidence"] for r in rows if r.get("confidence") is not None]

    return {
        "n": len(rows),
        "accuracy": round(sum(1 for r in rows if r["top_pick_hit"]) / len(rows), 4),
        "brier": round(brier_score(actual_pairs), 4),
        "log_loss": round(log_loss(actual_pairs), 4),
        "ece": round(expected_calibration_error(cal_pairs), 4),
        "avg_edge": round(sum(edges) / len(edges), 2) if edges else None,
        "avg_confidence": round(sum(confs) / len(confs), 1) if confs else None,
        "buckets": [b.to_row() for b in reliability_buckets(cal_pairs) if b.n],
    }
