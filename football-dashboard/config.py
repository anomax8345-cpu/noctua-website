"""Central configuration.

Everything that a user might reasonably want to change lives here or in the
`.env` file. The league list is a *catalog* (data), not hard-wired business
logic: enabling/disabling leagues is done via the ENABLED_LEAGUES env var or
the Settings page, using the human-readable names below.

API-Football identifies leagues by numeric id. The catalog maps our friendly
names + region to those ids so the rest of the code never hard-codes a number.
The ids below are the long-standing API-Football league ids; if a league id
ever changes, only this table needs editing. Coverage per league/season is NOT
assumed — it is probed at runtime (see data/api_football.py).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "football.sqlite")

# Current model version. Bump this whenever the model logic changes so that
# historical predictions remain attributable to the model that produced them.
MODEL_VERSION = "model_v1.0"


@dataclass(frozen=True)
class League:
    name: str
    api_football_id: int
    region: str  # Europe | Asia | Middle East | Americas | International
    country: str = ""


# ---------------------------------------------------------------------------
# League catalog. Grouped by region. Add/remove freely — nothing else depends
# on the exact set being present.
# ---------------------------------------------------------------------------
LEAGUE_CATALOG: list[League] = [
    # --- Europe: domestic top & second tiers ---
    League("Bundesliga", 78, "Europe", "Germany"),
    League("2. Bundesliga", 79, "Europe", "Germany"),
    League("Premier League", 39, "Europe", "England"),
    League("Championship", 40, "Europe", "England"),
    League("La Liga", 140, "Europe", "Spain"),
    League("Segunda División", 141, "Europe", "Spain"),
    League("Serie A", 135, "Europe", "Italy"),
    League("Serie B", 136, "Europe", "Italy"),
    League("Ligue 1", 61, "Europe", "France"),
    League("Ligue 2", 62, "Europe", "France"),
    League("Eredivisie", 88, "Europe", "Netherlands"),
    League("Primeira Liga", 94, "Europe", "Portugal"),
    League("Belgian Pro League", 144, "Europe", "Belgium"),
    League("Scottish Premiership", 179, "Europe", "Scotland"),
    League("Austrian Bundesliga", 218, "Europe", "Austria"),
    League("Swiss Super League", 207, "Europe", "Switzerland"),
    League("Super League Greece", 197, "Europe", "Greece"),
    League("Turkish Süper Lig", 203, "Europe", "Turkey"),
    League("Danish Superliga", 119, "Europe", "Denmark"),
    League("Swedish Allsvenskan", 113, "Europe", "Sweden"),
    League("Norwegian Eliteserien", 103, "Europe", "Norway"),
    League("Polish Ekstraklasa", 106, "Europe", "Poland"),
    League("Czech First League", 345, "Europe", "Czech-Republic"),
    League("Croatian HNL", 210, "Europe", "Croatia"),
    # --- International / continental competitions ---
    League("UEFA Champions League", 2, "International"),
    League("UEFA Europa League", 3, "International"),
    League("UEFA Conference League", 848, "International"),
    League("UEFA Nations League", 5, "International"),
    League("Copa Libertadores", 13, "International"),
    League("Copa Sudamericana", 11, "International"),
    # --- Middle East / Asia ---
    League("Qatar Stars League", 305, "Middle East", "Qatar"),
    League("Saudi Pro League", 307, "Middle East", "Saudi-Arabia"),
    League("UAE Pro League", 301, "Middle East", "United-Arab-Emirates"),
    League("J1 League", 98, "Asia", "Japan"),
    League("K League 1", 292, "Asia", "South-Korea"),
    League("Chinese Super League", 169, "Asia", "China"),
    # --- Americas ---
    League("MLS", 253, "Americas", "USA"),
    League("Brasileirão", 71, "Americas", "Brazil"),
    League("Argentina Primera División", 128, "Americas", "Argentina"),
    League("Liga MX", 262, "Americas", "Mexico"),
]

LEAGUE_BY_NAME = {lg.name: lg for lg in LEAGUE_CATALOG}
LEAGUE_BY_ID = {lg.api_football_id: lg for lg in LEAGUE_CATALOG}
REGIONS = ["Europe", "International", "Asia", "Middle East", "Americas"]


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
    """Runtime settings. Loaded from env, overridable via the Settings page
    (persisted in the DB `settings` table at runtime)."""

    api_football_key: str = field(default_factory=lambda: os.getenv("API_FOOTBALL_KEY", ""))
    api_football_host: str = field(
        default_factory=lambda: os.getenv("API_FOOTBALL_HOST", "v3.football.api-sports.io")
    )
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Europe/Zurich"))
    lookahead_hours: int = field(default_factory=lambda: _as_int(os.getenv("LOOKAHEAD_HOURS"), 48))
    enabled_leagues: str = field(default_factory=lambda: os.getenv("ENABLED_LEAGUES", "ALL"))

    min_edge_pp: float = field(default_factory=lambda: _as_float(os.getenv("MIN_EDGE_PP"), 3.0))
    min_confidence: int = field(default_factory=lambda: _as_int(os.getenv("MIN_CONFIDENCE"), 60))
    min_liquidity_usd: float = field(
        default_factory=lambda: _as_float(os.getenv("MIN_LIQUIDITY_USD"), 500.0)
    )

    refresh_markets_seconds: int = field(
        default_factory=lambda: _as_int(os.getenv("REFRESH_MARKETS_SECONDS"), 300)
    )
    refresh_football_seconds: int = field(
        default_factory=lambda: _as_int(os.getenv("REFRESH_FOOTBALL_SECONDS"), 1800)
    )

    cache_ttl_fixtures: int = field(
        default_factory=lambda: _as_int(os.getenv("CACHE_TTL_FIXTURES"), 900)
    )
    cache_ttl_team_form: int = field(
        default_factory=lambda: _as_int(os.getenv("CACHE_TTL_TEAM_FORM"), 3600)
    )
    cache_ttl_standings: int = field(
        default_factory=lambda: _as_int(os.getenv("CACHE_TTL_STANDINGS"), 21600)
    )
    cache_ttl_markets: int = field(
        default_factory=lambda: _as_int(os.getenv("CACHE_TTL_MARKETS"), 120)
    )

    # Default ensemble weights. Must sum to ~1.0; the ensemble renormalises
    # automatically when a model is unavailable for a given match.
    weight_elo: float = 0.25
    weight_poisson: float = 0.30
    weight_xg: float = 0.25
    weight_form: float = 0.15
    weight_home: float = 0.05

    def enabled_league_objects(self) -> list[League]:
        raw = (self.enabled_leagues or "ALL").strip()
        if raw.upper() == "ALL":
            return list(LEAGUE_CATALOG)
        wanted = {n.strip().lower() for n in raw.split(",") if n.strip()}
        return [lg for lg in LEAGUE_CATALOG if lg.name.lower() in wanted]

    def model_weights(self) -> dict[str, float]:
        return {
            "elo": self.weight_elo,
            "poisson": self.weight_poisson,
            "xg": self.weight_xg,
            "form": self.weight_form,
            "home": self.weight_home,
        }


# A module-level singleton, refreshed from the DB at startup.
SETTINGS = Settings()
