"""Trading strategies.

A strategy only looks at price history and returns a Signal. It knows nothing
about cash, positions or risk; the Trader combines its signal with the
RiskManager and Broker to decide what actually happens.

To add a strategy: subclass Strategy, implement `lookback` and
`generate_signal`, and register it in STRATEGIES.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from .models import Bar, Signal


def sma(values: Sequence[float], period: int) -> float:
    """Simple moving average of the last `period` values."""
    if period <= 0 or len(values) < period:
        raise ValueError(f"need at least {period} values, got {len(values)}")
    return sum(values[-period:]) / period


def rsi(values: Sequence[float], period: int) -> float:
    """Relative Strength Index over the last `period` changes (simple averages)."""
    if len(values) < period + 1:
        raise ValueError(f"need at least {period + 1} values, got {len(values)}")
    window = values[-(period + 1):]
    gains = losses = 0.0
    for prev, cur in zip(window, window[1:]):
        change = cur - prev
        if change > 0:
            gains += change
        else:
            losses -= change
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


class Strategy(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def lookback(self) -> int:
        """Number of most recent bars the strategy needs to produce a signal."""

    @abstractmethod
    def generate_signal(self, bars: Sequence[Bar]) -> Signal:
        """Return a signal based on `bars` (oldest first, last one just closed)."""


class SMACrossover(Strategy):
    """Buy when the fast SMA crosses above the slow SMA; sell on the cross below."""

    name = "sma_crossover"

    def __init__(self, fast: int = 10, slow: int = 30):
        if not 0 < fast < slow:
            raise ValueError("require 0 < fast < slow")
        self.fast = fast
        self.slow = slow

    @property
    def lookback(self) -> int:
        return self.slow + 1

    def generate_signal(self, bars: Sequence[Bar]) -> Signal:
        if len(bars) < self.lookback:
            return Signal.HOLD
        closes = [b.close for b in bars[-self.lookback:]]
        prev = closes[:-1]
        fast_now, slow_now = sma(closes, self.fast), sma(closes, self.slow)
        fast_prev, slow_prev = sma(prev, self.fast), sma(prev, self.slow)
        if fast_prev <= slow_prev and fast_now > slow_now:
            return Signal.BUY
        if fast_prev >= slow_prev and fast_now < slow_now:
            return Signal.SELL
        return Signal.HOLD

    def __repr__(self) -> str:
        return f"SMACrossover(fast={self.fast}, slow={self.slow})"


class RSIMeanReversion(Strategy):
    """Buy when RSI drops below `oversold`; sell when it rises above `overbought`."""

    name = "rsi"

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        if period <= 0:
            raise ValueError("period must be positive")
        if not 0 <= oversold < overbought <= 100:
            raise ValueError("require 0 <= oversold < overbought <= 100")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    @property
    def lookback(self) -> int:
        return self.period + 1

    def generate_signal(self, bars: Sequence[Bar]) -> Signal:
        if len(bars) < self.lookback:
            return Signal.HOLD
        value = rsi([b.close for b in bars[-self.lookback:]], self.period)
        if value < self.oversold:
            return Signal.BUY
        if value > self.overbought:
            return Signal.SELL
        return Signal.HOLD

    def __repr__(self) -> str:
        return (
            f"RSIMeanReversion(period={self.period}, oversold={self.oversold}, "
            f"overbought={self.overbought})"
        )


STRATEGIES: dict[str, type[Strategy]] = {
    SMACrossover.name: SMACrossover,
    RSIMeanReversion.name: RSIMeanReversion,
}


def build_strategy(name: str, **params) -> Strategy:
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"unknown strategy {name!r}; choose from {', '.join(sorted(STRATEGIES))}"
        ) from None
    return cls(**params)
