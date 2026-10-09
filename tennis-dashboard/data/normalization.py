"""Player-name normalisation and fixture <-> Polymarket market matching.

Tennis names are messy across sources: "Djokovic N.", "Novak Djokovic",
"N. Djokovic", "Carlos Alcaraz Garfia". We normalise to a comparable token
form and match on **surname-first** signals, because the surname is the most
stable token. As with football, matching produces an explicit confidence and
low-confidence matches are NOT auto-assigned.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

# A few well-known aliases / spelling variants.
ALIASES: dict[str, str] = {
    "rafa nadal": "nadal",
    "novak djokovic": "djokovic",
    "carlos alcaraz garfia": "alcaraz",
    "stefanos tsitsipas": "tsitsipas",
    "daniil medvedev": "medvedev",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    """Lowercase, de-accent, drop punctuation. Collapses single-initial tokens
    (e.g. 'djokovic n' -> 'djokovic'). Returns a canonical token string."""
    if not name:
        return ""
    s = strip_accents(name).lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    tokens = [t for t in s.split() if t]
    # drop single-letter initials
    tokens = [t for t in tokens if len(t) > 1]
    s = " ".join(tokens).strip()
    return ALIASES.get(s, s)


def surname(name: str) -> str:
    """Heuristic surname extraction: for 'First Last' the last token; for
    'Last F.' the first token. We return the longest token as a robust proxy."""
    norm = normalize_name(name)
    if not norm:
        return ""
    tokens = norm.split()
    return max(tokens, key=len)


def _similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # surname agreement is a strong signal in tennis
    if surname(a) and surname(a) == surname(b):
        base = 0.92
    else:
        base = 0.0
    sa, sb = set(na.split()), set(nb.split())
    if sa and sb and (sa <= sb or sb <= sa):
        base = max(base, 0.9)
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    return max(base, ratio)


@dataclass
class MatchResult:
    confidence: float
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


def score_match(p1: str, p2: str, market_players: list[str],
                fixture_kickoff=None, market_time=None) -> MatchResult:
    """Score how well a Polymarket market corresponds to a fixture (2 players)."""
    if len(market_players) < 2:
        return MatchResult(0.0, "market has fewer than two identifiable players")
    m_a, m_b = market_players[0], market_players[1]
    direct = (_similarity(p1, m_a) + _similarity(p2, m_b)) / 2
    swapped = (_similarity(p1, m_b) + _similarity(p2, m_a)) / 2
    name_score = max(direct, swapped)

    time_factor = 1.0
    reason_time = "no times"
    fk, mk = _parse_dt(fixture_kickoff), _parse_dt(market_time)
    if fk and mk:
        hours = abs((fk - mk).total_seconds()) / 3600.0
        if hours <= 6:
            time_factor = 1.0
        elif hours <= 48:
            time_factor = max(0.6, 1.0 - (hours - 6) / 80.0)
        else:
            time_factor = 0.4
        reason_time = f"delta {hours:.1f}h"

    confidence = name_score * (0.8 + 0.2 * time_factor)
    return MatchResult(round(confidence, 4), f"name={name_score:.2f} ({reason_time})")


def extract_players_from_question(question: str) -> list[str]:
    """Pull two player names from a Polymarket question.
    Handles 'A vs B', 'A - B', 'Will A beat B?', 'A vs. B: ...'."""
    if not question:
        return []
    q = question.split(":", 1)[0].strip()
    for sep in [" vs. ", " vs ", " v ", " - ", " beat ", " defeat ", " def "]:
        low = q.lower()
        if sep in low:
            idx = low.index(sep)
            left = q[:idx].strip()
            right = q[idx + len(sep):].strip()
            left = re.sub(r"^(will|does)\s+", "", left, flags=re.I).strip()
            right = re.sub(r"[\?\.].*$", "", right).strip()
            if left and right:
                return [left, right]
    return []
