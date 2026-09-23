"""Replay historical bars through the same Trader used for live trading."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from .broker import PaperBroker
from .models import Bar, Side, Trade
from .risk import RiskConfig, RiskManager
from .strategies import Strategy
from .trader import Trader


@dataclass
class BacktestResult:
    initial_cash: float
    trades: list[Trade]
    equity_curve: list[tuple[datetime, float]]
    metrics: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        lines = [
            f"Initial equity     {self.initial_cash:>14,.2f}",
            f"Final equity       {m['final_equity']:>14,.2f}",
            f"Total return       {m['total_return']:>14.2%}",
            f"Buy & hold return  {m['buy_and_hold_return']:>14.2%}",
            f"Max drawdown       {m['max_drawdown']:>14.2%}",
            f"Sharpe ratio       {m['sharpe']:>14.2f}",
            f"Round trips        {int(m['round_trips']):>14d}",
            f"Win rate           {m['win_rate']:>14.2%}",
            f"Fees paid          {m['fees_paid']:>14,.2f}",
        ]
        return "\n".join(lines)


def run_backtest(
    bars: Sequence[Bar],
    strategy: Strategy,
    risk_config: RiskConfig | None = None,
    initial_cash: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage_pct: float = 0.0005,
    periods_per_year: float = 24 * 365,
) -> BacktestResult:
    """Run a backtest.

    Decisions are made on each bar's close and filled at the *next* bar's
    open, so the strategy never trades on a price it could not have seen.
    """
    if len(bars) < 2:
        raise ValueError("need at least 2 bars")
    broker = PaperBroker(initial_cash, fee_rate, slippage_pct)
    trader = Trader(strategy, broker, RiskManager(risk_config or RiskConfig()))
    window = strategy.lookback

    pending = None
    equity_curve: list[tuple[datetime, float]] = []
    for i, bar in enumerate(bars):
        if pending is not None:
            trader.execute(pending, bar.open, bar.timestamp)
            pending = None
        pending = trader.decide(bars[max(0, i + 1 - window): i + 1])
        equity_curve.append((bar.timestamp, broker.equity(bar.close)))

    result = BacktestResult(initial_cash, broker.trades, equity_curve)
    result.metrics = compute_metrics(result, bars, periods_per_year)
    return result


def compute_metrics(result: BacktestResult, bars: Sequence[Bar], periods_per_year: float) -> dict[str, float]:
    equities = [e for _, e in result.equity_curve]
    final = equities[-1]

    peak, max_dd = equities[0], 0.0
    for e in equities:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)

    returns = [b / a - 1 for a, b in zip(equities, equities[1:]) if a > 0]
    sharpe = 0.0
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        if var > 0:
            sharpe = mean / math.sqrt(var) * math.sqrt(periods_per_year)

    # Pair each sell with the buys before it to get round-trip P&L.
    pnls, cost_basis = [], 0.0
    for t in result.trades:
        if t.side is Side.BUY:
            cost_basis += t.price * t.quantity + t.fee
        else:
            pnls.append(t.price * t.quantity - t.fee - cost_basis)
            cost_basis = 0.0
    wins = sum(1 for p in pnls if p > 0)

    return {
        "final_equity": final,
        "total_return": final / result.initial_cash - 1,
        "buy_and_hold_return": bars[-1].close / bars[0].open - 1,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "round_trips": float(len(pnls)),
        "win_rate": wins / len(pnls) if pnls else 0.0,
        "fees_paid": sum(t.fee for t in result.trades),
    }
