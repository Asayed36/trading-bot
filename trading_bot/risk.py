"""Position sizing and protective exits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskConfig:
    # Fraction of current equity committed to each new position.
    position_size_pct: float = 0.95
    # Exit when price falls this fraction below the entry price. None disables.
    stop_loss_pct: Optional[float] = 0.05
    # Exit when price rises this fraction above the entry price. None disables.
    take_profit_pct: Optional[float] = 0.10
    # Stop opening new positions (and flatten) once equity falls this fraction
    # below its peak. None disables.
    max_drawdown_pct: Optional[float] = 0.25

    def __post_init__(self) -> None:
        if not 0 < self.position_size_pct <= 1:
            raise ValueError("position_size_pct must be in (0, 1]")
        for name in ("stop_loss_pct", "take_profit_pct", "max_drawdown_pct"):
            value = getattr(self, name)
            if value is not None and not 0 < value < 1:
                raise ValueError(f"{name} must be in (0, 1) or None")


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self.peak_equity: Optional[float] = None
        self.halted = False

    def update_equity(self, equity: float) -> None:
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        limit = self.config.max_drawdown_pct
        if limit is not None and self.peak_equity > 0:
            if (self.peak_equity - equity) / self.peak_equity >= limit:
                self.halted = True

    def position_size(self, equity: float, price: float) -> float:
        if price <= 0:
            raise ValueError("price must be positive")
        return equity * self.config.position_size_pct / price

    def exit_reason(self, entry_price: float, price: float) -> Optional[str]:
        """Return why an open position should be closed, or None to keep it."""
        change = (price - entry_price) / entry_price
        sl = self.config.stop_loss_pct
        tp = self.config.take_profit_pct
        if sl is not None and change <= -sl:
            return f"stop loss ({change:.2%})"
        if tp is not None and change >= tp:
            return f"take profit ({change:.2%})"
        return None
