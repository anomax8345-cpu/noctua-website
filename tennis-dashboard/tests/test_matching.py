from data.normalization import (
    extract_players_from_question,
    normalize_name,
    score_match,
    surname,
)


def test_normalize_handles_initials_and_accents():
    assert normalize_name("Djokovic N.") == "djokovic"
    assert normalize_name("N. Djokovic") == "djokovic"
    assert normalize_name("Stefanos Tsitsipás") == "tsitsipas"


def test_surname_extraction():
    assert surname("Carlos Alcaraz") == "alcaraz"
    assert surname("Alcaraz C.") == "alcaraz"


def test_extract_players():
    assert extract_players_from_question("Alcaraz vs Sinner") == ["Alcaraz", "Sinner"]
    assert extract_players_from_question("Will Djokovic beat Medvedev?") == ["Djokovic", "Medvedev"]
    assert extract_players_from_question("Unrelated market") == []


def test_high_confidence_match():
    res = score_match("Carlos Alcaraz", "Jannik Sinner", ["Alcaraz C.", "Sinner J."],
                      fixture_kickoff="2026-10-09T12:00:00+00:00",
                      market_time="2026-10-09T12:00:00+00:00")
    assert res.is_confident and res.confidence >= 0.85


def test_low_confidence_wrong_players():
    res = score_match("Carlos Alcaraz", "Jannik Sinner", ["Novak Djokovic", "Daniil Medvedev"])
    assert not res.is_confident
    assert res.label == "LOW"


def test_swapped_order_matches():
    res = score_match("Jannik Sinner", "Carlos Alcaraz", ["Alcaraz C.", "Sinner J."])
    assert res.confidence >= 0.8
