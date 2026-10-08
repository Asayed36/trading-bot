"""Bitcoin's trend, saved with every paper buy (entries.csv's btc_* columns),
so results can later be split by market direction. Logging only: it never
changes what is bought.

    btc_close_usd       Bitcoin's last daily close (00:00 UTC, CoinGecko)
    btc_200d_avg_usd    the average of its last 200 daily closes
    btc_vs_200d         "above" or "below" that average
    btc_7d_change_pct   % change of the daily close over the last 7 days

One CoinGecko request a day per bot (read-only, free API; with the demo key
when there is one), at the first buy of the UTC day. If it fails, the
columns stay blank and it's tried again at a buy at least 30 minutes later.
"""

import os
from datetime import datetime, timedelta, timezone

import requests

URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
RETRY_MINUTES = 30


def trend(prices):
    """The four values from CoinGecko's daily [ms, price] points. The last
    point is "now" (not a close) unless it falls exactly on 00:00 UTC."""
    closes = []
    for ms, price in prices or []:
        when = datetime.fromtimestamp(ms / 1000, timezone.utc)
        if (when.hour, when.minute, when.second) == (0, 0, 0) and price:
            closes.append(float(price))
    if len(closes) < 8:
        return {}
    close = closes[-1]
    week = (close / closes[-8] - 1) * 100
    values = {"btc_close_usd": round(close, 2), "btc_7d_change_pct": round(week, 2)}
    if len(closes) >= 200:
        avg = sum(closes[-200:]) / 200
        values.update(btc_200d_avg_usd=round(avg, 2),
                      btc_vs_200d="above" if close > avg else "below")
    return values


class BtcTrend:
    """Callable: () -> the values (empty when unknown). Never raises."""

    def __init__(self, key=None, timeout=15, get=requests.get, clock=None):
        self.key = key if key is not None else os.environ.get("COINGECKO_API_KEY")
        self.timeout, self.get = timeout, get
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.day, self.values, self.failed_at = None, {}, None

    def __call__(self):
        now = self.clock()
        today = now.strftime("%Y-%m-%d")
        if self.day == today:
            return self.values
        if self.failed_at and now - self.failed_at < timedelta(minutes=RETRY_MINUTES):
            return {}
        headers = {"x-cg-demo-api-key": self.key} if self.key else None
        try:
            resp = self.get(URL, params={"vs_currency": "usd", "days": 210,
                                         "interval": "daily"},
                            headers=headers, timeout=self.timeout)
            values = trend(resp.json().get("prices")) if resp.status_code == 200 else {}
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            values = {}
        if not values:
            self.failed_at = now
            return {}
        self.day, self.values, self.failed_at = today, values, None
        return values
