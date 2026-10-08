"""Tests for calibration metrics and the confidence score."""
from models import calibration as cal
from models import confidence as conf


def test_brier_and_logloss_bounds():
    perfect = [(1.0, True), (1.0, True)]
    assert cal.brier_score(perfect) == 0.0
    worst = [(0.0, True)]
    assert cal.brier_score(worst) == 1.0
    assert cal.log_loss([(0.5, True)]) > 0


def test_reliability_and_ece():
    # Well-calibrated: 70% predictions win ~70% of the time.
    pairs = [(0.72, True)] * 7 + [(0.72, False)] * 3
    ece = cal.expected_calibration_error(pairs)
    assert ece is not None
    assert ece < 0.05  # predicted .72 vs actual .70 -> small error


def test_calibration_quality_mapping():
    assert cal.calibration_quality_from_ece(0.0) == 1.0
    assert cal.calibration_quality_from_ece(0.15) == 0.0
    assert cal.calibration_quality_from_ece(None) is None


def test_confidence_not_equal_to_probability():
    # Rich data, deep market -> high confidence.
    hi = conf.compute(conf.ConfidenceInputs(
        recent_matches=10, xg_present=True, lineups_present=True,
        injuries_present=True, calibration_quality=0.9, historical_sample=300,
        market_liquidity_usd=8000, market_spread=0.01, match_confidence=0.98,
    ))[0]
    # Thin data, no market -> low confidence, even if probability would be high.
    lo = conf.compute(conf.ConfidenceInputs(
        recent_matches=2, xg_present=False, lineups_present=False,
        injuries_present=False, calibration_quality=None, historical_sample=0,
        market_liquidity_usd=None, market_spread=None, match_confidence=None,
    ))[0]
    assert hi > lo
    assert hi >= 80
    assert lo <= 40


def test_signal_quality_caps_on_thin_market():
    # Same edge + confidence, but low liquidity must not be HIGH.
    good = conf.signal_quality(edge_pp=7, confidence=85, liquidity_usd=8000, spread=0.01)
    thin = conf.signal_quality(edge_pp=7, confidence=85, liquidity_usd=100, spread=0.08)
    assert good == "HIGH"
    assert thin == "LOW"


def test_labels():
    assert conf.liquidity_label(None) == "N/A"
    assert conf.liquidity_label(9000) == "HIGH"
    assert conf.spread_label(0.01) == "LOW"
    assert conf.data_quality_label(10, True) == "HIGH"
