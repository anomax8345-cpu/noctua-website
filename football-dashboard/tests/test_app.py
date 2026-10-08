"""Smoke tests for the Flask app.

These verify the app starts and renders gracefully with NO API key and NO
network — the resilience requirements from the spec (tests 1-3).
"""
import os
import tempfile

import pytest


@pytest.fixture()
def client(monkeypatch):
    # Point the DB at a throwaway file BEFORE importing the app.
    tmp = os.path.join(tempfile.gettempdir(), "fd_test.sqlite")
    from database.database import reset_db_for_tests
    reset_db_for_tests(tmp)

    # No API key -> football layer fails fast (no network).
    from config import SETTINGS
    monkeypatch.setattr(SETTINGS, "api_football_key", "", raising=False)

    # Stub Polymarket so tests never touch the network.
    from data.polymarket import PolymarketClient
    monkeypatch.setattr(PolymarketClient, "search_soccer_markets", lambda self, limit=200: [])

    from data.cache import CACHE
    CACHE.clear()

    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_app_starts_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["api_key_configured"] is False


def test_index_renders_without_key_or_markets(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # resilience messaging present
    assert "FOOTBALL MARKET ANALYZER" in html
    assert "Live football data unavailable" in html


def test_api_matches_returns_structure(client):
    resp = client.get("/api/matches")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "matches" in data
    assert "status" in data
    assert data["status"]["football_ok"] is False
    # No markets, no fixtures -> empty list, but no crash.
    assert isinstance(data["matches"], list)


def test_settings_page_hides_key(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "NOT SET" in html  # key status shown, never the key value


def test_missing_match_detail_404(client):
    resp = client.get("/match/999999")
    assert resp.status_code == 404
