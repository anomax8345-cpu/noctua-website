"""Central configuration for the tennis dashboard.

Tennis has no league table like football; the relevant groupings are the
**tour** (ATP / WTA / Challenger / ITF) and the **surface** (Hard / Clay /
Grass / Carpet). Surface matters enormously, so the model keeps surface-specific
Elo ratings. The tour catalog below is data (enable ALL or a named subset), not
hard-wired logic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tennis.sqlite")

MODEL_VERSION = "tennis_model_v1.0"

SURFACES = ["Hard", "Clay", "Grass", "Carpet"]


@dataclass(frozen=True)
class Tour:
    name: str
    # substrings matched (case-insensitive) against the provider's event type /
    # tournament name to classify a fixture into this tour.
    match_terms: tuple[str, ...]


# Tour catalog. A fixture is assigned to the first tour whose terms match.
TOUR_CATALOG: list[Tour] = [
    Tour("Grand Slam", ("grand slam", "australian open", "roland garros",
                        "french open", "wimbledon", "us open")),
    Tour("ATP", ("atp",)),
    Tour("WTA", ("wta",)),
    Tour("ATP Challenger", ("challenger",)),
    Tour("ITF", ("itf",)),
    Tour("Davis/United Cup", ("davis cup", "united cup", "billie jean")),
]

TOUR_BY_NAME = {t.name: t for t in TOUR_CATALOG}


def classify_tour(event_type: str, tournament: str) -> str:
    hay = f"{event_type} {tournament}".lower()
    for tour in TOUR_CATALOG:
        if any(term in hay for term in tour.match_terms):
            return tour.name
    return "Other"


def classify_surface(text: str | None) -> str | None:
    """Best-effort surface classification from provider strings. Returns None
    (-> N/A) when it cannot be determined — never guessed."""
    if not text:
        return None
    t = text.lower()
    if "clay" in t:
        return "Clay"
    if "grass" in t:
        return "Grass"
    if "carpet" in t:
        return "Carpet"
    if "hard" in t or "indoor hard" in t or "outdoor hard" in t:
        return "Hard"
    return None


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    api_tennis_key: str = field(default_factory=lambda: os.getenv("API_TENNIS_KEY", ""))
    api_tennis_host: str = field(default_factory=lambda: os.getenv("API_TENNIS_HOST", "api.api-tennis.com"))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Europe/Zurich"))
    lookahead_hours: int = field(default_factory=lambda: _as_int(os.getenv("LOOKAHEAD_HOURS"), 48))
    enabled_tours: str = field(default_factory=lambda: os.getenv("ENABLED_TOURS", "ALL"))

    min_edge_pp: float = field(default_factory=lambda: _as_float(os.getenv("MIN_EDGE_PP"), 3.0))
    min_confidence: int = field(default_factory=lambda: _as_int(os.getenv("MIN_CONFIDENCE"), 60))
    min_liquidity_usd: float = field(default_factory=lambda: _as_float(os.getenv("MIN_LIQUIDITY_USD"), 500.0))

    refresh_markets_seconds: int = field(default_factory=lambda: _as_int(os.getenv("REFRESH_MARKETS_SECONDS"), 300))
    refresh_tennis_seconds: int = field(default_factory=lambda: _as_int(os.getenv("REFRESH_TENNIS_SECONDS"), 1800))

    cache_ttl_fixtures: int = field(default_factory=lambda: _as_int(os.getenv("CACHE_TTL_FIXTURES"), 900))
    cache_ttl_player_form: int = field(default_factory=lambda: _as_int(os.getenv("CACHE_TTL_PLAYER_FORM"), 3600))
    cache_ttl_rankings: int = field(default_factory=lambda: _as_int(os.getenv("CACHE_TTL_RANKINGS"), 43200))
    cache_ttl_markets: int = field(default_factory=lambda: _as_int(os.getenv("CACHE_TTL_MARKETS"), 120))

    # Default ensemble weights. Renormalised automatically when a model is
    # unavailable for a given match.
    weight_elo_surface: float = 0.40   # surface-blended Elo (primary)
    weight_points: float = 0.20        # serve/return points model
    weight_form: float = 0.20
    weight_h2h: float = 0.20

    def enabled_tour_names(self) -> list[str]:
        raw = (self.enabled_tours or "ALL").strip()
        if raw.upper() == "ALL":
            return [t.name for t in TOUR_CATALOG]
        return [n.strip() for n in raw.split(",") if n.strip()]

    def tour_enabled(self, tour_name: str) -> bool:
        if (self.enabled_tours or "ALL").strip().upper() == "ALL":
            return True
        return tour_name in self.enabled_tour_names()

    def model_weights(self) -> dict[str, float]:
        return {
            "elo_surface": self.weight_elo_surface,
            "points": self.weight_points,
            "form": self.weight_form,
            "h2h": self.weight_h2h,
        }


SETTINGS = Settings()
