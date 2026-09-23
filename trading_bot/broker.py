"""Brokers execute orders. PaperBroker simulates fills; CCXTBroker places real ones."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .models import Side, Trade

log = logging.getLogger(__name__)


class Broker(ABC):
    """Long-only, single-symbol broker interface."""

    @property
    @abstractmethod
    def cash(self) -> float: ...

    @property
    @abstractmethod
    def position(self) -> float:
        """Quantity of the base asset currently held."""

    @property
    @abstractmethod
    def entry_price(self) -> Optional[float]:
        """Average entry price of the open position, or None if flat."""

    @abstractmethod
    def buy(self, quantity: float, price: float, timestamp: datetime, reason: str) -> Optional[Trade]: ...

    @abstractmethod
    def sell(self, quantity: float, price: float, timestamp: datetime, reason: str) -> Optional[Trade]: ...

    def equity(self, price: float) -> float:
        return self.cash + self.position * price


class PaperBroker(Broker):
    """Simulated broker with proportional fees and slippage."""

    def __init__(self, cash: float = 10_000.0, fee_rate: float = 0.001, slippage_pct: float = 0.0005):
        if cash <= 0:
            raise ValueError("cash must be positive")
        self._cash = cash
        self._position = 0.0
        self._entry_price: Optional[float] = None
        self.fee_rate = fee_rate
        self.slippage_pct = slippage_pct
        self.trades: list[Trade] = []

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def position(self) -> float:
        return self._position

    @property
    def entry_price(self) -> Optional[float]:
        return self._entry_price

    def buy(self, quantity, price, timestamp, reason):
        fill = price * (1 + self.slippage_pct)
        # Never spend more cash than we have, fees included.
        quantity = min(quantity, self._cash / (fill * (1 + self.fee_rate)))
        if quantity <= 0:
            return None
        cost = quantity * fill
        fee = cost * self.fee_rate
        self._cash -= cost + fee
        total = self._position + quantity
        prev_cost = (self._entry_price or 0.0) * self._position
        self._entry_price = (prev_cost + cost) / total
        self._position = total
        return self._record(timestamp, Side.BUY, fill, quantity, fee, reason)

    def sell(self, quantity, price, timestamp, reason):
        quantity = min(quantity, self._position)
        if quantity <= 0:
            return None
        fill = price * (1 - self.slippage_pct)
        proceeds = quantity * fill
        fee = proceeds * self.fee_rate
        self._cash += proceeds - fee
        self._position -= quantity
        if self._position <= 1e-12:
            self._position = 0.0
            self._entry_price = None
        return self._record(timestamp, Side.SELL, fill, quantity, fee, reason)

    def _record(self, timestamp, side, price, quantity, fee, reason) -> Trade:
        trade = Trade(timestamp, side, price, quantity, fee, reason)
        self.trades.append(trade)
        return trade


class CCXTBroker(Broker):
    """Places real market orders on a crypto exchange through ccxt.

    Balances come from the exchange. The entry price is tracked in memory
    only, so stop-loss/take-profit do not survive a restart while a position
    is open.
    """

    def __init__(self, exchange, symbol: str):
        self.exchange = exchange
        self.symbol = symbol
        self.base, self.quote = symbol.split("/")[0], symbol.split("/")[1].split(":")[0]
        self._entry_price: Optional[float] = None
        self.exchange.load_markets()

    def _free(self, currency: str) -> float:
        balance = self.exchange.fetch_balance()
        return float(balance.get("free", {}).get(currency) or 0.0)

    @property
    def cash(self) -> float:
        return self._free(self.quote)

    @property
    def position(self) -> float:
        return self._free(self.base)

    @property
    def entry_price(self) -> Optional[float]:
        return self._entry_price

    def _submit(self, side: Side, quantity: float, timestamp, reason) -> Optional[Trade]:
        amount = float(self.exchange.amount_to_precision(self.symbol, quantity))
        if amount <= 0:
            return None
        log.warning("LIVE %s %s %s (%s)", side.value.upper(), amount, self.symbol, reason)
        order = self.exchange.create_order(self.symbol, "market", side.value, amount)
        filled = float(order.get("filled") or amount)
        avg = float(order.get("average") or order.get("price") or 0.0)
        fee = float((order.get("fee") or {}).get("cost") or 0.0)
        return Trade(timestamp, side, avg, filled, fee, reason)

    def buy(self, quantity, price, timestamp, reason):
        # Leave a small buffer for fees and price movement.
        affordable = self.cash * 0.995 / price
        trade = self._submit(Side.BUY, min(quantity, affordable), timestamp, reason)
        if trade:
            self._entry_price = trade.price or price
        return trade

    def sell(self, quantity, price, timestamp, reason):
        trade = self._submit(Side.SELL, min(quantity, self.position), timestamp, reason)
        if trade:
            self._entry_price = None
        return trade
