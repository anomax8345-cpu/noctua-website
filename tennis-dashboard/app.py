"""Tennis Prediction & Polymarket Research Dashboard — Flask entry point.

Run locally:  python app.py   ->   http://127.0.0.1:5001

Starts and renders even with no API key and no network, showing clear
"configure your key" / "markets unavailable" messages instead of crashing.
Runs on port 5001 so it can coexist with the football dashboard (port 5000).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request

from config import MODEL_VERSION, SETTINGS, SURFACES, TOUR_CATALOG
from database.database import get_db
from services import pipeline

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

_SETTING_FIELDS = [
    "api_tennis_key", "api_tennis_host", "timezone", "lookahead_hours",
    "enabled_tours", "min_edge_pp", "min_confidence", "min_liquidity_usd",
    "refresh_markets_seconds", "refresh_tennis_seconds",
    "weight_elo_surface", "weight_points", "weight_form", "weight_h2h",
]


def _coerce(field: str, value: str):
    int_fields = {"lookahead_hours", "min_confidence", "refresh_markets_seconds",
                  "refresh_tennis_seconds"}
    float_fields = {"min_edge_pp", "min_liquidity_usd", "weight_elo_surface",
                    "weight_points", "weight_form", "weight_h2h"}
    if field in int_fields:
        return int(float(value))
    if field in float_fields:
        return float(value)
    return value


def load_settings_from_db() -> None:
    db = get_db()
    stored = db.all_settings()
    for field in _SETTING_FIELDS:
        if field in stored and stored[field] != "":
            try:
                setattr(SETTINGS, field, _coerce(field, stored[field]))
            except (ValueError, TypeError):
                pass


with app.app_context():
    get_db()
    load_settings_from_db()


def to_local(iso_utc: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(SETTINGS.timezone)).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso_utc


@app.context_processor
def inject_globals():
    return {
        "model_version": MODEL_VERSION,
        "to_local": to_local,
        "timezone": SETTINGS.timezone,
        "refresh_markets_seconds": SETTINGS.refresh_markets_seconds,
    }


@app.route("/")
def index():
    data = pipeline.analyze_upcoming()
    tours = sorted({m["tour"] for m in data["matches"]})
    return render_template("index.html", data=data, tours=tours, surfaces=SURFACES,
                           settings=SETTINGS, now=to_local(data["generated_utc"]))


@app.route("/match/<fixture_id>")
def match_detail(fixture_id: str):
    detail = pipeline.get_fixture_detail(fixture_id)
    if detail is None:
        return render_template("match.html", detail=None, fixture_id=fixture_id), 404
    return render_template("match.html", detail=detail, fixture_id=fixture_id)


@app.route("/performance")
def performance():
    db = get_db()
    from backtest.calibration import performance_from_results
    scored = []
    for r in db.query(
        """SELECT pr.predicted_prob AS predicted_prob, pr.top_pick_hit AS pick_hit,
                  p.confidence AS confidence, p.p1_probability AS p1p, p.p2_probability AS p2p
           FROM prediction_results pr JOIN predictions p ON p.id = pr.prediction_id"""
    ):
        pick_prob = max(r["p1p"] or 0, r["p2p"] or 0)
        scored.append({"pick_prob": pick_prob, "pick_hit": r["pick_hit"],
                       "edge": None, "confidence": r["confidence"]})
    perf = performance_from_results(scored)
    return render_template("performance.html", perf=perf)


@app.route("/backtest")
def backtest_page():
    db = get_db()
    last = db.query_one("SELECT * FROM backtest_results ORDER BY run_utc DESC LIMIT 1")
    return render_template("backtest.html", last=dict(last) if last else None)


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    db = get_db()
    message = None
    if request.method == "POST":
        for field in _SETTING_FIELDS:
            if field == "api_tennis_key":
                val = request.form.get("api_tennis_key", "").strip()
                if val:
                    db.set_setting("api_tennis_key", val)
                continue
            if field in request.form:
                db.set_setting(field, request.form.get(field, "").strip())
        load_settings_from_db()
        from data.cache import CACHE
        CACHE.clear()
        message = "Settings saved. Caches cleared."
    return render_template("settings.html", settings=SETTINGS, tours=TOUR_CATALOG,
                           key_set=bool(SETTINGS.api_tennis_key), message=message)


@app.route("/api/matches")
def api_matches():
    return jsonify(pipeline.analyze_upcoming(force=request.args.get("force") == "1"))


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True, "model_version": MODEL_VERSION,
        "api_key_configured": bool(SETTINGS.api_tennis_key),
        "timezone": SETTINGS.timezone, "lookahead_hours": SETTINGS.lookahead_hours,
    })


@app.route("/api/price-history/<market_id>")
def api_price_history(market_id: str):
    db = get_db()
    rows = db.query(
        "SELECT timestamp_utc, price FROM polymarket_prices "
        "WHERE market_id=? AND price IS NOT NULL ORDER BY timestamp_utc", (market_id,),
    )
    return jsonify([{"t": r["timestamp_utc"], "price": r["price"]} for r in rows])


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5001, debug=debug)
