"""Tests for team-name normalisation and market matching."""
from data.normalization import (
    extract_teams_from_question,
    normalize_name,
    score_match,
)


def test_normalize_aliases():
    assert normalize_name("BVB") == "borussia dortmund"
    assert normalize_name("Man United") == "manchester united"
    assert normalize_name("FC Bayern München") == "bayern munich"


def test_extract_teams_patterns():
    assert extract_teams_from_question("Dortmund vs Werder Bremen") == ["Dortmund", "Werder Bremen"]
    assert extract_teams_from_question("Will Arsenal beat Chelsea?") == ["Arsenal", "Chelsea"]
    assert extract_teams_from_question("Real Madrid - Barcelona: Over 2.5") == ["Real Madrid", "Barcelona"]
    assert extract_teams_from_question("Some unrelated question") == []


def test_high_confidence_match():
    res = score_match(
        "Borussia Dortmund", "Werder Bremen", ["Dortmund", "Werder Bremen"],
        fixture_kickoff="2026-10-09T18:30:00+00:00",
        market_time="2026-10-09T18:30:00+00:00",
    )
    assert res.is_confident
    assert res.confidence >= 0.9
    assert res.label in ("HIGH", "MEDIUM")


def test_low_confidence_wrong_teams_not_assigned():
    res = score_match(
        "Borussia Dortmund", "Werder Bremen", ["Real Madrid", "Barcelona"],
        fixture_kickoff="2026-10-09T18:30:00+00:00",
        market_time="2026-10-09T18:30:00+00:00",
    )
    assert not res.is_confident
    assert res.label == "LOW"


def test_swapped_order_still_matches():
    res = score_match(
        "Werder Bremen", "Borussia Dortmund", ["Dortmund", "Werder Bremen"],
    )
    assert res.confidence >= 0.8
