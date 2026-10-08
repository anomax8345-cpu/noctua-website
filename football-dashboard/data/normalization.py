"""Team-name normalisation and fixture <-> Polymarket market matching.

Matching is the single most safety-critical piece of the whole app: assigning
the wrong market to a fixture would silently corrupt every edge number. We
therefore combine several signals and produce an explicit confidence score.
A low score means "do NOT auto-assign" rather than "best guess".

Signals used:
  * normalised team-name similarity (both teams must match)
  * an alias table for well-known clubs
  * kickoff date/time proximity
  * (optionally) league agreement

No external fuzzy-matching dependency is used; difflib from the standard
library is enough and keeps the install small and auditable.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

# Aliases: map many spellings to one canonical normalised token set.
# Keys and values are raw strings; they are normalised before use.
ALIASES: dict[str, str] = {
    "bvb": "borussia dortmund",
    "dortmund": "borussia dortmund",
    "borussia dortmund": "borussia dortmund",
    "man united": "manchester united",
    "manchester utd": "manchester united",
    "man utd": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "werder": "werder bremen",
    "bremen": "werder bremen",
    "bayern": "bayern munich",
    "bayern münchen": "bayern munich",
    "fc bayern": "bayern munich",
    "gladbach": "borussia monchengladbach",
    "inter": "inter milan",
    "internazionale": "inter milan",
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "atleti": "atletico madrid",
    "atletico": "atletico madrid",
    "real": "real madrid",
    "barca": "barcelona",
    "fcb": "barcelona",
    "wolves": "wolverhampton",
    "wolverhampton wanderers": "wolverhampton",
    "sporting": "sporting cp",
    "sporting lisbon": "sporting cp",
    "ajax amsterdam": "ajax",
}

# Tokens stripped out before comparison (club-form noise that varies by source).
_NOISE = {
    "fc", "cf", "sc", "ac", "afc", "cfc", "sv", "vfb", "vfl", "tsg", "fsv",
    "ssc", "us", "ud", "cd", "club", "calcio", "if", "bk", "fk", "sk",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _clean(name: str) -> str:
    """Lowercase, de-accent, drop punctuation and common club-noise tokens.
    Does NOT apply alias substitution (used to build the alias map itself)."""
    if not name:
        return ""
    s = strip_accents(name).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t and t not in _NOISE]
    return " ".join(tokens).strip()


# Pre-normalise alias keys/values so lookups are robust to accents/punctuation
# (e.g. "Bayern München" and "bayern munchen" resolve the same way).
_ALIASES_NORMALIZED: dict[str, str] = {_clean(k): _clean(v) for k, v in ALIASES.items()}


def normalize_name(name: str) -> str:
    """Canonical team token string: cleaned, then alias-resolved."""
    cleaned = _clean(name)
    return _ALIASES_NORMALIZED.get(cleaned, cleaned)


def _similarity(a: str, b: str) -> float:
    a, b = normalize_name(a), normalize_name(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # token-set containment boosts e.g. "dortmund" vs "borussia dortmund"
    at, bt = set(a.split()), set(b.split())
    if at and bt and (at <= bt or bt <= at):
        base = 0.9
    else:
        base = 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return max(base, ratio)


@dataclass
class MatchResult:
    confidence: float  # 0..1
    reason: str

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.80

    @property
    def label(self) -> str:
        if self.confidence >= 0.95:
            return "HIGH"
        if self.confidence >= 0.80:
            return "MEDIUM"
        return "LOW"


def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def score_match(
    fixture_home: str,
    fixture_away: str,
    market_teams: list[str],
    fixture_kickoff=None,
    market_time=None,
) -> MatchResult:
    """Score how well a Polymarket market corresponds to a fixture.

    `market_teams` are the two team names extracted from the market question.
    Returns a MatchResult; callers must refuse auto-assignment when
    `is_confident` is False.
    """
    if len(market_teams) < 2:
        return MatchResult(0.0, "market has fewer than two identifiable teams")

    m_a, m_b = market_teams[0], market_teams[1]
    # Try both orientations (home/away order may differ between sources).
    direct = (_similarity(fixture_home, m_a) + _similarity(fixture_away, m_b)) / 2
    swapped = (_similarity(fixture_home, m_b) + _similarity(fixture_away, m_a)) / 2
    name_score = max(direct, swapped)

    # Time proximity: within 3h is ideal, degrade gently up to 36h.
    time_factor = 1.0
    reason_time = "no kickoff times to compare"
    fk, mk = _parse_dt(fixture_kickoff), _parse_dt(market_time)
    if fk and mk:
        hours = abs((fk - mk).total_seconds()) / 3600.0
        if hours <= 3:
            time_factor = 1.0
        elif hours <= 36:
            time_factor = max(0.6, 1.0 - (hours - 3) / 60.0)
        else:
            time_factor = 0.4
        reason_time = f"kickoff delta {hours:.1f}h"

    confidence = name_score * (0.75 + 0.25 * time_factor)
    reason = f"name={name_score:.2f} ({reason_time})"
    return MatchResult(round(confidence, 4), reason)


def extract_teams_from_question(question: str) -> list[str]:
    """Pull two team names out of a Polymarket question string.

    Handles the common patterns: "A vs B", "A - B", "Will A beat B?",
    "A vs. B: ...". Returns [] when it cannot confidently find two sides.
    """
    if not question:
        return []
    q = question.strip()
    # Cut trailing market-type qualifiers after a colon ("A vs B: Over 2.5")
    q = q.split(":", 1)[0]
    # Normalise common separators to " vs "
    for sep in [" vs. ", " vs ", " v ", " - ", " @ ", " beat ", " defeat "]:
        if sep in q.lower():
            idx = q.lower().index(sep)
            left = q[:idx].strip()
            right = q[idx + len(sep):].strip()
            # strip leading "Will "
            left = re.sub(r"^(will|does)\s+", "", left, flags=re.I).strip()
            right = re.sub(r"[\?\.].*$", "", right).strip()
            if left and right:
                return [left, right]
    return []
