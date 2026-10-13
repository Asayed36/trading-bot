"""The market backdrop at the moment a token is first checked or bought, saved
for later analysis (candidates.csv and entries.csv). RECORDING ONLY: nothing
here is read by any buy, sell, filter or exit.

    btc_change_1h_pct   Bitcoin's price change over the last hour
    btc_change_24h_pct  Bitcoin's price change over the last 24 hours
    eth_change_1h_pct   Ethereum's price change over the last hour
    sol_change_1h_pct   Solana's price change over the last hour

One public CoinGecko request (the same free data source screener/btc.py uses
for Bitcoin; with the demo key when there is one) covers all four values and
is cached for CACHE_MINUTES, so a bot makes at most 12 requests an hour
however many tokens it checks, and none while it checks nothing. A short
timeout; if it fails the values stay blank (blank = not known, never zero) and
it is tried again after RETRY_SECONDS. It never raises.

PAPER TRADING ONLY: a public read-only GET, no wallet, key or order.
"""

import os
from datetime import datetime, timedelta, timezone

import requests

URL = "https://api.coingecko.com/api/v3/coins/markets"
CACHE_MINUTES = 5
RETRY_SECONDS = 60
TIMEOUT_SECONDS = 5

COLUMNS = ["btc_change_1h_pct", "btc_change_24h_pct", "eth_change_1h_pct", "sol_change_1h_pct"]
# CoinGecko coin id -> (column, CoinGecko's field)
FIELDS = [
    ("bitcoin", "btc_change_1h_pct", "price_change_percentage_1h_in_currency"),
    ("bitcoin", "btc_change_24h_pct", "price_change_percentage_24h_in_currency"),
    ("ethereum", "eth_change_1h_pct", "price_change_percentage_1h_in_currency"),
    ("solana", "sol_change_1h_pct", "price_change_percentage_1h_in_currency"),
]


def parse(coins):
    """{column: percent} from CoinGecko's /coins/markets list (only the values it gave)."""
    by_id = {c.get("id"): c for c in coins if isinstance(c, dict)}
    out = {}
    for coin, column, field in FIELDS:
        value = (by_id.get(coin) or {}).get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[column] = round(float(value), 2)
    return out


class MarketBackdrop:
    """Callable: () -> {column: percent} (empty when unknown). Never raises."""

    def __init__(self, key=None, timeout=TIMEOUT_SECONDS, get=requests.get, clock=None):
        self.key = key if key is not None else os.environ.get("COINGECKO_API_KEY")
        self.timeout, self.get = timeout, get
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.values, self.fetched_at, self.failed_at = {}, None, None

    def __call__(self):
        now = self.clock()
        if self.fetched_at and now - self.fetched_at < timedelta(minutes=CACHE_MINUTES):
            return self.values
        if self.failed_at and now - self.failed_at < timedelta(seconds=RETRY_SECONDS):
            return {}
        headers = {"x-cg-demo-api-key": self.key} if self.key else None
        try:
            resp = self.get(URL, params={"vs_currency": "usd", "ids": "bitcoin,ethereum,solana",
                                         "price_change_percentage": "1h,24h"},
                            headers=headers, timeout=self.timeout)
            values = parse(resp.json()) if resp.status_code == 200 else {}
        except Exception:      # logging only: a failure here must never reach the bot
            values = {}
        if not values:
            self.failed_at = now
            return {}
        self.values, self.fetched_at, self.failed_at = values, now, None
        return values
