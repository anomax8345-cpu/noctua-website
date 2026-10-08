"""Football Prediction & Polymarket Research Dashboard — Flask entry point.

Run locally:
    python app.py
then open http://127.0.0.1:5000

The app is intentionally resilient: it starts and renders even with no API key
and no network. In that state it shows clear "configure your API key" / "market
data unavailable" messages instead of crashing.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template, request, url_for

from config import LEAGUE_CATALOG, MODEL_VERSION, REGIONS, SETTINGS
from database.database import get_db
from services import pipeline

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")


# --------------------------------------------------------------------------- #
# Settings persistence: load any DB-stored overrides into SETTINGS at startup.
# --------------------------------------------------------------------------- #
_SETTING_FIELDS = [
    "api_football_key", "api_football_host", "timezone", "lookahead_hours",
    "enabled_leagues", "min_edge_pp", "min_confidence", "min_liquidity_usd",
    "refresh_markets_seconds", "refresh_football_seconds",
    "weight_elo", "weight_poisson", "weight_xg", "weight_form", "weight_home",
]


def _coerce(field: str, value: str):
    int_fields = {"lookahead_hours", "min_confidence", "refresh_markets_seconds",
                  "refresh_football_seconds"}
    float_fields = {"min_edge_pp", "min_liquidity_usd", "weight_elo",
                    "weight_poisson", "weight_xg", "weight_form", "weight_home"}
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
    get_db()  # ensure schema
    load_settings_from_db()


# --------------------------------------------------------------------------- #
# Template helpers
# --------------------------------------------------------------------------- #
def to_local(iso_utc: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ZoneInfo(SETTINGS.timezone))
        return local.strftime("%d.%m.%Y %H:%M")
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


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    data = pipeline.analyze_upcoming()
    leagues = sorted({m["league"] for m in data["matches"]})
    return render_template(
        "index.html",
        data=data,
        regions=REGIONS,
        leagues=leagues,
        settings=SETTINGS,
        now=to_local(data["generated_utc"]),
    )


@app.route("/match/<int:fixture_id>")
def match_detail(fixture_id: int):
    detail = pipeline.get_fixture_detail(fixture_id)
    if detail is None:
        return render_template("match.html", detail=None, fixture_id=fixture_id), 404
    return render_template("match.html", detail=detail, fixture_id=fixture_id)


@app.route("/performance")
def performance():
    db = get_db()
    # Build scoring rows (top_pick_prob = prob of model's pick)
    from backtest.calibration import performance_from_results
    scored = []
    for r in db.query(
        """SELECT pr.predicted_prob AS predicted_prob, pr.top_pick_hit AS top_pick_hit,
                  pr.outcome AS outcome, p.confidence AS confidence,
                  p.home_probability AS hp, p.draw_probability AS dp, p.away_probability AS ap
           FROM prediction_results pr JOIN predictions p ON p.id = pr.prediction_id"""
    ):
        pick_prob = max(r["hp"] or 0, r["dp"] or 0, r["ap"] or 0)
        scored.append({
            "predicted_prob": r["predicted_prob"],
            "top_pick_hit": r["top_pick_hit"],
            "top_pick_prob": pick_prob,
            "edge": None,
            "confidence": r["confidence"],
        })
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
            if field == "api_football_key":
                # Only overwrite the key if a non-empty value was submitted,
                # so the (never-rendered) existing key is preserved otherwise.
                val = request.form.get("api_football_key", "").strip()
                if val:
                    db.set_setting("api_football_key", val)
                continue
            if field in request.form:
                db.set_setting(field, request.form.get(field, "").strip())
        load_settings_from_db()
        from data.cache import CACHE
        CACHE.clear()
        message = "Settings saved. Caches cleared."
    key_set = bool(SETTINGS.api_football_key)
    return render_template(
        "settings.html",
        settings=SETTINGS,
        leagues=LEAGUE_CATALOG,
        key_set=key_set,
        message=message,
    )


# --------------------------------------------------------------------------- #
# JSON API (for auto-refresh / charts)
# --------------------------------------------------------------------------- #
@app.route("/api/matches")
def api_matches():
    force = request.args.get("force") == "1"
    return jsonify(pipeline.analyze_upcoming(force=force))


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "model_version": MODEL_VERSION,
        "api_key_configured": bool(SETTINGS.api_football_key),
        "timezone": SETTINGS.timezone,
        "lookahead_hours": SETTINGS.lookahead_hours,
    })


@app.route("/api/price-history/<market_id>")
def api_price_history(market_id: str):
    db = get_db()
    rows = db.query(
        "SELECT timestamp_utc, price FROM polymarket_prices "
        "WHERE market_id=? AND price IS NOT NULL ORDER BY timestamp_utc",
        (market_id,),
    )
    return jsonify([{"t": r["timestamp_utc"], "price": r["price"]} for r in rows])


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug)
