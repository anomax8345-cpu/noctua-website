"""Confidence score (0..100) for tennis.

Confidence is NOT the win probability — it expresses how reliable the data and
model are for this match. A match between two well-rated players on a known
surface with H2H history and a liquid market scores high; an obscure qualifier
with no surface rating, no H2H and a thin market scores low. Missing signals
contribute 0 (not a neutral guess).
"""
from __future__ import annotations

from dataclasses import dataclass

SIGNAL_WEIGHTS = {
    "both_rated": 0.18,      # both players have an established Elo
    "surface_known": 0.12,
    "surface_rated": 0.12,   # surface-specific rating exists for both
    "h2h_present": 0.10,
    "form_volume": 0.10,
    "calibration": 0.13,
    "sample": 0.08,
    "liquidity": 0.10,
    "spread": 0.05,
    "match_confidence": 0.02,
}


@dataclass
class ConfidenceInputs:
    p1_matches: int = 0
    p2_matches: int = 0
    surface_known: bool = False
    surface_rated: bool = False
    h2h_present: bool = False
    form_matches: int = 0
    calibration_quality: float | None = None
    historical_sample: int = 0
    market_liquidity_usd: float | None = None
    market_spread: float | None = None
    match_confidence: float | None = None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute(inp: ConfidenceInputs) -> tuple[int, dict[str, float]]:
    s: dict[str, float] = {}
    s["both_rated"] = _clamp01(min(inp.p1_matches, inp.p2_matches) / 20.0)
    s["surface_known"] = 1.0 if inp.surface_known else 0.0
    s["surface_rated"] = 1.0 if inp.surface_rated else 0.0
    s["h2h_present"] = 1.0 if inp.h2h_present else 0.0
    s["form_volume"] = _clamp01(inp.form_matches / 10.0)
    s["calibration"] = _clamp01(inp.calibration_quality) if inp.calibration_quality is not None else 0.4
    s["sample"] = _clamp01(inp.historical_sample / 200.0)
    s["liquidity"] = 0.0 if inp.market_liquidity_usd is None else _clamp01(inp.market_liquidity_usd / 5000.0)
    s["spread"] = 0.0 if inp.market_spread is None else _clamp01(1.0 - inp.market_spread / 0.10)
    s["match_confidence"] = _clamp01(inp.match_confidence) if inp.match_confidence is not None else 0.0

    score = sum(SIGNAL_WEIGHTS[k] * s[k] for k in SIGNAL_WEIGHTS)
    return round(score * 100), {k: round(v, 3) for k, v in s.items()}


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


def data_quality_label(both_matches: int, surface_rated: bool) -> str:
    if both_matches >= 15 and surface_rated:
        return "HIGH"
    if both_matches >= 8:
        return "MEDIUM"
    return "LOW"


def signal_quality(edge_pp: float, confidence: int, liquidity_usd: float | None,
                   spread: float | None) -> str:
    liq = liquidity_label(liquidity_usd)
    spr = spread_label(spread)
    if liq == "LOW" or spr == "HIGH" or confidence < 55:
        return "LOW"
    if edge_pp >= 5 and confidence >= 75 and liq == "HIGH" and spr == "LOW":
        return "HIGH"
    if edge_pp >= 3 and confidence >= 65:
        return "MEDIUM"
    return "LOW"
