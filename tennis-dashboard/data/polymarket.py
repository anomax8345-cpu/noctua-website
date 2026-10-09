"""Polymarket client (tennis).

Identical mechanics to the football version (Gamma discovery + CLOB order book),
but the market filter keeps tennis markets and excludes other sports. Prices
and some arrays may arrive as strings; we parse defensively and never fabricate
missing fields (they become None / N/A).
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

    def search_tennis_markets(self, limit: int = 200) -> list[dict[str, Any]]:
        try:
            raw = self._get(
                GAMMA_BASE, "markets",
                {"closed": "false", "active": "true", "limit": limit,
                 "order": "volume", "ascending": "false"},
                ttl=self.settings.cache_ttl_markets,
            )
        except PolymarketError:
            return []
        markets = raw if isinstance(raw, list) else raw.get("data", [])
        out = []
        for m in markets:
            norm = self._normalize_market(m)
            if norm and self._looks_like_tennis(norm):
                out.append(norm)
        return out

    @staticmethod
    def _looks_like_tennis(market: dict[str, Any]) -> bool:
        text = " ".join(str(market.get(k, "")) for k in ("question", "slug", "category")).lower()
        tennis_terms = ("tennis", "atp", "wta", "wimbledon", "us open", "roland garros",
                        "french open", "australian open", "grand slam")
        exclude = ("nfl", "nba", "mlb", "nhl", "soccer", "football", "cricket", "ufc", "golf")
        if any(x in text for x in exclude):
            return False
        return any(s in text for s in tennis_terms)

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
                "event_id": str((m.get("events") or [{}])[0].get("id", "")) if m.get("events") else str(m.get("eventId", "")),
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
            "bids": [{"price": _to_float(b.get("price")), "size": _to_float(b.get("size"))} for b in bids],
            "asks": [{"price": _to_float(a.get("price")), "size": _to_float(a.get("size"))} for a in asks],
        }
