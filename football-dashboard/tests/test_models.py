"""Unit tests for the probability models."""
import math

from models import elo, poisson, form, xg
from models.ensemble import combine, injury_adjustment


def _sum_to_one(dist):
    return math.isclose(sum(dist.values()), 1.0, abs_tol=1e-9)


# --- Elo ---------------------------------------------------------------------
def test_elo_probabilities_sum_to_one_and_favour_stronger():
    probs = elo.match_probabilities(1800, 1500)
    assert _sum_to_one(probs)
    assert probs["home"] > probs["away"]
    # with equal ratings + home advantage, home should still be favoured
    even = elo.match_probabilities(1500, 1500)
    assert even["home"] > even["away"]
    assert even["draw"] > 0


def test_elo_update_moves_ratings_correctly():
    h = elo.EloRating(elo=1500)
    a = elo.EloRating(elo=1500)
    nh, na = elo.update_ratings(h, a, 3, 0)  # big home win
    assert nh.elo > 1500
    assert na.elo < 1500
    assert math.isclose(nh.elo - 1500, 1500 - na.elo, abs_tol=1e-6)  # zero-sum


# --- Poisson -----------------------------------------------------------------
def test_poisson_distribution_valid():
    r = poisson.predict(1.6, 1.1)
    d = r.as_1x2()
    assert _sum_to_one(d)
    assert 0 < r.over25 < 1
    assert math.isclose(r.over25 + r.under25, 1.0, abs_tol=1e-6)
    assert r.home > r.away  # higher lambda_home => home favoured


def test_poisson_lambdas_in_range():
    lh, la = poisson.lambdas_from_strengths(2.2, 0.8, 0.9, 1.9)
    assert 0.1 <= lh <= 5.0 and 0.1 <= la <= 5.0
    assert lh > la  # strong attack + weak opponent defense


# --- Form --------------------------------------------------------------------
def _match(home_id, away_id, hg, ag, when):
    return {
        "id": hash((home_id, away_id, when)) & 0xFFFF,
        "kickoff_utc": when,
        "home_team_id": home_id, "away_team_id": away_id,
        "home_goals": hg, "away_goals": ag,
        "status": "FT",
    }


def test_form_summary_counts_results():
    team = 1
    matches = [
        _match(1, 2, 2, 0, "2026-01-01T00:00:00+00:00"),  # W
        _match(3, 1, 1, 1, "2026-01-08T00:00:00+00:00"),  # D (away)
        _match(1, 4, 0, 1, "2026-01-15T00:00:00+00:00"),  # L
    ]
    s = form.summarize(team, matches, window=5, venue="all")
    assert s.played == 3
    assert s.wins == 1 and s.draws == 1 and s.losses == 1
    assert s.points == 4
    assert s.form_string == "WDL"


def test_form_venue_split():
    team = 1
    matches = [
        _match(1, 2, 2, 0, "2026-01-01T00:00:00+00:00"),  # home
        _match(3, 1, 1, 1, "2026-01-08T00:00:00+00:00"),  # away
    ]
    home = form.summarize(team, matches, 5, "home")
    away = form.summarize(team, matches, 5, "away")
    assert home.played == 1 and away.played == 1


# --- xG fallback -------------------------------------------------------------
def test_xg_returns_none_when_missing():
    assert xg.predict_from_xg(None, 1.0, 1.2, 0.9) is None
    assert xg.predict_from_xg(1.5, 1.0, 1.2, 0.9) is not None


# --- Ensemble ----------------------------------------------------------------
def test_ensemble_renormalises_when_model_missing():
    components = {
        "elo": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "poisson": None,  # unavailable
        "form": {"home": 0.4, "draw": 0.3, "away": 0.3},
    }
    weights = {"elo": 0.25, "poisson": 0.30, "form": 0.15}
    res = combine(components, weights)
    assert _sum_to_one(res.probabilities)
    # only elo + form used; their weights renormalise to sum 1
    assert math.isclose(sum(res.weights_used.values()), 1.0, abs_tol=1e-6)
    assert "poisson" not in res.weights_used


def test_ensemble_all_missing_gives_uniform():
    res = combine({"elo": None}, {"elo": 1.0})
    assert math.isclose(res.probabilities["home"], 1 / 3, abs_tol=1e-9)


def test_injury_adjustment_none_when_no_data():
    assert injury_adjustment(None, None) is None
    adj = injury_adjustment(0.0, 0.5)  # away worse off helps home
    assert adj["home"] > 0 and adj["away"] < 0
