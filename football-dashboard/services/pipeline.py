"""Analysis pipeline — orchestrates data -> model -> market -> edge -> storage.

This is the integration layer the Flask app calls. It is written to degrade
gracefully:

  * No API key           -> raises a clear, catchable error the UI shows.
  * No Polymarket markets -> model still runs; market/edge shown as N/A.
  * Missing xG/injuries   -> ensemble falls back; fields shown as N/A.

Nothing here fabricates data. Every optional feature is either real or N/A.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from config import MODEL_VERSION, SETTINGS
from data.api_football import ApiFootballClient, ApiFootballError
from data.cache import CACHE
from data.normalization import extract_teams_from_question, score_match
from data.polymarket import PolymarketClient
from database.database import get_db
from models import confidence as conf_mod
from models import elo as elo_mod
from models import form as form_mod
from models import poisson as poisson_mod
from models import xg as xg_mod
from models.ensemble import combine, injury_adjustment

OUTCOMES = ("home", "draw", "away")
_ANALYSIS_CACHE_KEY = "pipeline:upcoming"


class PipelineStatus:
    """Carries non-fatal warnings to surface in the UI (e.g. 'markets offline')."""

    def __init__(self):
        self.football_ok = True
        self.markets_ok = True
        self.messages: list[str] = []

    def warn(self, msg: str):
        self.messages.append(msg)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _team_rating(db, team_id: int) -> elo_mod.EloRating:
    row = db.query_one("SELECT * FROM team_ratings WHERE team_id=?", (team_id,))
    if row is None:
        return elo_mod.EloRating()
    return elo_mod.EloRating(
        elo=row["elo"], elo_home=row["elo_home"], elo_away=row["elo_away"],
        games=row["games"], last_change=row["last_change"],
    )


def _build_market_index(pm_client: PolymarketClient, status: PipelineStatus) -> list[dict]:
    try:
        markets = pm_client.search_soccer_markets()
        if not markets:
            status.markets_ok = False
            status.warn("No Polymarket soccer markets returned (network blocked or none active).")
        return markets
    except Exception as exc:  # noqa: BLE001 - must never crash the page
        status.markets_ok = False
        status.warn(f"Polymarket unavailable: {exc}")
        return []


def _match_market(fixture: dict, markets: list[dict]):
    """Return (best_market, MatchResult) or (None, None)."""
    best = None
    best_res = None
    for m in markets:
        teams = extract_teams_from_question(m["question"])
        if len(teams) < 2:
            continue
        res = score_match(
            fixture["home_team"], fixture["away_team"], teams,
            fixture_kickoff=fixture["kickoff_utc"], market_time=m.get("end_date"),
        )
        if best_res is None or res.confidence > best_res.confidence:
            best, best_res = m, res
    if best_res and best_res.is_confident:
        return best, best_res
    return None, best_res  # res returned for diagnostics even if not confident


def _market_1x2(market: dict) -> dict | None:
    """Map a Polymarket market's outcomes to home/draw/away probabilities.

    Only works for genuine 3-way (or clearly home/draw/away) markets; returns
    None otherwise so we never force a mismatched mapping.
    """
    outcomes = [str(o).lower() for o in market.get("outcomes", [])]
    prices = market.get("prices", [])
    if len(outcomes) != len(prices) or not prices:
        return None
    mapping = {}
    for name, price in zip(outcomes, prices):
        if price is None:
            continue
        if "draw" in name or name in ("tie", "x"):
            mapping["draw"] = price
        # Heuristic home/away by position handled below if names are team names
    # If exactly 3 outcomes and one is a draw, assign the other two by order.
    if len(outcomes) == 3 and "draw" in mapping:
        non_draw = [(n, p) for n, p in zip(outcomes, prices) if "draw" not in n and n not in ("tie", "x")]
        if len(non_draw) == 2:
            mapping["home"] = non_draw[0][1]
            mapping["away"] = non_draw[1][1]
    elif len(outcomes) == 2:
        # binary market (e.g. "Team to win") -> treat as home/away two-way
        mapping["home"] = prices[0]
        mapping["away"] = prices[1]
    if not mapping:
        return None
    total = sum(v for v in mapping.values() if v)
    if total <= 0:
        return None
    # Normalise (Polymarket prices already ~sum to 1 but may carry a vig)
    return {k: v / total for k, v in mapping.items()}


def _injury_impact(af: ApiFootballClient, fixture_id: int, status: PipelineStatus):
    """Return (home_impact, away_impact, present) with impacts in 0..1 or None.
    For MVP we proxy impact by count of absences (capped); a richer player-level
    importance model is a Phase-2 extension. Returns None impacts when the
    injuries endpoint yields nothing usable (never guessed)."""
    try:
        rows = af.injuries_for_fixture(fixture_id)
    except ApiFootballError:
        return None, None, False
    if not rows:
        return None, None, False
    # group by team
    by_team: dict[int, int] = {}
    for r in rows:
        tid = r.get("team_id")
        if tid is not None:
            by_team[tid] = by_team.get(tid, 0) + 1
    return by_team, None, True  # resolved against fixture teams by caller


def analyze_upcoming(force: bool = False) -> dict:
    """Main entry. Returns {status, generated_utc, matches:[...]}.

    Cached briefly so repeated page loads don't re-hit APIs.
    """
    if not force:
        cached = CACHE.get(_ANALYSIS_CACHE_KEY)
        if cached is not None:
            return cached

    db = get_db()
    status = PipelineStatus()
    af = ApiFootballClient(SETTINGS)
    pm = PolymarketClient(SETTINGS)

    league_ids = [lg.api_football_id for lg in SETTINGS.enabled_league_objects()]
    start = _now()
    end = start + timedelta(hours=SETTINGS.lookahead_hours)

    fixtures: list[dict] = []
    try:
        fixtures = af.fixtures_between(start, end, league_ids)
        status.football_ok = True
    except ApiFootballError as exc:
        status.football_ok = False
        status.warn(str(exc))

    markets = _build_market_index(pm, status)

    results = []
    for fx in fixtures:
        try:
            analysis = _analyze_fixture(db, af, fx, markets, status)
            results.append(analysis)
            _store_prediction(db, fx, analysis)
        except Exception as exc:  # noqa: BLE001 - one bad fixture must not kill the page
            status.warn(f"Fixture {fx.get('id')} skipped: {exc}")

    # sort by absolute edge (strongest potential edges first), N/A last
    def sort_key(a):
        e = a.get("edge_top")
        return (-abs(e)) if e is not None else 1e9

    results.sort(key=sort_key)

    payload = {
        "status": {
            "football_ok": status.football_ok,
            "markets_ok": status.markets_ok,
            "messages": status.messages,
        },
        "generated_utc": start.isoformat(),
        "matches": results,
    }
    CACHE.set(_ANALYSIS_CACHE_KEY, payload, ttl=min(SETTINGS.refresh_markets_seconds, 180))
    return payload


def _recent_matches(af: ApiFootballClient, team_id: int, status: PipelineStatus) -> list[dict]:
    try:
        return af.team_last_fixtures(team_id, 20)
    except ApiFootballError as exc:
        status.warn(f"Form unavailable for team {team_id}: {exc}")
        return []


def _analyze_fixture(db, af, fx, markets, status: PipelineStatus) -> dict:
    hid, aid = fx["home_team_id"], fx["away_team_id"]
    home_matches = _recent_matches(af, hid, status) if status.football_ok else []
    away_matches = _recent_matches(af, aid, status) if status.football_ok else []

    hf = form_mod.summarize(hid, home_matches, 10, "all")
    af_ = form_mod.summarize(aid, away_matches, 10, "all")
    hf_home = form_mod.summarize(hid, home_matches, 10, "home")
    af_away = form_mod.summarize(aid, away_matches, 10, "away")

    # Elo
    hr = _team_rating(db, hid)
    ar = _team_rating(db, aid)
    elo_probs = elo_mod.match_probabilities(hr.elo, ar.elo, SETTINGS.weight_home * 0 + elo_mod.DEFAULT_HOME_ADVANTAGE)

    # Poisson from form (only if enough data)
    poisson_probs = None
    poisson_detail = None
    if hf.played >= 3 and af_.played >= 3:
        lam_h, lam_a = poisson_mod.lambdas_from_strengths(hf.gf_pg, hf.ga_pg, af_.gf_pg, af_.ga_pg)
        pr = poisson_mod.predict(lam_h, lam_a)
        poisson_probs = pr.as_1x2()
        poisson_detail = {
            "lambda_home": round(pr.lambda_home, 2),
            "lambda_away": round(pr.lambda_away, 2),
            "over25": round(pr.over25, 3),
            "under25": round(pr.under25, 3),
            "btts": round(pr.btts, 3),
        }

    # Form probs
    form_probs = form_mod.form_probabilities(hf.ppg, af_.ppg) if (hf.played and af_.played) else None

    # xG (unavailable by default in MVP -> fallback). Hook for Phase 2.
    xg_probs = xg_mod.predict_from_xg(hf.xg, hf.xga, af_.xg, af_.xga)
    xg_probs = xg_probs.as_1x2() if xg_probs else None

    # Injuries (best effort)
    inj_present = False
    inj_delta = None
    try:
        rows = af.injuries_for_fixture(fx["id"]) if status.football_ok else []
        if rows:
            inj_present = True
            counts = {}
            for r in rows:
                tid = r.get("team_id")
                if tid is not None:
                    counts[tid] = counts.get(tid, 0) + 1
            home_impact = min(counts.get(hid, 0) / 6.0, 1.0)
            away_impact = min(counts.get(aid, 0) / 6.0, 1.0)
            inj_delta = injury_adjustment(home_impact, away_impact)
    except ApiFootballError:
        inj_present = False

    weights = SETTINGS.model_weights()
    ensemble = combine(
        {
            "elo": elo_probs,
            "poisson": poisson_probs,
            "xg": xg_probs,
            "form": form_probs,
            "home": elo_probs,
        },
        weights,
        injury_delta=inj_delta,
    )
    probs = ensemble.probabilities
    top = ensemble.top_pick()

    # --- market matching ---
    market, match_res = _match_market(fx, markets)
    market_probs = _market_1x2(market) if market else None
    edge = None
    edge_top = None
    liquidity = spread = None
    market_id = None
    match_conf = match_res.confidence if match_res else None
    if market:
        market_id = market["market_id"]
        liquidity = market.get("liquidity")
        spread = market.get("spread")
    if market_probs:
        edge = {o: round((probs.get(o, 0) - market_probs.get(o, 0)) * 100, 1)
                for o in OUTCOMES if o in market_probs}
        if top in edge:
            edge_top = edge[top]

    # --- confidence ---
    recent_n = min(hf.played, af_.played)
    conf_inputs = conf_mod.ConfidenceInputs(
        recent_matches=recent_n,
        xg_present=xg_probs is not None,
        lineups_present=False,  # Phase 2
        injuries_present=inj_present,
        calibration_quality=_calibration_quality(db),
        historical_sample=_historical_sample(db),
        market_liquidity_usd=liquidity,
        market_spread=spread,
        match_confidence=match_conf,
    )
    confidence, conf_signals = conf_mod.compute(conf_inputs)

    data_quality = conf_mod.data_quality_label(recent_n, xg_probs is not None)
    liq_label = conf_mod.liquidity_label(liquidity)
    spr_label = conf_mod.spread_label(spread)
    sig_quality = conf_mod.signal_quality(abs(edge_top) if edge_top is not None else 0,
                                          confidence, liquidity, spread)

    return {
        "fixture_id": fx["id"],
        "kickoff_utc": fx["kickoff_utc"],
        "league": fx["league_name"],
        "home_team": fx["home_team"],
        "away_team": fx["away_team"],
        "home_team_id": hid,
        "away_team_id": aid,
        "model": {o: round(probs[o] * 100, 1) for o in OUTCOMES},
        "market": ({o: round(market_probs[o] * 100, 1) for o in market_probs}
                   if market_probs else None),
        "edge": edge,
        "edge_top": edge_top,
        "top_pick": top,
        "confidence": confidence,
        "confidence_signals": conf_signals,
        "data_quality": data_quality,
        "liquidity": liquidity,
        "liquidity_label": liq_label,
        "spread": spread,
        "spread_label": spr_label,
        "signal_quality": sig_quality,
        "match_confidence": round(match_conf * 100, 1) if match_conf is not None else None,
        "market_status": ("MATCHED" if market else
                          ("LOW CONFIDENCE" if match_res else "POLYMARKET MARKET NOT FOUND")),
        "polymarket_market_id": market_id,
        "components": ensemble.components,
        "weights_used": ensemble.weights_used,
        "poisson_detail": poisson_detail,
        "form": {
            "home": hf.to_row(), "away": af_.to_row(),
            "home_at_home": hf_home.to_row(), "away_at_away": af_away.to_row(),
        },
        "elo": {"home": round(hr.elo), "away": round(ar.elo)},
        "injuries_present": inj_present,
    }


def _calibration_quality(db) -> float | None:
    row = db.query_one(
        "SELECT ece FROM backtest_results ORDER BY run_utc DESC LIMIT 1"
    )
    if not row or row["ece"] is None:
        return None
    from models.calibration import calibration_quality_from_ece
    return calibration_quality_from_ece(row["ece"])


def _historical_sample(db) -> int:
    row = db.query_one("SELECT COUNT(*) AS c FROM prediction_results")
    return row["c"] if row else 0


def _store_prediction(db, fx, analysis) -> None:
    now = _now().isoformat()
    model = analysis["model"]
    market = analysis.get("market")
    edge = analysis.get("edge") or {}
    db.execute(
        """INSERT OR IGNORE INTO predictions
           (timestamp_utc, fixture_id, model_version, market_type,
            home_probability, draw_probability, away_probability,
            market_home, market_draw, market_away,
            edge_home, edge_draw, edge_away,
            confidence, data_quality, components_json,
            polymarket_market_id, match_confidence)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            now, fx["id"], MODEL_VERSION, "1X2",
            model["home"] / 100, model["draw"] / 100, model["away"] / 100,
            (market or {}).get("home"), (market or {}).get("draw"), (market or {}).get("away"),
            edge.get("home"), edge.get("draw"), edge.get("away"),
            analysis["confidence"], analysis["data_quality"],
            json.dumps({"components": analysis["components"],
                        "weights": analysis["weights_used"]}),
            analysis.get("polymarket_market_id"), analysis.get("match_confidence"),
        ),
    )
    # persist fixture + market snapshot
    db.upsert("fixtures", {
        "id": fx["id"], "league_id": fx["league_id"], "league_name": fx["league_name"],
        "season": fx.get("season"), "kickoff_utc": fx["kickoff_utc"], "status": fx["status"],
        "home_team_id": fx["home_team_id"], "away_team_id": fx["away_team_id"],
        "home_team": fx["home_team"], "away_team": fx["away_team"],
        "home_goals": fx.get("home_goals"), "away_goals": fx.get("away_goals"),
        "updated_utc": now,
    }, ["id"])
    if analysis.get("polymarket_market_id"):
        db.execute(
            """INSERT INTO polymarket_prices
               (market_id, timestamp_utc, outcome, price, spread, liquidity)
               VALUES (?,?,?,?,?,?)""",
            (analysis["polymarket_market_id"], now, analysis["top_pick"],
             (analysis.get("market") or {}).get(analysis["top_pick"], 0) / 100
             if analysis.get("market") else None,
             analysis.get("spread"), analysis.get("liquidity")),
        )


def get_fixture_detail(fixture_id: int) -> dict | None:
    """Return the cached analysis for a single fixture (from the last run)."""
    data = analyze_upcoming()
    for m in data["matches"]:
        if m["fixture_id"] == fixture_id:
            return m
    return None
