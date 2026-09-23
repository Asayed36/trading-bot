"""Decision logic shared by the backtester and the live loop."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Sequence

from .broker import Broker
from .models import Bar, Order, Side, Signal, Trade
from .risk import RiskManager
from .strategies import Strategy

log = logging.getLogger(__name__)


class Trader:
    def __init__(
        self,
        strategy: Strategy,
        broker: Broker,
        risk: RiskManager,
        min_position_value: float = 1.0,
    ):
        self.strategy = strategy
        self.broker = broker
        self.risk = risk
        # Holdings worth less than this (in quote currency) count as flat, so
        # leftover exchange dust does not block new entries.
        self.min_position_value = min_position_value

    def has_position(self, price: float) -> bool:
        return self.broker.position * price >= self.min_position_value

    def decide(self, bars: Sequence[Bar]) -> Optional[Order]:
        """Look at the latest closed bar and decide whether to trade."""
        price = bars[-1].close
        self.risk.update_equity(self.broker.equity(price))
        in_position = self.has_position(price)

        if in_position:
            if self.risk.halted:
                return Order(Side.SELL, "max drawdown reached, trading halted")
            entry = self.broker.entry_price
            if entry is not None:
                reason = self.risk.exit_reason(entry, price)
                if reason:
                    return Order(Side.SELL, reason)

        signal = self.strategy.generate_signal(bars)
        if signal is Signal.BUY and not in_position and not self.risk.halted:
            return Order(Side.BUY, f"{self.strategy.name} buy signal")
        if signal is Signal.SELL and in_position:
            return Order(Side.SELL, f"{self.strategy.name} sell signal")
        return None

    def execute(self, order: Order, price: float, timestamp: datetime) -> Optional[Trade]:
        if order.side is Side.BUY:
            qty = self.risk.position_size(self.broker.equity(price), price)
            trade = self.broker.buy(qty, price, timestamp, order.reason)
        else:
            trade = self.broker.sell(self.broker.position, price, timestamp, order.reason)
        if trade:
            log.info(
                "%s %s %.6f @ %.4f fee=%.4f (%s)",
                trade.timestamp, trade.side.value.upper(), trade.quantity,
                trade.price, trade.fee, trade.reason,
            )
        return trade
