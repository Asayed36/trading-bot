"""Turns the per-coin results into one portfolio, and measures it.

How the portfolio is built (the same for every strategy and for the
buy-and-hold benchmark, so they are comparable):

* independent strategies (trend, breakout, mean reversion, buy-and-hold):
  every day the money is split equally between the coins that have enough
  history (200 days); each coin's share is in that coin while its rule says
  so and in cash otherwise. Moving money between the coins' shares is free
  (a simplification that treats the strategy and the benchmark alike).
* momentum: three equal slots; a slot holds one of the chosen coins or cash.

Total return compounds the portfolio's daily returns. Costs are already
inside each coin's daily returns (fee and slippage on every fill).
"""

import math

from .data import DAY_MS, EPOCH_ORDINAL
from .engine import Costs, simulate
from .strategies import WARMUP_DAYS
from .universe import FEE, slippage

DAYS_PER_YEAR = 365


class Run:
    """All the coins' results for one strategy over one window."""

    def __init__(self, sleeves, slots=None):
        self.sleeves = sleeves                 # {label: Sleeve}
        self.slots = slots                     # None: split between the eligible coins; n: n fixed slots
        count = {}
        for s in sleeves.values():
            for d in s.days:
                count[d] = count.get(d, 0) + 1
        self.eligible = count
        self.days = sorted(count)

    def weight(self, day):
        return 1.0 / (self.slots or self.eligible[day])

    def daily_returns(self, drop=()):
        """(days, portfolio return per day); `drop` = {(coin, trade index)} left out."""
        total = {d: 0.0 for d in self.days}
        for label, s in self.sleeves.items():
            for d, r, idx in zip(s.days, s.ret, s.trade_of_day):
                if (label, idx) in drop:
                    continue
                total[d] += r * self.weight(d)
        return self.days, [total[d] for d in self.days]

    def trades(self):
        """[(label, index, Trade)] of every trade, all coins."""
        return [(label, k, t) for label, s in self.sleeves.items() for k, t in enumerate(s.trades)]

    def contributions(self):
        """{(label, index): how much the trade added to the portfolio's daily returns}."""
        out = {}
        for label, s in self.sleeves.items():
            for d, r, idx in zip(s.days, s.ret, s.trade_of_day):
                if idx >= 0:
                    out[(label, idx)] = out.get((label, idx), 0.0) + r * self.weight(d)
        return out


def run_strategy(coins, build, window_start, window_end):
    """Replay a strategy on every coin: `build(coin)` makes a fresh strategy
    for it. `window_*` are dates. A coin takes part from its 201st daily candle."""
    start_day = window_start.toordinal() - EPOCH_ORDINAL
    end_day = window_end.toordinal() - EPOCH_ORDINAL
    sleeves = {}
    for coin in coins:
        i_end = coin.index_on_or_after(end_day + 1) - 1
        i_start = max(coin.index_on_or_after(start_day), WARMUP_DAYS)
        if i_end < i_start:
            continue
        sleeves[coin.label] = simulate(coin, build(coin), i_start, i_end,
                                       Costs(FEE, slippage(coin.label)))
    return sleeves


# ---- measures ---------------------------------------------------------

def equity_curve(returns):
    out, value = [], 1.0
    for r in returns:
        value *= 1 + r
        out.append(value)
    return out


def total_return(returns):
    value = 1.0
    for r in returns:
        value *= 1 + r
    return value - 1


def max_drawdown(returns):
    """The worst fall from a peak, as a negative fraction (0 if none)."""
    peak, worst, value = 1.0, 0.0, 1.0
    for r in returns:
        value *= 1 + r
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def sharpe(returns):
    """Annualised mean / standard deviation of daily returns (no risk-free rate)."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return 0.0 if var <= 0 else mean / math.sqrt(var) * math.sqrt(DAYS_PER_YEAR)


def paired_t(run, other):
    """t-statistic of the daily return difference between two runs over the days
    they share: how many standard errors the average gap is from zero. Below
    about 2 (in size), a gap this big could easily be luck. None if undefined."""
    a_days, a = run.daily_returns()
    b_days, b = other.daily_returns()
    b_by_day = dict(zip(b_days, b))
    diffs = [x - b_by_day[d] for d, x in zip(a_days, a) if d in b_by_day]
    n = len(diffs)
    if n < 2:
        return None
    mean = sum(diffs) / n
    var = sum((x - mean) ** 2 for x in diffs) / (n - 1)
    return None if var <= 0 else mean / math.sqrt(var / n)


def cagr(returns):
    if not returns:
        return 0.0
    growth = 1 + total_return(returns)
    return growth ** (DAYS_PER_YEAR / len(returns)) - 1 if growth > 0 else -1.0


def yearly(days, returns):
    """{year: total return of that calendar year (days inside the window only)}."""
    from datetime import date
    groups = {}
    for d, r in zip(days, returns):
        groups.setdefault(date.fromordinal(EPOCH_ORDINAL + d).year, []).append(r)
    return {y: total_return(rs) for y, rs in sorted(groups.items())}


def trade_stats(trades):
    rets = [t.ret for _, _, t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    return {
        "trades": len(rets),
        "win_rate": len(wins) / len(rets) if rets else None,
        "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
        "average_trade": sum(rets) / len(rets) if rets else None,
        "average_days_held": (sum(t.exit_i - t.entry_i + 1 for _, _, t in trades) / len(rets)
                              if rets else None),
    }


def measure(run):
    """Everything reported about one run (a dict of plain numbers)."""
    days, returns = run.daily_returns()
    trades = run.trades()
    contribution = run.contributions()
    ranked = sorted(contribution, key=contribution.get, reverse=True)
    sleeve_days = sum(len(s.days) for s in run.sleeves.values())
    in_market = sum(1 for s in run.sleeves.values() for idx in s.trade_of_day if idx >= 0)
    out = {
        "from": _iso(days[0]) if days else None, "to": _iso(days[-1]) if days else None,
        "days": len(days), "coins": len(run.sleeves),
        "total_return": total_return(returns), "max_drawdown": max_drawdown(returns),
        "sharpe": sharpe(returns), "cagr": cagr(returns),
        "time_in_market": in_market / sleeve_days if sleeve_days else None,
        "yearly": yearly(days, returns),
    }
    out.update(trade_stats(trades))
    for k in (1, 3):
        _, rs = run.daily_returns(drop=set(ranked[:k]))
        out[f"total_return_without_best_{k}"] = total_return(rs)
    if ranked:
        label, idx = ranked[0]
        best = run.sleeves[label].trades[idx]
        out["best_trade"] = {"coin": label, "from": _iso(best.first_day), "to": _iso(best.last_day),
                             "return": best.ret}
    return out


def _iso(day):
    from datetime import date
    return date.fromordinal(EPOCH_ORDINAL + day).isoformat()


def trade_rows(run, strategy_name):
    rows = []
    for label, k, t in run.trades():
        rows.append({"strategy": strategy_name, "coin": label,
                     "bought": _iso(t.first_day), "sold": _iso(t.last_day),
                     "buy_price": t.entry_price, "sell_price": t.exit_price,
                     "net_return": t.ret, "ended_by": t.reason})
    rows.sort(key=lambda r: (r["bought"], r["coin"]))
    return rows
