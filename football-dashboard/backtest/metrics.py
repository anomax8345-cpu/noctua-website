"""Aggregate backtest metrics built on top of models.calibration.

Given a list of scored predictions, compute the summary block the spec asks for:
Brier, Log Loss, Accuracy, ECE, ROI, Max Drawdown, Win Rate, Average Edge.

ROI here is a *paper* notion: if a matched market existed and the model's edge
exceeded a threshold, we simulate a 1-unit bet on the model's pick at the
market price and settle at the true outcome. This is for research only and is
clearly labelled as such throughout the UI.
"""
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
    prob_actual: float          # prob model gave to the actual outcome
    top_pick_hit: bool          # model's argmax was correct
    edge_pp: float | None       # model prob - market prob for the pick, in pp
    market_price: float | None  # 0..1 price of the model's pick, if matched
    won: bool | None            # did the model's pick happen (for ROI)


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
        return {
            "n": self.n,
            "brier": round(self.brier, 4) if self.brier is not None else None,
            "log_loss": round(self.log_loss, 4) if self.log_loss is not None else None,
            "accuracy": round(self.accuracy, 4) if self.accuracy is not None else None,
            "ece": round(self.ece, 4) if self.ece is not None else None,
            "roi": round(self.roi, 4) if self.roi is not None else None,
            "max_drawdown": round(self.max_drawdown, 4) if self.max_drawdown is not None else None,
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "avg_edge": round(self.avg_edge, 2) if self.avg_edge is not None else None,
            "buckets": self.buckets,
        }


def summarize(scored: list[ScoredPrediction], min_edge_pp: float = 3.0) -> BacktestSummary:
    s = BacktestSummary(n=len(scored))
    if not scored:
        return s

    pairs = [(sp.prob_actual, True) for sp in scored]  # prob_actual is prob of event that DID happen
    # For Brier/LogLoss of a probabilistic forecast of the realised outcome,
    # the "event" always happened, so we score prob_actual against 1.0. That
    # rewards giving high probability to what actually occurred.
    s.brier = brier_score(pairs)
    s.log_loss = log_loss(pairs)
    s.accuracy = sum(1 for sp in scored if sp.top_pick_hit) / len(scored)

    # Reliability uses the model's pick probability vs whether the pick won.
    rel_pairs = [
        (sp.market_price if False else _pick_prob(sp), bool(sp.won))
        for sp in scored
        if sp.won is not None
    ]
    # Use the top-pick probability against pick outcome for calibration curve.
    cal_pairs = [(_pick_prob(sp), sp.top_pick_hit) for sp in scored]
    s.ece = expected_calibration_error(cal_pairs)
    s.buckets = [b.to_row() for b in reliability_buckets(cal_pairs) if b.n]

    # Paper ROI over bets that passed the edge filter and had a market.
    bets = [
        sp for sp in scored
        if sp.edge_pp is not None and sp.market_price and sp.edge_pp >= min_edge_pp
        and sp.won is not None
    ]
    if bets:
        pnl_series = []
        cum = 0.0
        wins = 0
        for sp in bets:
            # buy YES on model's pick at market_price; payout 1 if it wins.
            pnl = (1.0 - sp.market_price) if sp.won else (-sp.market_price)
            cum += pnl
            pnl_series.append(cum)
            if sp.won:
                wins += 1
        staked = sum(sp.market_price for sp in bets)
        s.roi = cum / staked if staked else None
        s.win_rate = wins / len(bets)
        s.avg_edge = sum(sp.edge_pp for sp in bets) / len(bets)
        s.max_drawdown = _max_drawdown(pnl_series)
    return s


def _pick_prob(sp: ScoredPrediction) -> float:
    # If the top pick hit, prob_actual is the pick's prob; if it missed, the
    # pick's prob is 1 - prob_actual only in the 2-outcome sense, which is not
    # exact for 3-way. We store pick prob separately via prob_actual when hit;
    # for simplicity in the calibration curve we use prob_actual when hit and
    # (1 - prob_actual) otherwise as a monotone proxy.
    return sp.prob_actual if sp.top_pick_hit else max(0.0, 1.0 - sp.prob_actual)


def _max_drawdown(cum_series: list[float]) -> float:
    peak = cum_series[0]
    max_dd = 0.0
    for v in cum_series:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    return max_dd
