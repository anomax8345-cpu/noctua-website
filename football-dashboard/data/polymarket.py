"""Polymarket client.

Two public APIs are used:

  * Gamma API (https://gamma-api.polymarket.com) — discovery/metadata:
      GET /events        : events (each event groups related markets)
      GET /markets       : markets with outcomes + outcomePrices + volume +
                           liquidity + bestBid/bestAsk + lastTradePrice + spread
    Query params commonly used: ?closed=false&limit=&offset=&tag=  and the
    "search" param for keyword discovery.

  * CLOB API (https://clob.polymarket.com) — live order book / prices:
      GET /book?token_id=   : order book (bids/asks) for a market token
      GET /price?token_id=&side=buy|sell

Fields are defensive-parsed: Polymarket sometimes returns numbers as strings
and some list fields as JSON-encoded strings. We parse both forms. When a
field is absent we store None / N/A — we never invent a value.

This client is written to the documented response shapes. Because the egress
policy of some sandboxes blocks polymarket.com, callers must tolerate network
errors (no markets -> the app still works; markets are simply shown as N/A).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import requests

from config import SETTINGS
from data.cache import CACHE

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


class PolymarketError(RuntimeError):
    pass


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_json_list(value: Any) -> list[Any]:
    """Gamma returns some arrays as JSON-encoded strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


class PolymarketClient:
    def __init__(self, settings=SETTINGS):
        self.settings = settings

    def _get(self, base: str, path: str, params: dict[str, Any], ttl: int) -> Any:
        cache_key = f"pm:{base}:{path}:{sorted(params.items())}"
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached
        url = f"{base}/{path.lstrip('/')}"
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                CACHE.set(cache_key, data, ttl)
                return data
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
        raise PolymarketError(f"Polymarket request failed for {url}: {last_err}")

    # -- discovery -------------------------------------------------------------
    def search_soccer_markets(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return active soccer/football markets, normalised.

        We filter to soccer via the Gamma tag/category plus a keyword fallback.
        Returns [] on any failure (the app must keep working without markets).
        """
        try:
            raw = self._get(
                GAMMA_BASE,
                "markets",
                {
                    "closed": "false",
                    "active": "true",
                    "limit": limit,
                    "order": "volume",
                    "ascending": "false",
                },
                ttl=self.settings.cache_ttl_markets,
            )
        except PolymarketError:
            return []

        markets = raw if isinstance(raw, list) else raw.get("data", [])
        out = []
        for m in markets:
            norm = self._normalize_market(m)
            if norm and self._looks_like_soccer(norm):
                out.append(norm)
        return out

    @staticmethod
    def _looks_like_soccer(market: dict[str, Any]) -> bool:
        text = " ".join(
            str(market.get(k, "")) for k in ("question", "slug", "category")
        ).lower()
        # Positive soccer signals; kept broad but excludes obvious other sports.
        soccer_terms = (
            "soccer", "football", "epl", "la liga", "bundesliga", "serie a",
            "ligue 1", "champions league", "uefa", "mls", "vs",
        )
        exclude = ("nfl", "nba", "mlb", "nhl", "tennis", "cricket", "ufc")
        if any(x in text for x in exclude):
            return False
        return any(s in text for s in soccer_terms)

    @staticmethod
    def _normalize_market(m: dict[str, Any]) -> dict[str, Any] | None:
        try:
            outcomes = _maybe_json_list(m.get("outcomes"))
            prices = [_to_float(p) for p in _maybe_json_list(m.get("outcomePrices"))]
            token_ids = _maybe_json_list(m.get("clobTokenIds"))
            now = datetime.now(timezone.utc).isoformat()
            return {
                "market_id": str(m.get("id") or m.get("conditionId") or ""),
                "condition_id": m.get("conditionId"),
                "event_id": str((m.get("events") or [{}])[0].get("id", ""))
                if m.get("events")
                else str(m.get("eventId", "")),
                "question": m.get("question") or m.get("title") or "",
                "slug": m.get("slug", ""),
                "category": m.get("category", ""),
                "outcomes": outcomes,
                "prices": prices,
                "token_ids": token_ids,
                "volume": _to_float(m.get("volume") or m.get("volumeNum")),
                "liquidity": _to_float(m.get("liquidity") or m.get("liquidityNum")),
                "best_bid": _to_float(m.get("bestBid")),
                "best_ask": _to_float(m.get("bestAsk")),
                "spread": _to_float(m.get("spread")),
                "last_trade": _to_float(m.get("lastTradePrice")),
                "one_day_change": _to_float(m.get("oneDayPriceChange")),
                "end_date": m.get("endDate"),
                "timestamp_utc": now,
            }
        except (KeyError, TypeError, ValueError):
            return None

    # -- order book (CLOB) -----------------------------------------------------
    def order_book(self, token_id: str) -> dict[str, Any] | None:
        if not token_id:
            return None
        try:
            data = self._get(CLOB_BASE, "book", {"token_id": token_id}, ttl=60)
        except PolymarketError:
            return None
        bids = data.get("bids", []) if isinstance(data, dict) else []
        asks = data.get("asks", []) if isinstance(data, dict) else []
        return {
            "bids": [
                {"price": _to_float(b.get("price")), "size": _to_float(b.get("size"))}
                for b in bids
            ],
            "asks": [
                {"price": _to_float(a.get("price")), "size": _to_float(a.get("size"))}
                for a in asks
            ],
        }
