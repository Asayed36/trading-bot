"""A once-a-minute log of Bitcoin's, Ethereum's and Solana's prices, for later
analysis. RECORDING ONLY: nothing here is read by any buy, sell, filter or exit.

    data/market/prices-YYYY-MM-DD.csv   (UTC date) time_utc, btc_usd, eth_usd, sol_usd
    data/market/health.json             rows and failures per day, the last price saved

It runs inside the launch-bot service (launch_bot.py), so there is no new service
to start, and deploy/push_results.sh pushes the files every hour.

Source: Binance's public market-data host data-api.binance.vision (the host
screener/backdrop.py uses), the latest-price ticker /api/v3/ticker/price for
BTCUSDT, ETHUSDT and SOLUSDT in ONE request a minute (1,440 a day). No key, no
header, public GET only. Prices are in USDT, Binance's dollar stablecoin
(within a fraction of a percent of one US dollar).

A 5-second timeout and no retry: if the request fails, that minute's row is
saved with the prices blank (blank = not known, never zero) and the failure is
counted. One row per minute at most, also across a restart. It never raises.

PAPER TRADING ONLY: a public read-only GET, no wallet, key or order.
"""

import csv
import json
import os
from datetime import datetime, timezone

import requests

URL = "https://data-api.binance.vision/api/v3/ticker/price"
SYMBOLS = {"BTCUSDT": "btc_usd", "ETHUSDT": "eth_usd", "SOLUSDT": "sol_usd"}
COLUMNS = ["time_utc", "btc_usd", "eth_usd", "sol_usd"]
PRICE_COLUMNS = COLUMNS[1:]
TIMEOUT_SECONDS = 5
FOLDER = "market"            # under the data folder
TIME = "%Y-%m-%d %H:%M:%S"
KEEP_DAYS = 14               # days of counts kept in health.json


def file_name(day):
    """prices-YYYY-MM-DD.csv for a date (or a datetime)."""
    return f"prices-{day:%Y-%m-%d}.csv"


def parse(answer):
    """{column: price} from Binance's answer (only the prices it gave, each a
    positive number)."""
    out = {}
    if not isinstance(answer, list):
        return out
    for item in answer:
        if not isinstance(item, dict) or item.get("symbol") not in SYMBOLS:
            continue
        try:
            value = float(item.get("price"))
        except (TypeError, ValueError):
            continue
        if value == value and value != float("inf") and value > 0:
            out[SYMBOLS[item["symbol"]]] = value
    return out


class MarketPriceLog:
    """record() once a minute: one request, one row. Never raises."""

    def __init__(self, folder, get=requests.get, timeout=TIMEOUT_SECONDS, clock=None):
        self.folder, self.get, self.timeout = folder, get, timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.last_minute = None
        self.health = None

    def record(self, now=None):
        """Ask Binance once and save the row. Returns the row, or None when this
        minute already has one (or nothing could be saved)."""
        try:
            return self._record(now or self.clock())
        except Exception:      # recording only: a failure here must never reach the bot
            return None

    # -- one minute --

    def _record(self, now):
        now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
        minute = now.strftime("%Y-%m-%d %H:%M")
        if self.last_minute is None:
            self.last_minute = self._last_saved_minute(now)
        if minute == self.last_minute:
            return None
        prices, error = self._ask()
        row = {"time_utc": now.strftime(TIME)}
        row.update({c: f"{prices[c]:.10g}" if c in prices else "" for c in PRICE_COLUMNS})
        self._append(now, row)
        self.last_minute = minute
        self._note(now, row, error)
        return row

    def _ask(self):
        """(prices, error): one GET, no retry. error is None when all three came."""
        try:
            resp = self.get(URL, params={"symbols": json.dumps(list(SYMBOLS),
                                                               separators=(",", ":"))},
                            timeout=self.timeout)
            if resp.status_code != 200:
                return {}, f"HTTP {resp.status_code}"
            prices = parse(resp.json())
        except Exception as exc:
            return {}, (type(exc).__name__ + ": " + str(exc))[:160]
        missing = [c for c in PRICE_COLUMNS if c not in prices]
        return prices, (f"no price for {', '.join(missing)}" if missing else None)

    # -- the files --

    def path(self, day):
        return os.path.join(self.folder, file_name(day))

    def _last_saved_minute(self, now):
        """The minute of the last row in today's file ('' when none)."""
        try:
            with open(self.path(now), newline="") as fh:
                last = ""
                for row in csv.DictReader(fh):
                    last = (row.get("time_utc") or "")[:16] or last
                return last
        except OSError:
            return ""

    def _append(self, now, row):
        os.makedirs(self.folder, exist_ok=True)
        path = self.path(now)
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(COLUMNS)
            w.writerow([row[c] for c in COLUMNS])

    def _note(self, now, row, error):
        """health.json: rows and failures per UTC day, the last price saved, the
        last error. A row with any price missing counts as a failure."""
        path = os.path.join(self.folder, "health.json")
        if self.health is None:
            try:
                with open(path) as fh:
                    self.health = json.load(fh)
                if not isinstance(self.health, dict):
                    raise ValueError
            except (OSError, ValueError):
                self.health = {}
        h = self.health
        days = h.setdefault("days", {})
        day = days.setdefault(now.strftime("%Y-%m-%d"), {"rows": 0, "failures": 0})
        day["rows"] += 1
        stamp = now.strftime(TIME)
        if error:
            day["failures"] += 1
            h["last_error"], h["error_at"] = error, stamp
        if any(row[c] for c in PRICE_COLUMNS):
            h["last_price"] = dict(row)
        h["updated"] = stamp
        for old in sorted(days)[:-KEEP_DAYS]:
            del days[old]
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(h, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)


# -- reading the log back (market_prices.py --at ...) --

def read_rows(folder, start, end):
    """{"YYYY-MM-DD HH:MM": {column: float or None}} for the minutes from start to
    end (both included), from the daily files. The first row of a minute wins."""
    out = {}
    day = start.date()
    while day <= end.date():
        try:
            with open(os.path.join(folder, file_name(day)), newline="") as fh:
                for row in csv.DictReader(fh):
                    minute = (row.get("time_utc") or "")[:16]
                    if minute in out or not minute:
                        continue
                    try:
                        when = datetime.strptime(minute, "%Y-%m-%d %H:%M")
                    except ValueError:
                        continue
                    if start <= when <= end:
                        out[minute] = {c: _float(row.get(c)) for c in PRICE_COLUMNS}
        except OSError:
            pass
        day = day.fromordinal(day.toordinal() + 1)
    return out


def _float(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
