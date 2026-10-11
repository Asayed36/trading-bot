"""The strategies, with every parameter written down here, before any result
was seen. A strategy is asked once per day, at the close, what to do at the
next open; it can only look at candles up to and including that day (its
indicators are built so that value i never depends on anything after i).

The grid that is tried (and nothing else):

  trend       3 variants: close above its 50-day average / 200-day average / both
  breakout    4 variants: N-day high (20 or 55) x ATR stop (2 or 3 ATRs)
  momentum    2 variants: top 3 coins by 30-day return, weekly; with or without
              the rule "only if that 30-day return is above zero"
  mean rev.   4 variants: RSI(2) or Laguerre RSI, with or without an ADX < 25 filter

That is 13 variants plus the buy-and-hold benchmark.
"""

from datetime import date

from . import indicators as ind
from .data import EPOCH_ORDINAL
from .engine import Decision

# every strategy needs this many daily candles of history before it trades
# (the longest average is 200 days); the same for all, so they are comparable
WARMUP_DAYS = 200

ATR_DAYS = 14
RSI_BUY, RSI_SELL = 10.0, 70.0             # RSI(2): buy below 10, sell above 70
LAGUERRE_BUY, LAGUERRE_SELL = 0.10, 0.70   # Laguerre RSI (gamma 0.5), same idea
ADX_MAX = 25.0                             # the "ranging market" filter
MEAN_REVERSION_STOP_ATR = 3.0
MEAN_REVERSION_MAX_DAYS = 10
MOMENTUM_LOOKBACK = 30
MOMENTUM_TOP = 3


class Strategy:
    family = ""
    name = ""

    def prepare(self, coin):
        """Work out the indicators for this coin (called once per run)."""
        self.coin = coin

    def on_close(self, i, in_position):
        raise NotImplementedError


class BuyHold(Strategy):
    family, name = "buy-and-hold", "buy-and-hold"

    def on_close(self, i, in_position):
        return Decision(buy=not in_position)


class TrendFollowing(Strategy):
    """Hold only while the close is above its moving average(s)."""
    family = "trend following"

    def __init__(self, averages):
        self.averages = tuple(averages)
        self.name = "close above " + " and ".join(f"{n}-day average" for n in self.averages)

    def prepare(self, coin):
        super().prepare(coin)
        self.sma = [ind.sma(coin.c, n) for n in self.averages]

    def on_close(self, i, in_position):
        above = all(s[i] is not None and self.coin.c[i] > s[i] for s in self.sma)
        if in_position:
            return Decision(sell=not above)
        return Decision(buy=above)


class Breakout(Strategy):
    """Buy a new N-day high; a trailing stop k ATRs below the highest close
    since the buy (it only moves up). Sold only by that stop."""
    family = "breakout"

    def __init__(self, days, atrs):
        self.days, self.atrs = days, atrs
        self.name = f"{days}-day high, {atrs:g} ATR trailing stop"

    def prepare(self, coin):
        super().prepare(coin)
        self.high_before = ind.highest_before(coin.h, self.days)
        self.atr = ind.atr(coin.h, coin.l, coin.c, ATR_DAYS)
        self.top = self.stop = None

    def on_close(self, i, in_position):
        c, atr = self.coin.c[i], self.atr[i]
        if in_position and self.stop is not None:
            self.top = max(self.top, c)
            if atr is not None:
                self.stop = max(self.stop, self.top - self.atrs * atr)
            return Decision(stop=self.stop)
        self.top = self.stop = None
        if atr is not None and self.high_before[i] is not None and c > self.high_before[i]:
            self.top = c
            self.stop = c - self.atrs * atr
            return Decision(buy=True, stop=self.stop)
        return Decision()


class MeanReversion(Strategy):
    """Buy a short-term oversold reading (only when the market is ranging,
    if the ADX filter is on); sell when it recovers, after 10 days, or at a
    stop 3 ATRs below the buy."""
    family = "mean reversion"

    def __init__(self, oscillator, adx_filter):
        self.oscillator, self.adx_filter = oscillator, adx_filter
        label = "RSI(2)" if oscillator == "rsi" else "Laguerre RSI"
        self.name = label + (f", only when ADX < {ADX_MAX:g}" if adx_filter else ", no ADX filter")

    def prepare(self, coin):
        super().prepare(coin)
        if self.oscillator == "rsi":
            self.osc, self.buy_below, self.sell_above = ind.rsi(coin.c, 2), RSI_BUY, RSI_SELL
        else:
            self.osc = ind.laguerre_rsi(coin.c, 0.5)
            self.buy_below, self.sell_above = LAGUERRE_BUY, LAGUERRE_SELL
        self.atr = ind.atr(coin.h, coin.l, coin.c, ATR_DAYS)
        self.adx = ind.adx(coin.h, coin.l, coin.c, ATR_DAYS)
        self.signal_i = None

    def on_close(self, i, in_position):
        value = self.osc[i]
        if in_position:
            if value is not None and value > self.sell_above:
                return Decision(sell=True)
            if self.signal_i is not None and i - self.signal_i >= MEAN_REVERSION_MAX_DAYS:
                return Decision(sell=True)
            return Decision(stop=self.stop)
        self.signal_i = None
        if value is None or self.atr[i] is None or value >= self.buy_below:
            return Decision()
        if self.adx_filter and (self.adx[i] is None or self.adx[i] >= ADX_MAX):
            return Decision()
        self.signal_i = i
        self.stop = self.coin.c[i] - MEAN_REVERSION_STOP_ATR * self.atr[i]
        return Decision(buy=True, stop=self.stop)


class Scheduled(Strategy):
    """Follows a fixed schedule worked out beforehand from all the coins
    (used by momentum, which ranks the coins against each other):
    schedule[day] is True/False = hold/don't hold from the next open."""
    family = "momentum"

    def __init__(self, name, schedule):
        self.name, self.schedule = name, schedule

    def on_close(self, i, in_position):
        want = self.schedule.get(self.coin.day[i])
        if want is None:
            return Decision()
        if in_position:
            return Decision(sell=not want)
        return Decision(buy=want)


def momentum_schedules(coins, positive_only, lookback=MOMENTUM_LOOKBACK, top=MOMENTUM_TOP):
    """For every Sunday close: rank the coins that have WARMUP_DAYS of history
    by their `lookback`-day return, hold the best `top` (only those up over the
    period, if positive_only) until the next Sunday. Returns {label: {day: bool}}.
    Uses only candles up to that Sunday."""
    close = {c.label: dict(zip(c.day, c.c)) for c in coins}
    first = {c.label: c.day[WARMUP_DAYS] if len(c) > WARMUP_DAYS else None for c in coins}
    all_days = sorted({d for c in coins for d in c.day})
    schedules = {c.label: {} for c in coins}
    for day in all_days:
        if date.fromordinal(EPOCH_ORDINAL + day).weekday() != 6:     # Sunday's candle closes Monday 00:00
            continue
        ranked = []
        for c in coins:
            if first[c.label] is None or day < first[c.label]:
                continue
            now, then = close[c.label].get(day), close[c.label].get(day - lookback)
            if now is None or then is None:
                continue
            ranked.append((now / then - 1, c.label))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        chosen = {label for r, label in ranked[:top] if r > 0 or not positive_only}
        for r, label in ranked:
            schedules[label][day] = label in chosen
    return schedules


def families():
    """The whole grid, by family: {family: [factory]} where each factory builds
    a fresh strategy (momentum ones need the coins: see runner)."""
    return {
        "trend following": [lambda: TrendFollowing((50,)), lambda: TrendFollowing((200,)),
                            lambda: TrendFollowing((50, 200))],
        "breakout": [(lambda n=n, k=k: Breakout(n, k)) for n in (20, 55) for k in (2, 3)],
        "mean reversion": [(lambda o=o, a=a: MeanReversion(o, a))
                           for o in ("rsi", "laguerre") for a in (False, True)],
    }


MOMENTUM_VARIANTS = (("top 3 by 30-day return", False),
                     ("top 3 by 30-day return, only if it is above zero", True))
