"""Form model.

Computes recent-form aggregates from a chronological list of a team's finished
matches, split by venue (all/home/away) and over multiple windows (5/10/20).
Also derives a simple form-based 1X2 estimate from points-per-game difference.

Every match passed in MUST have kicked off strictly before the fixture being
predicted — the caller (pipeline/backtest) is responsible for that filtering,
which is how we guarantee no look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FormSummary:
    window: int
    venue: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    gf: int = 0
    ga: int = 0
    xg: float | None = None     # None => unavailable (never faked)
    xga: float | None = None
    points: int = 0
    form_string: str = ""       # e.g. "WWDLW" (most recent last)

    @property
    def ppg(self) -> float:
        return self.points / self.played if self.played else 0.0

    @property
    def gf_pg(self) -> float:
        return self.gf / self.played if self.played else 0.0

    @property
    def ga_pg(self) -> float:
        return self.ga / self.played if self.played else 0.0

    def to_row(self) -> dict:
        return {
            "window": self.window,
            "venue": self.venue,
            "played": self.played,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "gf": self.gf,
            "ga": self.ga,
            "xg": self.xg,
            "xga": self.xga,
            "ppg": round(self.ppg, 2),
            "form_string": self.form_string,
        }


def _result_char(scored: int, conceded: int) -> tuple[str, int]:
    if scored > conceded:
        return "W", 3
    if scored == conceded:
        return "D", 1
    return "L", 0


def summarize(
    team_id: int,
    matches: list[dict],
    window: int,
    venue: str = "all",
) -> FormSummary:
    """matches: list of normalised finished fixtures (most recent first is OK;
    we sort by kickoff). venue filters to home/away games for `team_id`."""
    rel = []
    for m in matches:
        is_home = m["home_team_id"] == team_id
        is_away = m["away_team_id"] == team_id
        if not (is_home or is_away):
            continue
        if venue == "home" and not is_home:
            continue
        if venue == "away" and not is_away:
            continue
        rel.append(m)
    rel.sort(key=lambda m: m["kickoff_utc"])
    rel = rel[-window:]

    s = FormSummary(window=window, venue=venue)
    chars = []
    for m in rel:
        is_home = m["home_team_id"] == team_id
        scored = m["home_goals"] if is_home else m["away_goals"]
        conceded = m["away_goals"] if is_home else m["home_goals"]
        if scored is None or conceded is None:
            continue
        s.played += 1
        s.gf += scored
        s.ga += conceded
        ch, pts = _result_char(scored, conceded)
        chars.append(ch)
        s.points += pts
        if ch == "W":
            s.wins += 1
        elif ch == "D":
            s.draws += 1
        else:
            s.losses += 1
    s.form_string = "".join(chars)
    return s


def form_probabilities(home_ppg: float, away_ppg: float) -> dict[str, float]:
    """A light 1X2 estimate from PPG difference, via a logistic curve with a
    fixed draw share. Intentionally simple; the ensemble gives it low weight."""
    import math

    diff = home_ppg - away_ppg
    # logistic on ppg diff; scale chosen so a +1.0 ppg edge ~ 64% excl. draws
    p_home_excl = 1.0 / (1.0 + math.exp(-1.1 * diff))
    draw = 0.26  # football base draw rate
    home = p_home_excl * (1 - draw)
    away = (1 - p_home_excl) * (1 - draw)
    return {"home": home, "draw": draw, "away": away}
