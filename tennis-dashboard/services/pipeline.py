"""Analysis pipeline (tennis): data -> model -> market -> edge -> storage.

Degrades gracefully: no key -> clear error shown; no markets -> model still
runs, market/edge N/A; missing surface/H2H -> ensemble falls back. Never
fabricates data.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from config import MODEL_VERSION, SETTINGS
from data.api_tennis import ApiTennisClient, ApiTennisError
from data.cache import CACHE
from data.normalization import extract_players_from_question, score_match
from data.polymarket import PolymarketClient
from database.database import get_db
from models import confidence as conf_mod
from models import elo as elo_mod
from models import form as form_mod
from models import h2h as h2h_mod
from models import points as points_mod
from models.ensemble import combine

OUTCOMES = ("p1", "p2")
_ANALYSIS_CACHE_KEY = "pipeline:tennis:upcoming"


class PipelineStatus:
    def __init__(self):
        self.tennis_ok = True
        self.markets_ok = True
        self.messages: list[str] = []

    def warn(self, msg: str):
        self.messages.append(msg)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _player_rating(db, player_id: str) -> elo_mod.PlayerRating:
    row = db.query_one("SELECT * FROM player_ratings WHERE player_id=?", (player_id,))
    if row is None:
        return elo_mod.PlayerRating()
    try:
        surface = json.loads(row["elo_surface_json"] or "{}")
    except (TypeError, ValueError):
        surface = {}
    return elo_mod.PlayerRating(elo=row["elo"], surface=surface, matches=row["matches"],
                                last_change=row["last_change"])


def _build_market_index(pm: PolymarketClient, status: PipelineStatus) -> list[dict]:
    try:
        markets = pm.search_tennis_markets()
        if not markets:
            status.markets_ok = False
            status.warn("No Polymarket tennis markets returned (network blocked or none active).")
        return markets
    except Exception as exc:  # noqa: BLE001
        status.markets_ok = False
        status.warn(f"Polymarket unavailable: {exc}")
        return []


def _match_market(fx: dict, markets: list[dict]):
    best = None
    best_res = None
    for m in markets:
        players = extract_players_from_question(m["question"])
        if len(players) < 2:
            continue
        res = score_match(fx["p1_name"], fx["p2_name"], players,
                          fixture_kickoff=fx["kickoff_utc"], market_time=m.get("end_date"))
        if best_res is None or res.confidence > best_res.confidence:
            best, best_res = m, res
    if best_res and best_res.is_confident:
        return best, best_res
    return None, best_res


def _market_2way(market: dict) -> dict | None:
    """Map a 2-outcome market to {p1, p2} by outcome order (normalised)."""
    outcomes = market.get("outcomes", [])
    prices = market.get("prices", [])
    if len(outcomes) != 2 or len(prices) != 2 or any(p is None for p in prices):
        return None
    total = sum(prices)
    if total <= 0:
        return None
    return {"p1": prices[0] / total, "p2": prices[1] / total}


def analyze_upcoming(force: bool = False) -> dict:
    if not force:
        cached = CACHE.get(_ANALYSIS_CACHE_KEY)
        if cached is not None:
            return cached

    db = get_db()
    status = PipelineStatus()
    at = ApiTennisClient(SETTINGS)
    pm = PolymarketClient(SETTINGS)

    start = _now()
    end = start + timedelta(hours=SETTINGS.lookahead_hours)

    fixtures: list[dict] = []
    try:
        for fx in at.fixtures_between(start, end):
            if fx["winner"] is None and SETTINGS.tour_enabled(fx["tour"]):
                fixtures.append(fx)
        status.tennis_ok = True
    except ApiTennisError as exc:
        status.tennis_ok = False
        status.warn(str(exc))

    markets = _build_market_index(pm, status)

    results = []
    for fx in fixtures:
        try:
            analysis = _analyze_fixture(db, at, fx, markets, status)
            results.append(analysis)
            _store_prediction(db, fx, analysis)
        except Exception as exc:  # noqa: BLE001
            status.warn(f"Fixture {fx.get('id')} skipped: {exc}")

    def sort_key(a):
        e = a.get("edge_top")
        return (-abs(e)) if e is not None else 1e9

    results.sort(key=sort_key)

    payload = {
        "status": {"tennis_ok": status.tennis_ok, "markets_ok": status.markets_ok,
                   "messages": status.messages},
        "generated_utc": start.isoformat(),
        "matches": results,
    }
    CACHE.set(_ANALYSIS_CACHE_KEY, payload, ttl=min(SETTINGS.refresh_markets_seconds, 180))
    return payload


def _player_recent(at: ApiTennisClient, player_id: str, status: PipelineStatus) -> list[dict]:
    try:
        end = _now()
        start = end - timedelta(days=120)
        return at.player_recent(player_id, start, end)
    except ApiTennisError as exc:
        status.warn(f"Form unavailable for player {player_id}: {exc}")
        return []


def _analyze_fixture(db, at, fx, markets, status: PipelineStatus) -> dict:
    p1, p2 = fx["p1_id"], fx["p2_id"]
    surface = fx.get("surface")

    r1 = _player_rating(db, p1)
    r2 = _player_rating(db, p2)
    elo_probs = elo_mod.match_probabilities(r1, r2, surface)

    recent1 = _player_recent(at, p1, status) if status.tennis_ok else []
    recent2 = _player_recent(at, p2, status) if status.tennis_ok else []
    f1 = form_mod.summarize(p1, recent1, 15)
    f2 = form_mod.summarize(p2, recent2, 15)
    f1_surf = form_mod.summarize(p1, recent1, 15, surface) if surface else f1
    f2_surf = form_mod.summarize(p2, recent2, 15, surface) if surface else f2
    form_probs = (form_mod.form_probabilities(f1.win_pct, f2.win_pct)
                  if f1.played >= 3 and f2.played >= 3 else None)

    # H2H
    h2h_probs = None
    h2h_present = False
    h2h_rec = None
    if status.tennis_ok:
        try:
            h2h_rec = at.h2h(p1, p2)
        except ApiTennisError:
            h2h_rec = None
    if h2h_rec:
        h2h_present = True
        h2h_probs = h2h_mod.h2h_probabilities(h2h_rec["p1_wins"], h2h_rec["p2_wins"])

    # Points model calibrated to Elo match prob -> coherent set distribution
    points_res = points_mod.predict_calibrated(elo_probs["p1"], best_of=fx.get("best_of", 3))
    points_probs = points_res.as_match()

    ensemble = combine(
        {"elo_surface": elo_probs, "points": points_probs,
         "form": form_probs, "h2h": h2h_probs},
        SETTINGS.model_weights(),
    )
    probs = ensemble.probabilities
    top = ensemble.top_pick()

    market, match_res = _match_market(fx, markets)
    market_probs = _market_2way(market) if market else None
    edge = edge_top = None
    liquidity = spread = market_id = None
    match_conf = match_res.confidence if match_res else None
    if market:
        market_id = market["market_id"]
        liquidity = market.get("liquidity")
        spread = market.get("spread")
    if market_probs:
        edge = {o: round((probs[o] - market_probs[o]) * 100, 1) for o in OUTCOMES}
        edge_top = edge[top]

    surface_rated = bool(surface and surface in r1.surface and surface in r2.surface)
    conf_inputs = conf_mod.ConfidenceInputs(
        p1_matches=r1.matches, p2_matches=r2.matches,
        surface_known=bool(surface), surface_rated=surface_rated,
        h2h_present=h2h_present, form_matches=min(f1.played, f2.played),
        calibration_quality=_calibration_quality(db),
        historical_sample=_historical_sample(db),
        market_liquidity_usd=liquidity, market_spread=spread,
        match_confidence=match_conf,
    )
    confidence, conf_signals = conf_mod.compute(conf_inputs)
    data_quality = conf_mod.data_quality_label(min(r1.matches, r2.matches), surface_rated)
    sig_quality = conf_mod.signal_quality(abs(edge_top) if edge_top is not None else 0,
                                          confidence, liquidity, spread)

    return {
        "fixture_id": fx["id"],
        "kickoff_utc": fx["kickoff_utc"],
        "tour": fx["tour"],
        "tournament": fx["tournament"],
        "round": fx.get("round", ""),
        "surface": surface or "N/A",
        "best_of": fx.get("best_of", 3),
        "p1_name": fx["p1_name"], "p2_name": fx["p2_name"],
        "model": {o: round(probs[o] * 100, 1) for o in OUTCOMES},
        "market": ({o: round(market_probs[o] * 100, 1) for o in OUTCOMES} if market_probs else None),
        "edge": edge, "edge_top": edge_top, "top_pick": top,
        "confidence": confidence, "confidence_signals": conf_signals,
        "data_quality": data_quality,
        "liquidity": liquidity, "liquidity_label": conf_mod.liquidity_label(liquidity),
        "spread": spread, "spread_label": conf_mod.spread_label(spread),
        "signal_quality": sig_quality,
        "match_confidence": round(match_conf * 100, 1) if match_conf is not None else None,
        "market_status": ("MATCHED" if market else
                          ("LOW CONFIDENCE" if match_res else "POLYMARKET MARKET NOT FOUND")),
        "polymarket_market_id": market_id,
        "components": ensemble.components, "weights_used": ensemble.weights_used,
        "points_detail": {
            "set_prob_p1": round(points_res.set_prob_p1, 3),
            "spw1": round(points_res.spw1, 3), "spw2": round(points_res.spw2, 3),
        },
        "form": {"p1": f1.to_row(), "p2": f2.to_row(),
                 "p1_surface": f1_surf.to_row(), "p2_surface": f2_surf.to_row()},
        "elo": {"p1": round(r1.blended(surface)), "p2": round(r2.blended(surface)),
                "p1_overall": round(r1.elo), "p2_overall": round(r2.elo)},
        "h2h": ({"p1_wins": h2h_rec["p1_wins"], "p2_wins": h2h_rec["p2_wins"]} if h2h_rec else None),
    }


def _calibration_quality(db):
    row = db.query_one("SELECT ece FROM backtest_results ORDER BY run_utc DESC LIMIT 1")
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
            p1_probability, p2_probability, market_p1, market_p2,
            edge_p1, edge_p2, confidence, data_quality, components_json,
            polymarket_market_id, match_confidence)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (now, fx["id"], MODEL_VERSION, "MATCH_WINNER",
         model["p1"] / 100, model["p2"] / 100,
         (market or {}).get("p1"), (market or {}).get("p2"),
         edge.get("p1"), edge.get("p2"),
         analysis["confidence"], analysis["data_quality"],
         json.dumps({"components": analysis["components"], "weights": analysis["weights_used"]}),
         analysis.get("polymarket_market_id"), analysis.get("match_confidence")),
    )
    db.upsert("fixtures", {
        "id": fx["id"], "tour": fx["tour"], "tournament": fx["tournament"],
        "round": fx.get("round"), "surface": fx.get("surface"), "best_of": fx.get("best_of"),
        "kickoff_utc": fx["kickoff_utc"], "status": fx["status"],
        "p1_id": fx["p1_id"], "p2_id": fx["p2_id"],
        "p1_name": fx["p1_name"], "p2_name": fx["p2_name"],
        "winner": fx.get("winner"), "score": fx.get("score"), "updated_utc": now,
    }, ["id"])
    if analysis.get("polymarket_market_id") and analysis.get("market"):
        db.execute(
            """INSERT INTO polymarket_prices (market_id, timestamp_utc, outcome, price, spread, liquidity)
               VALUES (?,?,?,?,?,?)""",
            (analysis["polymarket_market_id"], now, analysis["top_pick"],
             analysis["market"][analysis["top_pick"]] / 100,
             analysis.get("spread"), analysis.get("liquidity")),
        )


def get_fixture_detail(fixture_id: str) -> dict | None:
    data = analyze_upcoming()
    for m in data["matches"]:
        if str(m["fixture_id"]) == str(fixture_id):
            return m
    return None
