"""Replays one strategy on one coin, one day at a time.

The rules every strategy lives by (they are what keeps the test honest):

* A decision is made at a daily CLOSE, using data up to and including that
  day, and is carried out at the NEXT day's OPEN. Nothing is ever bought at a
  price the strategy could not have seen.
* Every fill pays slippage against you (buy higher, sell lower) and a fee on
  the money traded, both per side.
* A stop is checked on the hourly candles inside each day. It fills at the
  stop price, but if a candle OPENS beyond the stop (a gap) it fills at that
  open instead, never at the better stop price. Slippage and fee come on top.
* Long only, no leverage, no shorting. Cash earns nothing.
* A position still open on the last day of a window is sold at that day's
  close (with costs), so every trade is closed and counted.
"""

from dataclasses import dataclass, field

from .data import EPOCH_ORDINAL


@dataclass
class Costs:
    fee: float          # per side, fraction of the money traded
    slippage: float     # per side, fraction of the price


@dataclass
class Decision:
    buy: bool = False
    sell: bool = False
    stop: float = None  # a new stop level for the next day (None: keep the current one)


@dataclass
class Trade:
    coin: str
    entry_i: int
    exit_i: int = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    reason: str = ""
    ret: float = 0.0    # net of costs, compounded over the days it was held
    first_day: int = 0
    last_day: int = 0


@dataclass
class Sleeve:
    """What one coin did over a window."""
    coin: str
    days: list = field(default_factory=list)       # day numbers
    ret: list = field(default_factory=list)        # the sleeve's return each day
    trade_of_day: list = field(default_factory=list)   # index into trades, or -1
    trades: list = field(default_factory=list)


def stop_fill(coin, i, stop):
    """Price a stop at `stop` fills at during daily candle i, or None if the
    day never reached it. A candle that opens beyond the stop fills at its open."""
    if coin.l[i] > stop:
        return None
    first, end = coin.day_hours[i]
    for k in range(first, end):
        if coin.h_low[k] <= stop:
            return min(stop, coin.h_open[k])
    return min(stop, coin.o[i])        # no hourly candles for that day: use the daily one


def simulate(coin, strategy, i_start, i_end, costs):
    """Run `strategy` on `coin` from daily candle i_start to i_end (inclusive).

    The first order is decided at the close of i_start - 1 (data known by then)
    and filled at the open of i_start; i_start must be at least 1."""
    strategy.prepare(coin)
    sleeve = Sleeve(coin.label)
    trades = sleeve.trades
    cash, units = 1.0, 0.0
    stop, stop_next, pending = None, None, None
    cur = -1                     # index of the open trade, or -1 when flat
    prev_equity = 1.0

    decision = strategy.on_close(i_start - 1, False)
    if decision.buy:
        pending, stop_next = "buy", decision.stop

    def close(i, price, reason):
        tr = trades[cur]
        tr.exit_i, tr.exit_price, tr.reason, tr.last_day = i, price, reason, coin.day[i]

    for i in range(i_start, i_end + 1):
        today = cur
        # 1. the order decided at yesterday's close, at today's open
        if pending == "buy" and cur < 0:
            price = coin.o[i] * (1 + costs.slippage)
            units, cash, stop = 1.0 * cash / (price * (1 + costs.fee)), 0.0, stop_next
            trades.append(Trade(coin.label, i, entry_price=price, first_day=coin.day[i]))
            cur = today = len(trades) - 1
        elif pending == "sell" and cur >= 0:
            price = coin.o[i] * (1 - costs.slippage)
            cash, units, stop = units * price * (1 - costs.fee), 0.0, None
            close(i, price, "signal")
            cur = -1
        pending = None

        # 2. a stop inside today's candles
        if cur >= 0 and stop is not None:
            fill = stop_fill(coin, i, stop)
            if fill is not None:
                price = fill * (1 - costs.slippage)
                cash, units, stop = units * price * (1 - costs.fee), 0.0, None
                close(i, price, "stop")
                cur = -1

        # 3. today's close: value the sleeve (selling on the very last day)
        if cur >= 0 and i == i_end:
            price = coin.c[i] * (1 - costs.slippage)
            cash, units = units * price * (1 - costs.fee), 0.0
            close(i, price, "end of window")
            cur = -1
        equity = cash + units * coin.c[i]
        sleeve.days.append(coin.day[i])
        sleeve.ret.append(equity / prev_equity - 1)
        sleeve.trade_of_day.append(today)
        prev_equity = equity

        # 4. the decision for tomorrow's open
        if i < i_end:
            decision = strategy.on_close(i, cur >= 0)
            if cur >= 0:
                if decision.stop is not None:
                    stop = decision.stop
                if decision.sell:
                    pending = "sell"
            elif decision.buy:
                pending, stop_next = "buy", decision.stop

    # each trade's net return: the days it was held, compounded
    growth = {}
    for r, idx in zip(sleeve.ret, sleeve.trade_of_day):
        if idx >= 0:
            growth[idx] = growth.get(idx, 1.0) * (1 + r)
    for k, tr in enumerate(trades):
        tr.ret = growth.get(k, 1.0) - 1
    return sleeve


def date_of_day(day_number):
    from datetime import date
    return date.fromordinal(EPOCH_ORDINAL + day_number)
