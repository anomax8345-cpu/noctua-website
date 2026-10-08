"""API-Football v3 client.

Docs: https://www.api-football.com/documentation-v3

Endpoints used (all GET):
  /status                         -> plan + current usage (used for diagnostics)
  /fixtures?date=YYYY-MM-DD&...    -> fixtures for a date
  /fixtures?league=&season=&...    -> fixtures by league
  /teams/statistics               -> aggregate team stats for a league/season
  /fixtures?team=&last=N          -> recent results (for form)
  /injuries?fixture=              -> injuries/suspensions for a fixture

Key handling:
  * The API key is read ONLY from server-side settings/env. It is attached as a
    request header and is never returned to the frontend.
  * Both direct (api-sports.io -> header "x-apisports-key") and RapidAPI
    (-> headers "x-rapidapi-key"/"x-rapidapi-host") hosting are supported.

Robustness:
  * timeouts, bounded retries with backoff, and rate-limit (429) handling.
  * every call is cached with a TTL so repeated page renders do not re-hit the
    API.
  * on hard failure we return an empty/typed result and surface the error; we
    NEVER fabricate football data.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import SETTINGS
from data.cache import CACHE


class ApiFootballError(RuntimeError):
    pass


class ApiFootballClient:
    def __init__(self, settings=SETTINGS):
        self.settings = settings

    # -- low level -------------------------------------------------------------
    @property
    def base_url(self) -> str:
        host = self.settings.api_football_host
        return f"https://{host}"

    def _headers(self) -> dict[str, str]:
        key = self.settings.api_football_key
        host = self.settings.api_football_host
        if not key:
            raise ApiFootballError(
                "API_FOOTBALL_KEY is not configured. Set it in your .env file "
                "or on the Settings page. The app runs without it, but no live "
                "football data can be loaded."
            )
        if "rapidapi" in host:
            return {"x-rapidapi-key": key, "x-rapidapi-host": host}
        return {"x-apisports-key": key}

    def _get(self, path: str, params: dict[str, Any], ttl: int) -> dict[str, Any]:
        cache_key = f"af:{path}:{sorted(params.items())}"
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/{path.lstrip('/')}"
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = requests.get(
                    url, headers=self._headers(), params=params, timeout=15
                )
                if resp.status_code == 429:
                    # rate limited — exponential backoff
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                payload = resp.json()
                # API-Football wraps errors in an "errors" object with HTTP 200.
                errors = payload.get("errors")
                if errors:
                    raise ApiFootballError(f"API-Football error: {errors}")
                CACHE.set(cache_key, payload, ttl)
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(2 ** attempt)
        raise ApiFootballError(f"API-Football request failed for {path}: {last_err}")

    # -- diagnostics -----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        payload = self._get("status", {}, ttl=300)
        return payload.get("response", {})

    # -- fixtures --------------------------------------------------------------
    def fixtures_between(
        self, start_utc: datetime, end_utc: datetime, league_ids: list[int]
    ) -> list[dict[str, Any]]:
        """Return normalised fixtures kicking off within [start, end].

        We query day-by-day (API-Football is date-indexed) and filter by the
        enabled league ids and the exact time window.
        """
        out: list[dict[str, Any]] = []
        day = start_utc.date()
        last_day = end_utc.date()
        allowed = set(league_ids)
        while day <= last_day:
            payload = self._get(
                "fixtures",
                {"date": day.isoformat(), "timezone": "UTC"},
                ttl=self.settings.cache_ttl_fixtures,
            )
            for item in payload.get("response", []):
                norm = self._normalize_fixture(item)
                if norm is None:
                    continue
                if allowed and norm["league_id"] not in allowed:
                    continue
                ko = datetime.fromisoformat(norm["kickoff_utc"])
                if start_utc <= ko <= end_utc:
                    out.append(norm)
            day += timedelta(days=1)
        out.sort(key=lambda f: f["kickoff_utc"])
        return out

    @staticmethod
    def _normalize_fixture(item: dict[str, Any]) -> dict[str, Any] | None:
        try:
            fx = item["fixture"]
            lg = item["league"]
            teams = item["teams"]
            goals = item.get("goals", {})
            ko = fx["date"]
            dt = datetime.fromisoformat(ko.replace("Z", "+00:00")).astimezone(timezone.utc)
            return {
                "id": fx["id"],
                "kickoff_utc": dt.isoformat(),
                "status": (fx.get("status") or {}).get("short", "NS"),
                "league_id": lg["id"],
                "league_name": lg.get("name", ""),
                "season": lg.get("season"),
                "home_team_id": teams["home"]["id"],
                "away_team_id": teams["away"]["id"],
                "home_team": teams["home"]["name"],
                "away_team": teams["away"]["name"],
                "home_goals": goals.get("home"),
                "away_goals": goals.get("away"),
            }
        except (KeyError, TypeError, ValueError):
            return None

    # -- recent results for form ----------------------------------------------
    def team_last_fixtures(self, team_id: int, count: int = 20) -> list[dict[str, Any]]:
        payload = self._get(
            "fixtures",
            {"team": team_id, "last": count, "timezone": "UTC"},
            ttl=self.settings.cache_ttl_team_form,
        )
        results = []
        for item in payload.get("response", []):
            norm = self._normalize_fixture(item)
            if norm and norm["status"] in {"FT", "AET", "PEN"}:
                results.append(norm)
        return results

    # -- injuries / suspensions ------------------------------------------------
    def injuries_for_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        """Return injured/suspended players. Empty list means 'none reported'
        which is different from 'data unavailable' — callers decide how to
        present that. On error we raise so the caller can mark N/A."""
        payload = self._get(
            "injuries",
            {"fixture": fixture_id},
            ttl=self.settings.cache_ttl_team_form,
        )
        out = []
        for item in payload.get("response", []):
            player = item.get("player", {})
            team = item.get("team", {})
            out.append(
                {
                    "team_id": team.get("id"),
                    "player_name": player.get("name"),
                    "reason": player.get("reason") or player.get("type"),
                }
            )
        return out
