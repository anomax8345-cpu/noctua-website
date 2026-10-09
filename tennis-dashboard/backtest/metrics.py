"""Aggregate backtest metrics (tennis, binary)."""
from __future__ import annotations

from dataclasses import dataclass, field

from models.calibration import (
    brier_score,
    expected_calibration_error,
    log_loss,
    reliability_buckets,
)


@dataclass
class ScoredPrediction:
    pick_prob: float            # prob model gave to its pick (>=0.5)
    pick_hit: bool              # did the pick win
    edge_pp: float | None
    market_price: float | None  # price of the model's pick, if matched
    won: bool | None


@dataclass
class BacktestSummary:
    n: int = 0
    brier: float | None = None
    log_loss: float | None = None
    accuracy: float | None = None
    ece: float | None = None
    roi: float | None = None
    max_drawdown: float | None = None
    win_rate: float | None = None
    avg_edge: float | None = None
    buckets: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        def r(x, n=4):
            return round(x, n) if x is not None else None
        return {
            "n": self.n, "brier": r(self.brier), "log_loss": r(self.log_loss),
            "accuracy": r(self.accuracy), "ece": r(self.ece), "roi": r(self.roi),
            "max_drawdown": r(self.max_drawdown), "win_rate": r(self.win_rate),
            "avg_edge": r(self.avg_edge, 2), "buckets": self.buckets,
        }


def summarize(scored: list[ScoredPrediction], min_edge_pp: float = 3.0) -> BacktestSummary:
    s = BacktestSummary(n=len(scored))
    if not scored:
        return s

    cal_pairs = [(sp.pick_prob, sp.pick_hit) for sp in scored]
    s.brier = brier_score(cal_pairs)
    s.log_loss = log_loss(cal_pairs)
    s.accuracy = sum(1 for sp in scored if sp.pick_hit) / len(scored)
    s.ece = expected_calibration_error(cal_pairs)
    s.buckets = [b.to_row() for b in reliability_buckets(cal_pairs) if b.n]

    bets = [sp for sp in scored
            if sp.edge_pp is not None and sp.market_price and sp.edge_pp >= min_edge_pp
            and sp.won is not None]
    if bets:
        cum = 0.0
        series = []
        wins = 0
        for sp in bets:
            pnl = (1.0 - sp.market_price) if sp.won else (-sp.market_price)
            cum += pnl
            series.append(cum)
            if sp.won:
                wins += 1
        staked = sum(sp.market_price for sp in bets)
        s.roi = cum / staked if staked else None
        s.win_rate = wins / len(bets)
        s.avg_edge = sum(sp.edge_pp for sp in bets) / len(bets)
        peak = series[0]
        dd = 0.0
        for v in series:
            peak = max(peak, v)
            dd = max(dd, peak - v)
        s.max_drawdown = dd
    return s
