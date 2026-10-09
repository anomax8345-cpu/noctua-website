"""Form model (tennis).

Recent win rate over a window, optionally restricted to a surface. Produces a
light 2-way estimate from the win-rate difference. The caller must only pass
matches that occurred strictly before the fixture being predicted (no
look-ahead); the backtest engine and pipeline enforce that.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class FormSummary:
    window: int
    surface: str
    played: int = 0
    wins: int = 0
    losses: int = 0
    form_string: str = ""  # e.g. "WWLWL" (most recent last)

    @property
    def win_pct(self) -> float:
        return self.wins / self.played if self.played else 0.0

    def to_row(self) -> dict:
        return {
            "window": self.window,
            "surface": self.surface,
            "played": self.played,
            "wins": self.wins,
            "losses": self.losses,
            "win_pct": round(self.win_pct * 100, 1),
            "form_string": self.form_string,
        }


def summarize(player_id: str, matches: list[dict], window: int,
              surface: str | None = None) -> FormSummary:
    rel = []
    for m in matches:
        if surface and m.get("surface") != surface:
            continue
        if player_id not in (m.get("p1_id"), m.get("p2_id")):
            continue
        rel.append(m)
    rel.sort(key=lambda m: m["kickoff_utc"])
    rel = rel[-window:]

    s = FormSummary(window=window, surface=surface or "all")
    chars = []
    for m in rel:
        if m.get("winner") is None:
            continue
        is_p1 = m["p1_id"] == player_id
        won = (m["winner"] == "p1" and is_p1) or (m["winner"] == "p2" and not is_p1)
        s.played += 1
        if won:
            s.wins += 1
            chars.append("W")
        else:
            s.losses += 1
            chars.append("L")
    s.form_string = "".join(chars)
    return s


def form_probabilities(p1_win_pct: float, p2_win_pct: float) -> dict[str, float]:
    """2-way estimate from win-rate difference via a logistic curve."""
    diff = p1_win_pct - p2_win_pct  # in [-1, 1]
    p1 = 1.0 / (1.0 + math.exp(-2.2 * diff))
    return {"p1": p1, "p2": 1.0 - p1}
