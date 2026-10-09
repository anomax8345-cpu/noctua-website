"""Smoke tests: the app starts and renders gracefully with NO key and NO network."""
import os
import tempfile

import pytest


@pytest.fixture()
def client(monkeypatch):
    tmp = os.path.join(tempfile.gettempdir(), "td_test.sqlite")
    from database.database import reset_db_for_tests
    reset_db_for_tests(tmp)

    from config import SETTINGS
    monkeypatch.setattr(SETTINGS, "api_tennis_key", "", raising=False)

    from data.polymarket import PolymarketClient
    monkeypatch.setattr(PolymarketClient, "search_tennis_markets", lambda self, limit=200: [])

    from data.cache import CACHE
    CACHE.clear()

    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_health(client):
    body = client.get("/api/health").get_json()
    assert body["ok"] is True
    assert body["api_key_configured"] is False


def test_index_renders_without_key(client):
    html = client.get("/").get_data(as_text=True)
    assert "TENNIS MARKET ANALYZER" in html
    assert "Live tennis data unavailable" in html


def test_api_matches_structure(client):
    data = client.get("/api/matches").get_json()
    assert "matches" in data and "status" in data
    assert data["status"]["tennis_ok"] is False
    assert isinstance(data["matches"], list)


def test_settings_hides_key(client):
    html = client.get("/settings").get_data(as_text=True)
    assert "NOT SET" in html


def test_missing_match_404(client):
    assert client.get("/match/does-not-exist").status_code == 404
