"""Calibration reporting over stored tennis predictions (binary)."""
from __future__ import annotations

from models.calibration import (
    brier_score,
    expected_calibration_error,
    log_loss,
    reliability_buckets,
)


def performance_from_results(rows: list[dict]) -> dict:
    """rows: dicts with pick_prob (prob of model pick), pick_hit (0/1),
    edge, confidence."""
    if not rows:
        return {"n": 0, "accuracy": None, "brier": None, "log_loss": None,
                "ece": None, "avg_edge": None, "avg_confidence": None, "buckets": []}

    cal_pairs = [(r["pick_prob"], bool(r["pick_hit"])) for r in rows]
    edges = [r["edge"] for r in rows if r.get("edge") is not None]
    confs = [r["confidence"] for r in rows if r.get("confidence") is not None]
    return {
        "n": len(rows),
        "accuracy": round(sum(1 for r in rows if r["pick_hit"]) / len(rows), 4),
        "brier": round(brier_score(cal_pairs), 4),
        "log_loss": round(log_loss(cal_pairs), 4),
        "ece": round(expected_calibration_error(cal_pairs), 4),
        "avg_edge": round(sum(edges) / len(edges), 2) if edges else None,
        "avg_confidence": round(sum(confs) / len(confs), 1) if confs else None,
        "buckets": [b.to_row() for b in reliability_buckets(cal_pairs) if b.n],
    }
