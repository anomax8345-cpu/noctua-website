import math

from models import elo, points, form, h2h
from models.ensemble import combine


def _two(dist):
    return math.isclose(dist["p1"] + dist["p2"], 1.0, abs_tol=1e-9)


# --- Elo ---
def test_elo_win_prob_and_blend():
    assert math.isclose(elo.win_probability(1500, 1500), 0.5, abs_tol=1e-9)
    assert elo.win_probability(1700, 1500) > 0.5
    r = elo.PlayerRating(elo=1500, surface={"Clay": 1800})
    # on clay the blended rating is pulled up toward the clay rating
    assert r.blended("Clay") > 1500
    assert r.blended("Hard") == 1500   # no hard-specific rating -> overall


def test_elo_match_probabilities_sum_to_one():
    r1 = elo.PlayerRating(elo=1750)
    r2 = elo.PlayerRating(elo=1600)
    p = elo.match_probabilities(r1, r2, None)
    assert _two(p)
    assert p["p1"] > p["p2"]


def test_elo_update_surface_and_overall():
    r1 = elo.PlayerRating(elo=1500)
    r2 = elo.PlayerRating(elo=1500)
    n1, n2 = elo.update_ratings(r1, r2, "p1", "Clay")
    assert n1.elo > 1500 and n2.elo < 1500
    assert n1.surface["Clay"] > 1500 and n2.surface["Clay"] < 1500


# --- Points / serve model ---
def test_game_win_prob_monotone():
    assert points.game_win_prob(0.5) > 0.49
    assert points.game_win_prob(0.64) > points.game_win_prob(0.5)
    assert points.game_win_prob(0.8) > points.game_win_prob(0.64)
    # a 64% server should hold most of the time
    assert 0.78 < points.game_win_prob(0.64) < 0.95


def test_match_win_prob_bo5_more_decisive():
    s = 0.6
    assert points.match_win_prob(s, 3) > s          # better player favoured
    assert points.match_win_prob(s, 5) > points.match_win_prob(s, 3)


def test_predict_calibrated_hits_target():
    for target in (0.35, 0.5, 0.7, 0.85):
        res = points.predict_calibrated(target, best_of=3)
        assert abs(res.p1 - target) < 0.03
        assert math.isclose(res.p1 + res.p2, 1.0, abs_tol=1e-9)


# --- Form ---
def _m(p1, p2, winner, when, surface="Hard"):
    return {"id": f"{p1}{p2}{when}", "kickoff_utc": when, "p1_id": p1, "p2_id": p2,
            "winner": winner, "surface": surface}


def test_form_summary():
    s = form.summarize("A", [
        _m("A", "B", "p1", "2026-01-01T00:00:00+00:00"),
        _m("C", "A", "p1", "2026-01-05T00:00:00+00:00"),   # A lost (p1=C)
        _m("A", "D", "p1", "2026-01-09T00:00:00+00:00"),
    ], window=5)
    assert s.played == 3 and s.wins == 2 and s.losses == 1
    assert s.form_string == "WLW"


def test_form_surface_filter():
    s = form.summarize("A", [
        _m("A", "B", "p1", "2026-01-01T00:00:00+00:00", "Clay"),
        _m("A", "B", "p1", "2026-01-02T00:00:00+00:00", "Hard"),
    ], window=5, surface="Clay")
    assert s.played == 1


# --- H2H ---
def test_h2h_smoothing_and_none():
    assert h2h.h2h_probabilities(0, 0) is None
    p = h2h.h2h_probabilities(2, 0)
    assert 0.5 < p["p1"] < 1.0   # smoothed, not 100%


# --- Ensemble ---
def test_ensemble_renormalises_on_missing():
    res = combine({"elo_surface": {"p1": 0.6, "p2": 0.4}, "form": None,
                   "h2h": {"p1": 0.55, "p2": 0.45}},
                  {"elo_surface": 0.4, "form": 0.2, "h2h": 0.2})
    assert _two(res.probabilities)
    assert "form" not in res.weights_used
    assert math.isclose(sum(res.weights_used.values()), 1.0, abs_tol=1e-6)


def test_ensemble_all_missing_is_coinflip():
    res = combine({"elo_surface": None}, {"elo_surface": 1.0})
    assert res.probabilities == {"p1": 0.5, "p2": 0.5}
