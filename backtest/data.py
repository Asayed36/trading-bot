"""Candles from Binance's public data archive (data.binance.vision).

Why this source: it is the only free one that works from BOTH this kind of
sandbox and a GitHub Actions runner, with years of hourly history in one
download per month (Binance's and Bybit's live APIs refuse GitHub's US
servers; Kraken's API only gives the last 720 candles). No key, no account.

Files are monthly zips of klines (hourly and daily), plus daily zips for the
current month. Timestamps are milliseconds, and microseconds from 2025.
"""

import io
import os
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

BASE = "https://data.binance.vision/data/spot"
FIRST_MONTH = (2017, 8)            # the archive starts here
DAY_MS = 86_400_000
EPOCH_ORDINAL = 719163             # date(1970, 1, 1).toordinal()


class DataError(Exception):
    pass


def monthly_url(symbol, interval, year, month):
    return f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip"


def daily_url(symbol, interval, day):
    return f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{day.isoformat()}.zip"


def default_cache():
    return os.environ.get("BACKTEST_CACHE") or os.path.join(tempfile.gettempdir(), "backtest-cache")


class Fetcher:
    """Downloads one URL at a time (threads call it), keeping what it got in a
    cache folder. A missing file (404) is None; any other failure is retried
    and then raised, so a gap is never silently skipped."""

    def __init__(self, cache_dir=None, offline=False, retries=4, timeout=40, opener=None):
        self.cache_dir = cache_dir or default_cache()
        self.offline, self.retries, self.timeout = offline, retries, timeout
        self.opener = opener or urllib.request.urlopen
        self.downloaded = 0
        os.makedirs(self.cache_dir, exist_ok=True)

    def _path(self, url):
        return os.path.join(self.cache_dir, url.replace(BASE + "/", "").replace("/", "__"))

    def get(self, url):
        path = self._path(url)
        if os.path.exists(path):
            with open(path, "rb") as fh:
                return fh.read()
        if self.offline:
            return None
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "backtest/1.0 (read-only)"})
                with self.opener(req, timeout=self.timeout) as resp:
                    body = resp.read()
                tmp = path + ".tmp"
                with open(tmp, "wb") as fh:
                    fh.write(body)
                os.replace(tmp, path)
                self.downloaded += 1
                return body
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                last = exc
            except (urllib.error.URLError, OSError) as exc:
                last = exc
            time.sleep(1.5 * (attempt + 1))
        raise DataError(f"could not download {url}: {last}")


def parse_klines(text):
    """[(open time in ms, open, high, low, close, volume)] from a kline CSV
    (with or without a header line; microsecond timestamps are converted)."""
    rows = []
    for line in text.splitlines():
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            t = int(parts[0])
        except ValueError:
            continue                       # a header
        if t > 10 ** 14:
            t //= 1000                     # microseconds (files from 2025)
        rows.append((t, float(parts[1]), float(parts[2]), float(parts[3]),
                     float(parts[4]), float(parts[5])))
    return rows


def _rows_of(body):
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        return parse_klines(zf.read(zf.namelist()[0]).decode())


def _months(first, last):
    y, m = first
    while (y, m) <= last:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _month_days(year, month, today):
    day = date(year, month, 1)
    while day.month == month and day < today:
        yield day
        day += timedelta(days=1)


def _previous_month(today):
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def find_first_month(fetcher, symbol, today, workers=8):
    """The first month the archive has daily candles for this symbol."""
    months = list(_months(FIRST_MONTH, _previous_month(today)))
    with ThreadPoolExecutor(workers) as ex:
        found = list(ex.map(lambda ym: fetcher.get(monthly_url(symbol, "1d", *ym)), months))
    for ym, body in zip(months, found):
        if body is not None:
            return ym
    # a very new coin: only the current month's daily files exist
    cur = (today.year, today.month)
    for day in _month_days(*cur, today):
        if fetcher.get(daily_url(symbol, "1d", day)) is not None:
            return cur
    return None


def load_rows(fetcher, symbol, interval, first_month, today, workers=8):
    """All candles of one symbol and interval, oldest first, one per time."""
    last_complete = _previous_month(today)
    urls = [monthly_url(symbol, interval, y, m) for y, m in _months(first_month, last_complete)]
    with ThreadPoolExecutor(workers) as ex:
        bodies = list(ex.map(fetcher.get, urls))
    rows = []
    for (y, m), body in zip(_months(first_month, last_complete), bodies):
        if body is None:
            # the latest monthly file may not be published yet: use the days
            if (y, m) == last_complete:
                days = [daily_url(symbol, interval, d) for d in _month_days(y, m, today)]
                with ThreadPoolExecutor(workers) as ex:
                    for b in ex.map(fetcher.get, days):
                        if b is not None:
                            rows += _rows_of(b)
            continue
        rows += _rows_of(body)
    cur = (today.year, today.month)
    if cur >= first_month:
        days = [daily_url(symbol, interval, d) for d in _month_days(*cur, today)]
        with ThreadPoolExecutor(workers) as ex:
            for b in ex.map(fetcher.get, days):
                if b is not None:
                    rows += _rows_of(b)
    by_time = {r[0]: r for r in rows}
    return [by_time[t] for t in sorted(by_time)]


class CoinData:
    """One coin: daily candles, and the hourly path inside each day (used only
    to decide where a stop fills)."""

    def __init__(self, label, symbols):
        self.label, self.symbols = label, list(symbols)
        self.day = []                              # day number (days since 1970-01-01)
        self.o, self.h, self.l, self.c, self.v = [], [], [], [], []
        self.h_open = array("d")                   # hourly open and low, all days in a row
        self.h_low = array("d")
        self.day_hours = []                        # per day: (first, end) index into h_open / h_low
        self.notes = {}

    def __len__(self):
        return len(self.day)

    def date_of(self, i):
        return date.fromordinal(EPOCH_ORDINAL + self.day[i])

    def index_on_or_after(self, day_number):
        lo, hi = 0, len(self.day)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.day[mid] < day_number:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def truncate(self, last_day):
        """A copy with nothing after `last_day` (a date): later candles are not
        even in memory, so they cannot leak into anything computed from it."""
        cut = self.index_on_or_after(last_day.toordinal() - EPOCH_ORDINAL + 1)
        out = CoinData(self.label, self.symbols)
        for name in ("day", "o", "h", "l", "c", "v"):
            setattr(out, name, getattr(self, name)[:cut])
        out.day_hours = self.day_hours[:cut]
        end = out.day_hours[-1][1] if out.day_hours else 0
        out.h_open, out.h_low = self.h_open[:end], self.h_low[:end]
        out.notes = dict(self.notes)
        return out


def build_coin(label, symbols, daily_rows, hourly_rows):
    """CoinData from daily and hourly candles, with a check that the two agree."""
    coin = CoinData(label, symbols)
    # hourly candles grouped by day
    hours_by_day = {}
    for t, o, h, l, c, v in hourly_rows:
        hours_by_day.setdefault(t // DAY_MS, []).append((t, o, h, l, c))
    mismatched = short_days = 0
    for t, o, h, l, c, v in daily_rows:
        day = t // DAY_MS
        coin.day.append(day)
        coin.o.append(o)
        coin.h.append(h)
        coin.l.append(l)
        coin.c.append(c)
        coin.v.append(v)
        hours = hours_by_day.get(day, [])
        start = len(coin.h_open)
        for _, ho, _, hl, _ in hours:
            coin.h_open.append(ho)
            coin.h_low.append(hl)
        coin.day_hours.append((start, len(coin.h_open)))
        if len(hours) < 24:
            short_days += 1
        if hours:
            agg = (hours[0][1], max(x[2] for x in hours), min(x[3] for x in hours), hours[-1][4])
            for a, b in zip(agg, (o, h, l, c)):
                if abs(a - b) > 1e-6 * max(abs(b), 1e-12):
                    mismatched += 1
                    break
    gaps = sum(1 for a, b in zip(coin.day, coin.day[1:]) if b - a != 1)
    coin.notes = {"daily_bars": len(coin.day), "hourly_bars": len(coin.h_open),
                  "gaps_in_daily_candles": gaps, "days_with_fewer_than_24_hours": short_days,
                  "days_where_hourly_and_daily_disagree": mismatched}
    return coin


def load_coin(fetcher, label, symbols, today, workers=8):
    """Download and assemble one coin (None if the archive has nothing)."""
    daily, hourly = {}, {}
    for symbol in symbols:
        first = find_first_month(fetcher, symbol, today, workers)
        if first is None:
            continue
        for row in load_rows(fetcher, symbol, "1d", first, today, workers):
            daily[row[0]] = row                    # a later symbol replaces an earlier one
        for row in load_rows(fetcher, symbol, "1h", first, today, workers):
            hourly[row[0]] = row
    if not daily:
        return None
    return build_coin(label, symbols, [daily[t] for t in sorted(daily)],
                      [hourly[t] for t in sorted(hourly)])
