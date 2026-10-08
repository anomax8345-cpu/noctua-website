"""Confidence score (0..100).

IMPORTANT: confidence is NOT the win probability. It expresses how reliable the
data and model are *for this specific match*. A 74% pick on a well-covered
Bundesliga game with deep market liquidity should score high; the same 74% on
an obscure league with no xG, no lineups and a thin market should score low.

The score is a weighted sum of component signals, each in [0,1]. Signals whose
data is absent contribute 0 (not a neutral guess), which correctly drags
confidence down when we are flying blind.
"""
from __future__ import annotations

from dataclasses import dataclass

# weights sum to 1.0
SIGNAL_WEIGHTS = {
    "data_volume": 0.18,     # how many recent matches we have
    "xg_present": 0.12,
    "lineups_present": 0.10,
    "injuries_present": 0.10,
    "calibration": 0.15,     # historical calibration quality for this bucket
    "sample": 0.10,          # historical sample size for similar predictions
    "liquidity": 0.12,
    "spread": 0.08,
    "match_confidence": 0.05,
}


@dataclass
class ConfidenceInputs:
    recent_matches: int = 0           # count of recent finished matches available
    xg_present: bool = False
    lineups_present: bool = False
    injuries_present: bool = False
    calibration_quality: float | None = None   # 0..1, None if unknown
    historical_sample: int = 0        # how many past predictions in this bucket
    market_liquidity_usd: float | None = None
    market_spread: float | None = None
    match_confidence: float | None = None       # 0..1 from name matching


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute(inp: ConfidenceInputs) -> tuple[int, dict[str, float]]:
    signals: dict[str, float] = {}

    # data volume: 0 at 0 matches, saturates ~ 10 matches
    signals["data_volume"] = _clamp01(inp.recent_matches / 10.0)
    signals["xg_present"] = 1.0 if inp.xg_present else 0.0
    signals["lineups_present"] = 1.0 if inp.lineups_present else 0.0
    signals["injuries_present"] = 1.0 if inp.injuries_present else 0.0

    # calibration: unknown -> 0.4 (mild penalty, not zero, not full trust)
    signals["calibration"] = (
        _clamp01(inp.calibration_quality) if inp.calibration_quality is not None else 0.4
    )
    # historical sample saturates ~ 200 past predictions
    signals["sample"] = _clamp01(inp.historical_sample / 200.0)

    # liquidity: 0 if no market; saturates ~ $5000
    if inp.market_liquidity_usd is None:
        signals["liquidity"] = 0.0
    else:
        signals["liquidity"] = _clamp01(inp.market_liquidity_usd / 5000.0)

    # spread: lower is better. None -> 0. 0 spread -> 1, >=0.10 -> 0
    if inp.market_spread is None:
        signals["spread"] = 0.0
    else:
        signals["spread"] = _clamp01(1.0 - inp.market_spread / 0.10)

    signals["match_confidence"] = (
        _clamp01(inp.match_confidence) if inp.match_confidence is not None else 0.0
    )

    score = sum(SIGNAL_WEIGHTS[k] * signals[k] for k in SIGNAL_WEIGHTS)
    return round(score * 100), {k: round(v, 3) for k, v in signals.items()}


def liquidity_label(liquidity_usd: float | None) -> str:
    if liquidity_usd is None:
        return "N/A"
    if liquidity_usd >= 5000:
        return "HIGH"
    if liquidity_usd >= 1000:
        return "MEDIUM"
    return "LOW"


def spread_label(spread: float | None) -> str:
    if spread is None:
        return "N/A"
    if spread <= 0.02:
        return "LOW"
    if spread <= 0.05:
        return "MEDIUM"
    return "HIGH"


def data_quality_label(recent_matches: int, xg_present: bool) -> str:
    if recent_matches >= 8 and xg_present:
        return "HIGH"
    if recent_matches >= 5:
        return "MEDIUM"
    return "LOW"


def signal_quality(edge_pp: float, confidence: int, liquidity_usd: float | None,
                   spread: float | None) -> str:
    """Combine edge + confidence + market health into a single HIGH/MEDIUM/LOW
    label. This deliberately refuses to call something a good signal on edge
    alone — thin/illiquid markets cap the rating."""
    liq = liquidity_label(liquidity_usd)
    spr = spread_label(spread)
    if liq == "LOW" or spr == "HIGH" or confidence < 55:
        base = "LOW"
    elif edge_pp >= 5 and confidence >= 75 and liq == "HIGH" and spr == "LOW":
        base = "HIGH"
    elif edge_pp >= 3 and confidence >= 65:
        base = "MEDIUM"
    else:
        base = "LOW"
    return base
