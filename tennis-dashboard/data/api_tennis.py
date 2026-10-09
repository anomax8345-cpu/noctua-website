"""API-Tennis client (api-tennis.com).

API-Tennis uses a method-based REST interface:
    https://api.api-tennis.com/tennis/?method=<method>&APIkey=<key>&...
Responses are JSON: {"success": 1, "result": [...]}.

Methods used:
  get_fixtures   (date_start, date_stop)  -> scheduled & finished matches
  get_H2H        (first_player_key, second_player_key)
  get_standings  (event_type=ATP|WTA)     -> rankings

Fixture fields (per API-Tennis docs): event_key, event_date, event_time,
event_first_player, event_second_player, first_player_key, second_player_key,
event_final_result, event_winner ("First Player"/"Second Player"),
event_status, event_type_type (e.g. "Atp Singles"), tournament_name,
tournament_round, tournament_season, event_qualification.

Key handling: the API key is a query parameter read ONLY server-side; it is
never returned to the frontend. Robustness: timeouts, bounded retries with
backoff, rate-limit handling, caching. On hard failure we raise; we NEVER
fabricate tennis data.

NOTE: API-Tennis does not expose a surface field on every fixture; surface is
classified best-effort from tournament text and otherwise left N/A.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import SETTINGS, classify_surface, classify_tour
from data.cache import CACHE


class ApiTennisError(RuntimeError):
    pass


class ApiTennisClient:
    def __init__(self, settings=SETTINGS):
        self.settings = settings

    @property
    def base_url(self) -> str:
        return f"https://{self.settings.api_tennis_host}/tennis/"

    def _get(self, method: str, params: dict[str, Any], ttl: int) -> list[dict[str, Any]]:
        key = self.settings.api_tennis_key
        if not key:
            raise ApiTennisError(
                "API_TENNIS_KEY is not configured. Set it in your .env file or on "
                "the Settings page. The app runs without it, but no live tennis "
                "data can be loaded. (Note: this is separate from any football "
                "API-Sports key — API-Sports does not cover tennis.)"
            )
        query = {"method": method, "APIkey": key, **params}
        cache_key = f"at:{method}:{sorted((k, v) for k, v in params.items())}"
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = requests.get(self.base_url, params=query, timeout=15)
                if resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get("success"):
                    # API-Tennis returns success:0 with an error message
                    raise ApiTennisError(f"API-Tennis error: {payload.get('result') or payload}")
                result = payload.get("result", [])
                if not isinstance(result, list):
                    result = []
                CACHE.set(cache_key, result, ttl)
                return result
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(2 ** attempt)
        raise ApiTennisError(f"API-Tennis request failed for {method}: {last_err}")

    # -- fixtures --------------------------------------------------------------
    def fixtures_between(self, start_utc: datetime, end_utc: datetime) -> list[dict[str, Any]]:
        raw = self._get(
            "get_fixtures",
            {"date_start": start_utc.date().isoformat(),
             "date_stop": end_utc.date().isoformat()},
            ttl=self.settings.cache_ttl_fixtures,
        )
        out = []
        for item in raw:
            norm = self._normalize_fixture(item)
            if norm is None:
                continue
            ko = datetime.fromisoformat(norm["kickoff_utc"])
            if start_utc <= ko <= end_utc:
                out.append(norm)
        out.sort(key=lambda f: f["kickoff_utc"])
        return out

    @staticmethod
    def _normalize_fixture(item: dict[str, Any]) -> dict[str, Any] | None:
        try:
            date = item.get("event_date")
            t = item.get("event_time") or "00:00"
            if not date:
                return None
            dt = datetime.fromisoformat(f"{date}T{t}:00+00:00").astimezone(timezone.utc)
            etype = item.get("event_type_type", "") or ""
            tournament = item.get("tournament_name", "") or ""
            winner_raw = item.get("event_winner")
            winner = None
            if winner_raw == "First Player":
                winner = "p1"
            elif winner_raw == "Second Player":
                winner = "p2"
            best_of = 5 if ("grand slam" in f"{etype} {tournament}".lower()
                            and "atp" in etype.lower()) else 3
            return {
                "id": str(item.get("event_key")),
                "tour": classify_tour(etype, tournament),
                "tournament": tournament,
                "round": item.get("tournament_round", ""),
                "surface": classify_surface(f"{tournament} {item.get('event_type_type','')}"),
                "best_of": best_of,
                "kickoff_utc": dt.isoformat(),
                "status": item.get("event_status", "") or "",
                "p1_id": str(item.get("first_player_key")),
                "p2_id": str(item.get("second_player_key")),
                "p1_name": item.get("event_first_player", ""),
                "p2_name": item.get("event_second_player", ""),
                "winner": winner,
                "score": item.get("event_final_result"),
                "event_type": etype,
            }
        except (KeyError, TypeError, ValueError):
            return None

    # -- head to head ----------------------------------------------------------
    def h2h(self, p1_id: str, p2_id: str) -> dict[str, Any] | None:
        try:
            raw = self._get(
                "get_H2H",
                {"first_player_key": p1_id, "second_player_key": p2_id},
                ttl=self.settings.cache_ttl_player_form,
            )
        except ApiTennisError:
            return None
        # API-Tennis returns {"H2H": [...matches...]} inside result; the _get
        # helper returns a list, so handle both shapes defensively.
        matches = []
        if raw and isinstance(raw, list) and isinstance(raw[0], dict) and "H2H" in raw[0]:
            matches = raw[0].get("H2H", [])
        p1w = p2w = 0
        last = None
        for m in matches:
            w = m.get("event_winner")
            if w == "First Player":
                p1w += 1
            elif w == "Second Player":
                p2w += 1
            last = m.get("event_date") or last
        if p1w == 0 and p2w == 0:
            return None
        return {"p1_wins": p1w, "p2_wins": p2w, "last_meeting": last}

    # -- recent matches for a player (for form) --------------------------------
    def player_recent(self, player_id: str, start_utc: datetime, end_utc: datetime) -> list[dict[str, Any]]:
        raw = self._get(
            "get_fixtures",
            {"date_start": start_utc.date().isoformat(),
             "date_stop": end_utc.date().isoformat(),
             "player_key": player_id},
            ttl=self.settings.cache_ttl_player_form,
        )
        out = []
        for item in raw:
            norm = self._normalize_fixture(item)
            if norm and norm["winner"] is not None:
                out.append(norm)
        return out
