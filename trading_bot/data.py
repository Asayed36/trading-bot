"""Market data: CSV files, synthetic prices, and live exchange candles via ccxt."""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import Bar

CSV_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")


def _parse_timestamp(value: str) -> datetime:
    value = value.strip()
    try:
        number = float(value)
    except ValueError:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    # Treat large numbers as milliseconds (what exchanges usually return).
    if number > 1e11:
        number /= 1000
    return datetime.fromtimestamp(number, tz=timezone.utc)


def load_csv(path: str | Path) -> list[Bar]:
    """Load bars from a CSV with columns timestamp,open,high,low,close[,volume]."""
    bars = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fields = {name.lower().strip(): name for name in reader.fieldnames or []}
        missing = [c for c in CSV_FIELDS[:5] if c not in fields]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        for row in reader:
            bars.append(
                Bar(
                    timestamp=_parse_timestamp(row[fields["timestamp"]]),
                    open=float(row[fields["open"]]),
                    high=float(row[fields["high"]]),
                    low=float(row[fields["low"]]),
                    close=float(row[fields["close"]]),
                    volume=float(row[fields["volume"]]) if "volume" in fields else 0.0,
                )
            )
    bars.sort(key=lambda b: b.timestamp)
    return bars


def save_csv(bars: Iterable[Bar], path: str | Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_FIELDS)
        for b in bars:
            writer.writerow([b.timestamp.isoformat(), b.open, b.high, b.low, b.close, b.volume])


def generate_synthetic(
    n: int = 1000,
    start_price: float = 100.0,
    drift: float = 0.00005,
    volatility: float = 0.006,
    seed: int | None = 42,
    interval: timedelta = timedelta(hours=1),
    start: datetime = datetime(2024, 1, 1, tzinfo=timezone.utc),
) -> list[Bar]:
    """Random-walk (geometric Brownian motion) prices for testing without data."""
    rng = random.Random(seed)
    bars = []
    price = start_price
    for i in range(n):
        open_ = price
        close = open_ * math.exp(drift - volatility**2 / 2 + volatility * rng.gauss(0, 1))
        high = max(open_, close) * (1 + abs(rng.gauss(0, volatility / 3)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, volatility / 3)))
        bars.append(Bar(start + i * interval, open_, high, low, close, rng.uniform(100, 1000)))
        price = close
    return bars


def make_exchange(exchange_id: str, api_key: str | None = None, secret: str | None = None, sandbox: bool = False):
    """Create a ccxt exchange client. Requires `pip install ccxt`."""
    try:
        import ccxt
    except ImportError:
        raise SystemExit("This command needs ccxt: pip install ccxt") from None
    try:
        cls = getattr(ccxt, exchange_id)
    except AttributeError:
        raise SystemExit(f"unknown exchange {exchange_id!r}") from None
    config = {"enableRateLimit": True}
    if api_key:
        config.update(apiKey=api_key, secret=secret)
    exchange = cls(config)
    if sandbox:
        exchange.set_sandbox_mode(True)
    return exchange


class ExchangeFeed:
    """Fetches closed candles from an exchange through ccxt."""

    def __init__(self, exchange, symbol: str, timeframe: str = "1h"):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe

    def fetch_bars(self, limit: int) -> list[Bar]:
        # Ask for one extra because the newest candle is still forming.
        rows = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit + 1)
        bars = [
            Bar(datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc), *map(float, r[1:6]))
            for r in rows
        ]
        return bars[:-1]
