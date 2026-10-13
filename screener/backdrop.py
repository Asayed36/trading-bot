"""The market backdrop at the moment a token is first checked or bought, saved
for later analysis (candidates.csv and entries.csv). RECORDING ONLY: nothing
here is read by any buy, sell, filter or exit.

    btc_change_1h_pct   Bitcoin's price change over the last hour
    btc_change_24h_pct  Bitcoin's price change over the last 24 hours
    eth_change_1h_pct   Ethereum's price change over the last hour
    sol_change_1h_pct   Solana's price change over the last hour

Source: Binance's public market-data host data-api.binance.vision (the host
screener/trend.py already uses), the rolling-window ticker /api/v3/ticker for
BTCUSDT, ETHUSDT and SOLUSDT, priceChangePercent. No CoinGecko call, no key, no
header, public GET only. Two requests fetch everything: one with windowSize=1h
and one with windowSize=1d (a single request cannot mix the two windows).

The answer is cached for CACHE_MINUTES in memory and, when a cache_path is
given, in a small file (data/backdrop_cache.json, never committed) so another
process starts from it instead of asking again. At most 2 requests per 15
minutes per machine, however many tokens are checked, and none while nothing
is checked. A 5-second timeout; if it fails the values stay blank (blank = not
known, never zero) and it is tried again after RETRY_SECONDS. It never raises.

PAPER TRADING ONLY: a public read-only GET, no wallet, key or order.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import requests

URL = "https://data-api.binance.vision/api/v3/ticker"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CACHE_MINUTES = 15
RETRY_SECONDS = 60
TIMEOUT_SECONDS = 5

COLUMNS = ["btc_change_1h_pct", "btc_change_24h_pct", "eth_change_1h_pct", "sol_change_1h_pct"]
# (window, symbol, column)
FIELDS = [
    ("1h", "BTCUSDT", "btc_change_1h_pct"),
    ("1d", "BTCUSDT", "btc_change_24h_pct"),
    ("1h", "ETHUSDT", "eth_change_1h_pct"),
    ("1h", "SOLUSDT", "sol_change_1h_pct"),
]


def parse(window, tickers):
    """{column: percent} for one window from Binance's ticker list (only the
    values it gave)."""
    out = {}
    by_symbol = {t.get("symbol"): t for t in tickers if isinstance(t, dict)}
    for win, symbol, column in FIELDS:
        if win != window:
            continue
        try:
            value = float((by_symbol.get(symbol) or {})["priceChangePercent"])
        except (KeyError, TypeError, ValueError):
            continue
        if value == value and abs(value) != float("inf"):
            out[column] = round(value, 2)
    return out


class MarketBackdrop:
    """Callable: () -> {column: percent} (empty when unknown). Never raises."""

    def __init__(self, cache_path=None, timeout=TIMEOUT_SECONDS, get=requests.get, clock=None):
        self.cache_path, self.timeout, self.get = cache_path, timeout, get
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.values, self.fetched_at, self.failed_at = {}, None, None

    def __call__(self):
        try:
            return self._values()
        except Exception:      # logging only: a failure here must never reach the bot
            return {}

    def _fresh(self, when, now):
        return when is not None and timedelta(0) <= now - when < timedelta(minutes=CACHE_MINUTES)

    def _values(self):
        now = self.clock()
        if self._fresh(self.fetched_at, now):
            return self.values
        self._load(now)
        if self._fresh(self.fetched_at, now):
            return self.values
        if self.failed_at and now - self.failed_at < timedelta(seconds=RETRY_SECONDS):
            return {}
        values = {}
        for window in ("1h", "1d"):
            values.update(self._fetch(window))
        if not values:
            self.failed_at = now
            return {}
        self.values, self.fetched_at, self.failed_at = values, now, None
        self._save(values, now)
        return values

    def _fetch(self, window):
        try:
            resp = self.get(URL, params={"symbols": json.dumps(SYMBOLS, separators=(",", ":")),
                                         "windowSize": window}, timeout=self.timeout)
            return parse(window, resp.json()) if resp.status_code == 200 else {}
        except Exception:
            return {}

    # -- the small cache file (shared by the processes on one machine) --

    def _load(self, now):
        """Take the file's answer if it is under CACHE_MINUTES old."""
        if not self.cache_path:
            return
        try:
            with open(self.cache_path) as fh:
                saved = json.load(fh)
            when = datetime.fromisoformat(saved["fetched_at"])
            values = {k: float(v) for k, v in saved["values"].items() if k in COLUMNS}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return
        if values and self._fresh(when, now):
            self.values, self.fetched_at = values, when

    def _save(self, values, now):
        if not self.cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            tmp = f"{self.cache_path}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                json.dump({"fetched_at": now.isoformat(), "values": values}, fh)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass
