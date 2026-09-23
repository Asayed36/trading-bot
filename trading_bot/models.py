"""Core data types shared across the bot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Bar:
    """One OHLCV candle."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Order:
    """An intent to trade, produced by the Trader and filled by a Broker."""

    side: Side
    reason: str


@dataclass(frozen=True)
class Trade:
    """A filled order."""

    timestamp: datetime
    side: Side
    price: float
    quantity: float
    fee: float
    reason: str
