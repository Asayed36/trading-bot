"""Polling loop for paper or live trading against real market data."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .trader import Trader

log = logging.getLogger(__name__)


def run_loop(
    trader: Trader,
    feed,
    poll_seconds: float = 60.0,
    max_iterations: Optional[int] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Act once per newly closed candle until interrupted.

    `feed` must provide `fetch_bars(limit) -> list[Bar]` returning closed bars.
    """
    last_seen = None
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        try:
            bars = feed.fetch_bars(trader.strategy.lookback)
            if bars and bars[-1].timestamp != last_seen:
                last_seen = bars[-1].timestamp
                price = bars[-1].close
                order = trader.decide(bars)
                log.info(
                    "candle %s close=%.4f equity=%.2f position=%.6f -> %s",
                    last_seen, price, trader.broker.equity(price), trader.broker.position,
                    order.side.value if order else "hold",
                )
                if order:
                    trader.execute(order, price, datetime.now(timezone.utc))
        except KeyboardInterrupt:
            raise
        except Exception:
            # Network hiccups and exchange errors should not kill the bot.
            log.exception("iteration failed; retrying next poll")
        if max_iterations is None or iterations < max_iterations:
            sleep(poll_seconds)
