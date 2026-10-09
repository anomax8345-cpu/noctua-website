from models import calibration as cal
from models import confidence as conf


def test_brier_logloss():
    assert cal.brier_score([(1.0, True)]) == 0.0
    assert cal.brier_score([(0.0, True)]) == 1.0
    assert cal.log_loss([(0.5, True)]) > 0


def test_ece_small_when_calibrated():
    pairs = [(0.72, True)] * 7 + [(0.72, False)] * 3
    assert cal.expected_calibration_error(pairs) < 0.05


def test_confidence_reflects_data_not_probability():
    hi = conf.compute(conf.ConfidenceInputs(
        p1_matches=40, p2_matches=40, surface_known=True, surface_rated=True,
        h2h_present=True, form_matches=12, calibration_quality=0.9,
        historical_sample=300, market_liquidity_usd=9000, market_spread=0.01,
        match_confidence=0.98))[0]
    lo = conf.compute(conf.ConfidenceInputs(
        p1_matches=1, p2_matches=0, surface_known=False, surface_rated=False,
        h2h_present=False, form_matches=0, calibration_quality=None,
        historical_sample=0, market_liquidity_usd=None, market_spread=None,
        match_confidence=None))[0]
    assert hi > lo and hi >= 80 and lo <= 40


def test_signal_quality_caps_on_thin_market():
    assert conf.signal_quality(7, 85, 9000, 0.01) == "HIGH"
    assert conf.signal_quality(7, 85, 100, 0.08) == "LOW"


def test_labels():
    assert conf.liquidity_label(None) == "N/A"
    assert conf.spread_label(0.01) == "LOW"
    assert conf.data_quality_label(20, True) == "HIGH"
