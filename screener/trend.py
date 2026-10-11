"""The "trend" paper strategy: a forward test of a simple trend-following rule
on large, liquid coins. PAPER ONLY: virtual money, no wallet, no key, no order.
Only public daily prices are read (GET requests, no key, no paid service).

THE RULE (the backtest tool's "trend following: close above its 50-day
average" variant, the one that made about +46% in its 2024-2026 test; nothing
is re-tuned): a coin is held while its daily close is above its 50-day simple
average (the mean of the last 50 daily closes, today's included), and the
close must be strictly above it.
  * ENTER only on a fresh cross: today's close is above the average and
    yesterday's was not. Nothing is opened on the first day (the start day),
    whatever is already above its average.
  * EXIT when the close is no longer above the average.
  * Fills are at the signal day's own close (the backtest filled at the next
    open), with the backtest's costs per side (0.10% fee, 0.05% slippage for
    BTC/ETH/SOL and 0.20% for the others) but never under 0.5% for the round
    trip. Each coin has a fixed notional of 1,000 / 18 USDT.

THREE VIRTUAL LINES from the same start day:
  "trend"               the rule above;
  "trend + BTC filter"  the same, but a coin is only entered while BTC's close
                        is above BTC's 200-day average (open positions follow
                        the normal exit);
  "buy and hold"        the 18 coins in equal parts from the start day's close
                        (it pays the entry cost only: it never sells).

THE COINS are frozen in config.toml ([[trend.coins]]) and never change: if a
coin's data disappears it is written to log.csv, not dropped. The 18 coins all
still exist and are liquid today, so any history flatters the result
(survivorship bias).

RUNS: once a day, shortly after the daily candle closes (00:10 UTC, the
"Trend forward test" workflow). It is idempotent (a second run the same day
changes nothing) and catches up from the stored candles after a missed day.
Daily candles are stored in data/trend/candles/, positions in
data/trend/state.json, closed trades in trades.csv, the value of the three
lines in equity.csv and anything odd (missing data, the source used) in log.csv.

DATA SOURCE (tested from GitHub Actions, see the pull request): Binance's
public market-data endpoint data-api.binance.vision first, the daily files of
data.binance.vision as the fallback. No CoinGecko.
"""

import csv
import io
import json
import os
import zipfile
from datetime import date, datetime, timedelta, timezone

import requests

DATA_API = "https://data-api.binance.vision/api/v3/klines"
ARCHIVE = "https://data.binance.vision/data/spot/{kind}/klines/{symbol}/1d/{symbol}-1d-{stamp}.zip"
API_SOURCE = "data-api.binance.vision"
ARCHIVE_SOURCE = "data.binance.vision (daily files)"

LINE_NAMES = {"trend": "trend", "trend_btc": "trend + BTC filter", "buy_hold": "buy and hold"}
TRADE_COLUMNS = ["line", "coin", "entry_date", "entry_price", "exit_date", "exit_price",
                 "exit_reason", "notional_usdt", "gross_return_pct", "cost_pct", "cost_usdt",
                 "return_pct", "pnl_usdt", "sma_at_entry", "risk_pct", "r_multiple", "days_held"]
EQUITY_COLUMNS = ["date", "trend", "trend_btc_filter", "buy_hold", "trend_max_fall_pct",
                  "trend_btc_filter_max_fall_pct", "buy_hold_max_fall_pct", "trend_open",
                  "trend_btc_filter_open"]
LOG_COLUMNS = ["date", "coin", "event", "detail"]
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class FetchError(Exception):
    pass


def day_of(text):
    return date.fromisoformat(text)


# ---------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------

def _row(open_time, o, h, l, c, v):
    """One candle as (date, o, h, l, c, v); Binance's archive switched to
    microsecond timestamps in 2025."""
    t = int(open_time)
    if t > 10 ** 14:
        t //= 1000
    return (datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat(),
            float(o), float(h), float(l), float(c), float(v))


class BinanceDaily:
    """Daily candles, closed days only. data-api.binance.vision first; if it
    fails, the daily (or monthly) files of data.binance.vision."""

    def __init__(self, http=None, timeout=20):
        self.http, self.timeout = http or requests, timeout

    def candles(self, symbol, first, last):
        """([rows], source, note): the candles for first..last (dates, both
        included). Raises FetchError when no source answered."""
        try:
            return self._api(symbol, first, last), API_SOURCE, ""
        except FetchError as exc:
            api_error = str(exc)
        try:
            rows = self._archive(symbol, first, last)
        except FetchError as exc:
            raise FetchError(f"{API_SOURCE}: {api_error}; {ARCHIVE_SOURCE}: {exc}") from exc
        return rows, ARCHIVE_SOURCE, f"{API_SOURCE} failed: {api_error}"

    def _get(self, url, **kwargs):
        try:
            return self.http.get(url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise FetchError(f"could not reach {url.split('?')[0]}: {type(exc).__name__}") from exc

    def _api(self, symbol, first, last):
        rows, start = [], first
        while start <= last:
            ms = lambda d: int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)  # noqa: E731
            resp = self._get(DATA_API, params={
                "symbol": symbol, "interval": "1d", "startTime": ms(start),
                "endTime": ms(last + timedelta(days=1)) - 1, "limit": 1000})
            if resp.status_code != 200:
                raise FetchError(f"{symbol} answered HTTP {resp.status_code}")
            try:
                data = resp.json()
            except ValueError as exc:
                raise FetchError(f"{symbol}: not JSON") from exc
            if not isinstance(data, list):
                raise FetchError(f"{symbol}: unexpected answer")
            got = [_row(k[0], k[1], k[2], k[3], k[4], k[5]) for k in data]
            rows += [r for r in got if first <= day_of(r[0]) <= last]
            if len(data) < 1000:
                break
            start = day_of(got[-1][0]) + timedelta(days=1)
        return rows

    def _zip(self, kind, symbol, stamp):
        """The rows of one archive file; None when it isn't there (404)."""
        resp = self._get(ARCHIVE.format(kind=kind, symbol=symbol, stamp=stamp))
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise FetchError(f"{symbol} {stamp} answered HTTP {resp.status_code}")
        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                text = zf.read(zf.namelist()[0]).decode()
        except (zipfile.BadZipFile, KeyError, IndexError, UnicodeDecodeError) as exc:
            raise FetchError(f"{symbol} {stamp}: not a zip file") from exc
        return [_row(*r[:6]) for r in csv.reader(io.StringIO(text)) if r and r[0].isdigit()]

    def _archive(self, symbol, first, last):
        rows, d = [], first
        while d <= last:
            nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
            if d.day == 1 and nxt - timedelta(days=1) <= last:
                got = self._zip("monthly", symbol, d.strftime("%Y-%m"))
                if got is not None:
                    rows += got
                    d = nxt
                    continue
            got = self._zip("daily", symbol, d.isoformat())
            if got:
                rows += got
            d += timedelta(days=1)
        return [r for r in rows if first <= day_of(r[0]) <= last]


# ---------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------

def _read_csv(path):
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _append(path, columns, rows):
    if not rows:
        return
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(columns)
        w.writerows(rows)


def _num(x, digits=10):
    return f"{x:.{digits}g}"


class Trend:
    """One run of the strategy over a data folder (data/trend)."""

    def __init__(self, cfg, folder, fetcher=None, out=print):
        self.c = cfg["trend"]
        self.folder = folder
        self.fetcher = fetcher or BinanceDaily()
        self.out = out
        self.coins = [(x["name"], x["symbol"]) for x in self.c["coins"]]
        self.names = [n for n, _ in self.coins]
        self.n = int(self.c["average_days"])
        self.btc_days = int(self.c["btc_filter_days"])
        self.portfolio = float(self.c["portfolio_usdt"])
        self.notional = self.portfolio / len(self.coins)
        self.paths = {k: os.path.join(folder, v) for k, v in (
            ("state", "state.json"), ("trades", "trades.csv"), ("equity", "equity.csv"),
            ("log", "log.csv"))}
        self.candles = {}                 # coin -> [(date, o, h, l, c, v)]
        self.new_candles = {}
        self.logged = {(r["date"], r["coin"], r["event"]) for r in _read_csv(self.paths["log"])}
        self.log_rows, self.trade_rows, self.equity_rows = [], [], []

    # ---- costs ----

    def round_trip(self, coin):
        """The backtest's cost for a round trip, but never under the minimum (a fraction)."""
        slip = self.c["slippage_major_pct"] if coin in self.c["majors"] else self.c["slippage_other_pct"]
        return max(2 * (self.c["fee_per_side_pct"] + slip), self.c["min_round_trip_cost_pct"]) / 100

    # ---- the stored candles ----

    def _store_path(self, coin):
        return os.path.join(self.folder, "candles", f"{coin}.csv")

    def _load(self, coin):
        rows = [(r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                 float(r["volume"])) for r in _read_csv(self._store_path(coin))]
        self.candles[coin] = sorted(rows)

    def _log(self, day, coin, event, detail):
        key = (day, coin, event)
        if key not in self.logged:                  # one line per day, coin and event, however often it runs
            self.logged.add(key)
            self.log_rows.append([day, coin, event, detail])
            self.out(f"  log: {day} {coin or '-'} {event}: {detail}")

    def _first_wanted(self, have, last):
        """The first day to ask for: the whole history when nothing is stored yet, else the
        first recent day (the last grace_days + 1) that is missing from the stored candles
        (so a gap is filled when the day turns up), or the day after the last one stored."""
        if not have:
            return last - timedelta(days=int(self.c["history_days"]) - 1)
        known = {r[0] for r in have}
        wanted = []
        after = day_of(have[-1][0]) + timedelta(days=1)
        if after <= last:
            wanted.append(after)
        d = max(last - timedelta(days=int(self.c["grace_days"]) + 1), day_of(have[0][0]))
        while d <= last:
            if d.isoformat() not in known:
                wanted.append(d)
                break
            d += timedelta(days=1)
        return min(wanted) if wanted else None

    def _fetch_all(self, last):
        for coin, symbol in self.coins:
            self._load(coin)
            have = self.candles[coin]
            first = self._first_wanted(have, last)
            if first is None:
                continue
            try:
                rows, source, note = self.fetcher.candles(symbol, first, last)
            except FetchError as exc:
                self._log(last.isoformat(), coin, "fetch failed", str(exc)[:300])
                continue
            known = {r[0] for r in have}
            added = sorted(r for r in rows if r[0] not in known)
            if note:
                self._log(last.isoformat(), coin, "fallback source", f"{note}; used {source}")
            if not added:
                continue
            self.candles[coin] = sorted(have + added)
            self.new_candles[coin] = added
            self._log(last.isoformat(), "", "source", source)        # once a day

    # ---- state ----

    def _new_book(self):
        return {"open": {}, "realized": 0.0, "peak": self.portfolio, "max_fall_pct": 0.0}

    def _load_state(self):
        try:
            with open(self.paths["state"]) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    # ---- indicators (from the stored candles) ----

    def _series(self, coin, day):
        """Closes up to and including `day` (dates and values)."""
        rows = self.candles.get(coin) or []
        return [(r[0], r[4]) for r in rows if r[0] <= day]

    @staticmethod
    def _average(closes, n):
        return sum(v for _, v in closes[-n:]) / n if len(closes) >= n else None

    def _facts(self, coin, day):
        """(close, sma, previous close above its sma? True/False/None), or None without a candle that day."""
        closes = self._series(coin, day)
        if not closes or closes[-1][0] != day:
            return None
        close = closes[-1][1]
        sma = self._average(closes, self.n)
        prev = None
        if len(closes) >= 2 and closes[-2][0] == (day_of(day) - timedelta(days=1)).isoformat():
            prev_sma = self._average(closes[:-1], self.n)
            if prev_sma is not None:
                prev = closes[-2][1] > prev_sma
        return close, sma, prev

    def _btc_flag(self, day):
        closes = self._series("BTC", day)
        if not closes or closes[-1][0] != day:
            return None
        avg = self._average(closes, self.btc_days)
        return None if avg is None else closes[-1][1] > avg

    # ---- the days ----

    def run(self, now=None):
        """Fetch what is missing, then process every day not yet processed."""
        now = now or datetime.now(timezone.utc)
        last = now.date() - timedelta(days=1)             # the latest candle that has closed
        state = self._load_state()
        if state is not None and state.get("coins") != self.names:
            raise RuntimeError("the coin list in config.toml is not the frozen one in "
                               f"data/trend/state.json: {state.get('coins')} vs {self.names}")
        before = json.dumps(state, sort_keys=True)
        self._fetch_all(last)
        if state is None:
            state = self._start(last)
            if state is None:
                self._save(None, before)
                return []
        days = []
        d = day_of(state["last_day"]) + timedelta(days=1)
        while d <= last:
            if not self._ready(d, last):
                break
            self._process(state, d.isoformat(), last)
            days.append(d.isoformat())
            d += timedelta(days=1)
        self._save(state, before)
        return days

    def _ready(self, d, last):
        """A day is processed when every coin has its candle, or when it is old enough
        (grace_days) that a missing one is recorded as missing instead of waited for."""
        missing = [n for n in self.names if not any(r[0] == d.isoformat() for r in self.candles.get(n, []))]
        if not missing:
            return True
        if (last - d).days >= int(self.c["grace_days"]):
            return True
        self._log(d.isoformat(), "", "waiting", f"no candle yet for {', '.join(missing)}")
        return False

    def _start(self, last):
        """The first run: the start day is the latest day (within the grace days) on which
        every coin has a candle. Nothing is opened on it, except buy-and-hold."""
        for back in range(int(self.c["grace_days"]) + 1):
            d = (last - timedelta(days=back)).isoformat()
            if all(any(r[0] == d for r in self.candles.get(n, [])) for n in self.names):
                state = {"version": 1, "coins": list(self.names), "start_day": d, "last_day": d,
                         "last_close": {}, "books": {"trend": self._new_book(),
                                                     "trend_btc": self._new_book(),
                                                     "buy_hold": self._new_book()}}
                self._open_buy_hold(state, d)
                self._equity(state, d)
                self._log(d, "", "start", f"start day {d}: nothing is opened for coins already above their "
                                          f"{self.n}-day average; buy and hold buys {len(self.names)} coins at the close")
                return state
        self._log(last.isoformat(), "", "not started", "no day in the last "
                  f"{self.c['grace_days']} days has a candle for every coin")
        return None

    def _open_buy_hold(self, state, d):
        book = state["books"]["buy_hold"]
        for coin in self.names:
            f = self._facts(coin, d)
            if f is None:
                self._log(d, coin, "no candle", "buy and hold: no price on the start day, this slot stays in cash")
                continue
            state["last_close"][coin] = f[0]
            book["open"][coin] = {"entry_day": d, "entry_price": f[0], "notional": self.notional,
                                  "entry_cost": self.notional * self.round_trip(coin) / 2}

    def _process(self, state, d, last):
        books = state["books"]
        btc = self._btc_flag(d)
        if btc is None:
            self._log(d, "BTC", "no BTC flag", "no BTC candle or fewer than "
                      f"{self.btc_days} days of history: the BTC-filter line enters nothing today")
        for coin in self.names:
            f = self._facts(coin, d)
            if f is None:
                self._log(d, coin, "no candle", "no daily candle for this coin on this day (data missing)")
                continue
            close, sma, prev_above = f
            state["last_close"][coin] = close
            if sma is None:
                self._log(d, coin, "short history", f"fewer than {self.n} daily candles: no signal")
                continue
            above = close > sma
            for key in ("trend", "trend_btc"):
                book = books[key]
                pos = book["open"].get(coin)
                if pos is not None:
                    if not above:
                        self._close(book, key, coin, pos, d, close)
                    continue
                if prev_above is None:
                    self._log(d, coin, "no previous day", "cannot tell whether this is a fresh cross")
                    continue
                if above and prev_above is False:
                    if key == "trend_btc" and btc is not True:
                        continue
                    book["open"][coin] = {"entry_day": d, "entry_price": close, "sma": sma,
                                          "notional": self.notional,
                                          "entry_cost": self.notional * self.round_trip(coin) / 2}
        self._equity(state, d)
        state["last_day"] = d

    def _close(self, book, key, coin, pos, d, price):
        rt = self.round_trip(coin)
        notional = pos["notional"]
        gross = price / pos["entry_price"] - 1
        cost = notional * rt
        pnl = notional * gross - cost
        net = gross - rt
        risk = (pos["entry_price"] - pos["sma"]) / pos["entry_price"]
        book["realized"] += pnl
        del book["open"][coin]
        self.trade_rows.append([
            LINE_NAMES[key], coin, pos["entry_day"], _num(pos["entry_price"]), d, _num(price),
            f"close not above the {self.n}-day average", _num(notional, 8),
            _num(gross * 100, 8), _num(rt * 100, 4), _num(cost, 8), _num(net * 100, 8), _num(pnl, 8),
            _num(pos["sma"]), _num(risk * 100, 8), _num(net / risk, 8) if risk > 0 else "",
            (day_of(d) - day_of(pos["entry_day"])).days])

    def _value(self, state, key):
        book = state["books"][key]
        value = self.portfolio + book["realized"]
        for coin, pos in book["open"].items():
            last = state["last_close"].get(coin, pos["entry_price"])
            value += pos["notional"] * (last / pos["entry_price"] - 1) - pos["entry_cost"]
        return value

    def _equity(self, state, d):
        values = {}
        for key in ("trend", "trend_btc", "buy_hold"):
            book = state["books"][key]
            values[key] = self._value(state, key)
            book["peak"] = max(book["peak"], values[key])
            book["max_fall_pct"] = max(book["max_fall_pct"], (1 - values[key] / book["peak"]) * 100)
        b = state["books"]
        self.equity_rows.append([
            d, _num(values["trend"], 8), _num(values["trend_btc"], 8), _num(values["buy_hold"], 8),
            _num(b["trend"]["max_fall_pct"], 6), _num(b["trend_btc"]["max_fall_pct"], 6),
            _num(b["buy_hold"]["max_fall_pct"], 6), len(b["trend"]["open"]), len(b["trend_btc"]["open"])])

    def _save(self, state, before):
        have = {r["date"] for r in _read_csv(self.paths["equity"])}
        existing = {(r["line"], r["coin"], r["entry_date"]) for r in _read_csv(self.paths["trades"])}
        _append(self.paths["trades"], TRADE_COLUMNS,
                [r for r in self.trade_rows if (r[0], r[1], r[2]) not in existing])
        _append(self.paths["equity"], EQUITY_COLUMNS, [r for r in self.equity_rows if r[0] not in have])
        _append(self.paths["log"], LOG_COLUMNS, self.log_rows)
        for coin, rows in self.new_candles.items():
            _append(self._store_path(coin), CANDLE_COLUMNS,
                    [[r[0], _num(r[1]), _num(r[2]), _num(r[3]), _num(r[4]), _num(r[5])] for r in rows])
        if state is not None and json.dumps(state, sort_keys=True) != before:
            os.makedirs(self.folder, exist_ok=True)
            tmp = self.paths["state"] + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(state, fh, indent=1, sort_keys=True)
            os.replace(tmp, self.paths["state"])
