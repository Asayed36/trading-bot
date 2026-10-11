"""Checks for the "trend" paper strategy (screener/trend.py, trend_bot.py, the
"Trend forward test" workflow and its rows in the daily comparison), with made-up
prices: nothing is downloaded. Run with:  python -m unittest -v
"""

import copy
import csv
import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

import compare  # noqa: E402
from screener import compare as sc  # noqa: E402
from screener import trend as tr  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402

REAL = load_config()
D0 = date(2026, 1, 1)                      # day index 0 of the made-up series
S = 20                                     # the start day, as an index


def day(i):
    return (D0 + timedelta(days=i)).isoformat()


def at(i):
    """The time of a run at 00:10 UTC on day i (so the latest closed candle is i - 1)."""
    d = D0 + timedelta(days=i)
    return datetime(d.year, d.month, d.day, 0, 10, tzinfo=timezone.utc)


def small(**changes):
    """A 3-coin config with short averages, for readable series."""
    cfg = copy.deepcopy(REAL)
    t = cfg["trend"]
    t.update(average_days=5, btc_filter_days=10, portfolio_usdt=300, history_days=40, grace_days=3,
             majors=["BTC", "ETH", "SOL"], coins=[{"name": n, "symbol": n + "USDT"}
                                                   for n in ("BTC", "ETH", "SOL")])
    t.update(changes)
    return cfg


def flat_then(first, rest, n=60):
    """10 for `first` days, then the values in `rest`, then flat at the last one."""
    vals = [10.0] * first + list(rest)
    return vals + [vals[-1]] * (n - len(vals))


# BTC rises (always above its 10-day average); ETH crosses up at 21 and falls at 24;
# SOL is already above its average on the start day and just keeps rising.
BTC_UP = [10.0 + 0.3 * i for i in range(60)]
ETH = flat_then(21, [11, 12, 13, 9, 9, 9, 9])
SOL = [10.0 + 0.5 * i for i in range(60)]


class Fake:
    """A price source with the made-up series; days can be hidden or the source broken."""

    def __init__(self, series):
        self.series = series
        self.hidden = set()               # (symbol, index)
        self.broken = set()               # symbols that raise
        self.calls = []

    def candles(self, symbol, first, last):
        self.calls.append((symbol, first, last))
        if symbol in self.broken:
            raise tr.FetchError(f"{symbol} answered HTTP 500")
        rows = []
        for i, c in enumerate(self.series[symbol[:-4]]):
            d = D0 + timedelta(days=i)
            if first <= d <= last and (symbol, i) not in self.hidden:
                rows.append((d.isoformat(), c, c * 1.01, c * 0.99, c, 1000.0))
        return rows, tr.API_SOURCE, ""


def rows(path):
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def snapshot(folder):
    out = {}
    for base, _, files in os.walk(folder):
        for f in files:
            with open(os.path.join(base, f), "rb") as fh:
                out[os.path.relpath(os.path.join(base, f), folder)] = hashlib.md5(fh.read()).hexdigest()
    return out


class Base(unittest.TestCase):
    series = {"BTC": BTC_UP, "ETH": ETH, "SOL": SOL}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "trend")
        self.cfg = small()
        self.src = Fake(copy.deepcopy(self.series))

    def run_at(self, i, cfg=None, folder=None):
        t = tr.Trend(cfg or self.cfg, folder or self.folder, self.src, out=lambda *a: None)
        return t.run(at(i))

    def state(self):
        import json
        with open(os.path.join(self.folder, "state.json")) as fh:
            return json.load(fh)

    def trades(self, line=None):
        return [r for r in rows(os.path.join(self.folder, "trades.csv")) if line in (None, r["line"])]


class RuleTests(Base):
    def test_nothing_is_opened_on_the_start_day_whatever_is_already_above(self):
        self.assertEqual(self.run_at(S + 1), [])           # the first run: the start day is index 20
        s = self.state()
        self.assertEqual(s["start_day"], day(S))
        self.assertEqual(s["books"]["trend"]["open"], {})
        self.assertEqual(s["books"]["trend_btc"]["open"], {})
        self.assertEqual(sorted(s["books"]["buy_hold"]["open"]), ["BTC", "ETH", "SOL"])
        self.assertEqual(self.trades(), [])
        # SOL is above its average on day 1 and on every later day: never a fresh cross
        self.run_at(S + 30)
        self.assertNotIn("SOL", {r["coin"] for r in self.trades()})
        self.assertNotIn("SOL", self.state()["books"]["trend"]["open"])

    def test_a_fresh_cross_enters_at_that_days_close(self):
        self.run_at(S + 1)
        self.run_at(S + 3)                                  # processes days 21 and 22
        pos = self.state()["books"]["trend"]["open"]["ETH"]
        self.assertEqual((pos["entry_day"], pos["entry_price"]), (day(21), 11.0))
        self.assertAlmostEqual(pos["sma"], (10 + 10 + 10 + 10 + 11) / 5)
        self.assertAlmostEqual(pos["notional"], 100.0)      # 300 / 3

    def test_exit_when_the_close_is_no_longer_above_the_average(self):
        self.run_at(S + 1)
        self.run_at(S + 10)
        (t,) = self.trades("trend")
        self.assertEqual((t["coin"], t["entry_date"], t["exit_date"]), ("ETH", day(21), day(24)))
        self.assertEqual((float(t["entry_price"]), float(t["exit_price"])), (11.0, 9.0))
        self.assertEqual(self.state()["books"]["trend"]["open"], {})
        self.assertEqual(t["exit_reason"], "close not above the 5-day average")

    def test_costs_are_charged_and_logged_per_trade(self):
        self.run_at(S + 1)
        self.run_at(S + 10)
        (t,) = self.trades("trend")
        gross = 9 / 11 - 1
        self.assertAlmostEqual(float(t["gross_return_pct"]), gross * 100, places=5)
        self.assertAlmostEqual(float(t["cost_pct"]), 0.5)           # ETH: the backtest's 0.30%, raised to 0.5%
        self.assertAlmostEqual(float(t["cost_usdt"]), 100 * 0.005)
        self.assertAlmostEqual(float(t["return_pct"]), (gross - 0.005) * 100, places=5)
        self.assertAlmostEqual(float(t["pnl_usdt"]), 100 * gross - 0.5, places=5)
        self.assertAlmostEqual(self.state()["books"]["trend"]["realized"], 100 * gross - 0.5, places=5)

    def test_r_multiple_is_the_net_return_over_the_risk_at_entry(self):
        self.run_at(S + 1)
        self.run_at(S + 10)
        (t,) = self.trades("trend")
        risk = (11 - 10.2) / 11
        self.assertAlmostEqual(float(t["risk_pct"]), risk * 100, places=5)
        self.assertAlmostEqual(float(t["r_multiple"]), (9 / 11 - 1 - 0.005) / risk, places=5)
        self.assertEqual(float(t["sma_at_entry"]), 10.2)
        self.assertEqual(int(t["days_held"]), 3)

    def test_the_equity_file_has_the_three_lines_and_their_max_fall(self):
        self.run_at(S + 1)
        self.run_at(S + 10)
        eq = rows(os.path.join(self.folder, "equity.csv"))
        self.assertEqual([r["date"] for r in eq], [day(i) for i in range(S, S + 10)])
        self.assertEqual(list(eq[0]), tr.EQUITY_COLUMNS)
        # trend: 300 + the ETH trade's profit once closed
        self.assertAlmostEqual(float(eq[-1]["trend"]), 300 + 100 * (9 / 11 - 1) - 0.5, places=5)
        self.assertGreater(float(eq[-1]["trend_max_fall_pct"]), 0)
        # buy and hold: 100 in each coin from the start day's close, minus the entry cost only
        bh = sum(100 * (self.series[c][S + 9] / self.series[c][S] - 1) for c in ("BTC", "ETH", "SOL"))
        self.assertAlmostEqual(float(eq[-1]["buy_hold"]), 300 + bh - 3 * 100 * 0.005 / 2, places=5)
        peak, worst = 0, 0
        for r in eq:
            v = float(r["buy_hold"])
            peak = max(peak, v)
            worst = max(worst, (1 - v / peak) * 100)
        self.assertAlmostEqual(float(eq[-1]["buy_hold_max_fall_pct"]), worst, places=4)

    def test_the_costs_of_the_real_config(self):
        t = tr.Trend(REAL, self.folder, self.src)
        for coin in ("BTC", "ETH", "SOL"):
            self.assertAlmostEqual(t.round_trip(coin), 0.005)      # 0.30% in the backtest: never under 0.5%
        for coin in ("ADA", "RENDER", "TAO"):
            self.assertAlmostEqual(t.round_trip(coin), 0.006)      # 2 x (0.10% + 0.20%)
        cheap = tr.Trend(small(min_round_trip_cost_pct=0.1), self.folder, self.src)
        self.assertAlmostEqual(cheap.round_trip("BTC"), 0.003)


class BtcFilterTests(Base):
    # BTC falls through the window: below its 10-day average from the start on
    series = {"BTC": [30.0 - 0.3 * i for i in range(60)], "ETH": ETH, "SOL": SOL}

    def test_the_filter_does_not_enter_while_btc_is_below_its_average(self):
        self.run_at(S + 1)
        self.run_at(S + 10)
        self.assertEqual([r["coin"] for r in self.trades("trend")], ["ETH"])
        self.assertEqual(self.trades("trend + BTC filter"), [])
        self.assertEqual(self.state()["books"]["trend_btc"]["open"], {})

    def test_it_enters_when_btc_is_above_and_then_follows_the_normal_exit_even_if_btc_falls(self):
        # BTC above its average until day 22, then falling: ETH crossed up on 21 (BTC above), exits on 24
        btc = [10.0 + 0.3 * i for i in range(23)] + [16.0 - 1.0 * (i - 22) for i in range(23, 60)]
        src = Fake({"BTC": btc, "ETH": ETH, "SOL": SOL})
        self.src = src
        self.run_at(S + 1)
        self.run_at(S + 10)
        for line in ("trend", "trend + BTC filter"):
            (t,) = self.trades(line)
            self.assertEqual((t["coin"], t["entry_date"], t["exit_date"]), ("ETH", day(21), day(24)), line)


class SafetyTests(Base):
    def test_a_second_run_the_same_day_changes_nothing(self):
        self.run_at(S + 1)
        self.run_at(S + 10)
        before = snapshot(self.folder)
        self.src.calls.clear()
        self.assertEqual(self.run_at(S + 10), [])
        self.assertEqual(snapshot(self.folder), before)
        self.assertEqual(self.src.calls, [])               # and it did not even ask for prices

    def test_catching_up_after_missed_days_equals_running_every_day(self):
        every = os.path.join(self.tmp.name, "every")
        for i in range(S + 1, S + 14):
            self.run_at(i, folder=every)
        self.run_at(S + 1)
        self.run_at(S + 13)                                # nothing between: 12 days to catch up
        for name in ("trades.csv", "equity.csv", "state.json"):
            with open(os.path.join(every, name)) as a, open(os.path.join(self.folder, name)) as b:
                self.assertEqual(a.read(), b.read(), name)

    def test_no_duplicate_trades_even_if_the_state_is_lost(self):
        self.run_at(S + 1)
        self.run_at(S + 10)
        n = len(self.trades())
        os.remove(os.path.join(self.folder, "state.json"))   # a rerun from scratch re-creates the same days
        self.run_at(S + 10)
        self.assertEqual(len(self.trades()), n)

    def test_a_missing_candle_is_waited_for_then_recorded(self):
        self.run_at(S + 1)
        self.src.hidden.add(("ETHUSDT", 22))
        self.run_at(S + 4)                                  # days 21..23: day 22 has no ETH candle yet
        self.assertEqual(self.state()["last_day"], day(21))   # stopped before the gap, nothing lost
        log = rows(os.path.join(self.folder, "log.csv"))
        self.assertTrue(any(r["event"] == "waiting" and r["date"] == day(22) for r in log))
        self.src.hidden.clear()                              # it turns up: the days are caught up
        self.run_at(S + 5)
        self.assertEqual(self.state()["last_day"], day(24))
        self.assertEqual([r["coin"] for r in self.trades()][:1], ["ETH"])

    def test_data_that_never_comes_is_recorded_as_missing_not_dropped(self):
        self.run_at(S + 1)
        self.src.hidden.add(("SOLUSDT", 22))
        self.run_at(S + 8)                                   # day 22 is now 5 days old: past the grace days
        s = self.state()
        self.assertEqual(s["last_day"], day(S + 7))
        log = rows(os.path.join(self.folder, "log.csv"))
        self.assertTrue(any(r["coin"] == "SOL" and r["event"] == "no candle" and r["date"] == day(22)
                            for r in log))
        self.assertEqual(sorted(s["coins"]), ["BTC", "ETH", "SOL"])     # still in the list
        self.assertIn("SOL", s["books"]["buy_hold"]["open"])

    def test_a_failing_source_is_logged_once_a_day_and_nothing_else_changes(self):
        self.run_at(S + 1)
        self.src.broken.add("ETHUSDT")
        self.run_at(S + 5)
        before = snapshot(self.folder)
        self.run_at(S + 5)
        self.assertEqual(snapshot(self.folder), before)
        fails = [r for r in rows(os.path.join(self.folder, "log.csv")) if r["event"] == "fetch failed"]
        self.assertEqual(len(fails), 1)
        self.assertEqual((fails[0]["coin"], fails[0]["date"]), ("ETH", day(S + 4)))
        self.assertIn("HTTP 500", fails[0]["detail"])

    def test_a_fallback_to_the_daily_files_is_recorded(self):
        class Fallback(Fake):
            def candles(self, symbol, first, last):
                rows, _, _ = super().candles(symbol, first, last)
                return rows, tr.ARCHIVE_SOURCE, "data-api.binance.vision failed: HTTP 403"
        self.src = Fallback(copy.deepcopy(self.series))
        self.run_at(S + 1)
        log = rows(os.path.join(self.folder, "log.csv"))
        self.assertEqual(sum(1 for r in log if r["event"] == "fallback source"), 3)    # one per coin
        self.assertTrue(any(r["event"] == "source" and r["detail"] == tr.ARCHIVE_SOURCE for r in log))
        self.assertEqual(self.state()["start_day"], day(S))                            # and it works the same

    def test_the_first_run_waits_until_every_coin_has_a_candle(self):
        self.src.hidden |= {("SOLUSDT", i) for i in range(S - 5, 60)}
        self.run_at(S + 1)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "state.json")))
        self.assertTrue(any(r["event"] == "not started" for r in rows(os.path.join(self.folder, "log.csv"))))

    def test_the_frozen_coin_list_cannot_change(self):
        self.run_at(S + 1)
        other = small(coins=[{"name": n, "symbol": n + "USDT"} for n in ("BTC", "ETH")])
        with self.assertRaises(RuntimeError):
            self.run_at(S + 2, cfg=other)

    def test_the_candles_and_the_source_are_recorded(self):
        self.run_at(S + 1)
        stored = rows(os.path.join(self.folder, "candles", "ETH.csv"))
        self.assertEqual(stored[-1]["date"], day(S))
        self.assertEqual(len(stored), S + 1)                # all there is before the start day (days 0..20)
        self.assertEqual(self.src.calls[0][1], D0 + timedelta(days=S - 39))   # asked for history_days (40)
        log = rows(os.path.join(self.folder, "log.csv"))
        self.assertTrue(any(r["event"] == "source" and r["detail"] == tr.API_SOURCE for r in log))


class FrozenConfigTests(unittest.TestCase):
    def test_the_18_coins_are_the_backtests_and_notional_is_a_18th(self):
        from backtest import universe
        coins = REAL["trend"]["coins"]
        self.assertEqual([c["name"] for c in coins], list(universe.COINS))
        self.assertEqual(len(coins), 18)
        for c in coins:
            self.assertEqual(c["symbol"], universe.COINS[c["name"]][-1])
        t = REAL["trend"]
        self.assertEqual((t["average_days"], t["btc_filter_days"], t["portfolio_usdt"]), (50, 200, 1000))
        self.assertAlmostEqual(tr.Trend(REAL, "x", None).notional, 1000 / 18)
        self.assertEqual(sorted(t["majors"]), sorted(universe.MAJORS))
        self.assertEqual((t["fee_per_side_pct"], t["slippage_major_pct"], t["slippage_other_pct"]),
                         (universe.FEE * 100, universe.SLIPPAGE_MAJOR * 100, universe.SLIPPAGE_OTHER * 100))
        self.assertGreaterEqual(t["min_round_trip_cost_pct"], 0.5)

    def test_it_is_the_backtests_50_day_variant(self):
        from backtest import strategies
        s = strategies.TrendFollowing((REAL["trend"]["average_days"],))
        self.assertEqual(s.name, "close above 50-day average")

    def test_the_workflow_uses_only_the_github_token(self):
        with open(os.path.join(HERE, ".github", "workflows", "trend.yml")) as fh:
            text = fh.read()
        self.assertNotIn("secrets.", text)
        self.assertIn('cron: "10 0 * * *"', text)
        self.assertIn("contents: write", text)
        self.assertIn("cancel-in-progress: false", text)


def zip_bytes(name, lines):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, "\n".join(lines))
    return buf.getvalue()


class Http:
    """Answers like data-api.binance.vision and data.binance.vision."""

    def __init__(self, api=200, archive=None):
        self.api, self.archive, self.calls = api, archive or {}, []

    class Resp:
        def __init__(self, code, body=None, content=b""):
            self.status_code, self._body, self.content = code, body, content

        def json(self):
            return self._body

    def get(self, url, timeout=None, params=None):
        self.calls.append(url)
        if "data-api" in url:
            if self.api != 200:
                return self.Resp(self.api)
            t = int(datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp() * 1000)
            return self.Resp(200, [[t, "1", "2", "0.5", "1.5", "10", t + 86399999],
                                   [t + 86400000, "1.5", "2", "1", "1.8", "11", t + 2 * 86400000 - 1]])
        key = url.rsplit("/", 1)[1]
        if key in self.archive:
            return self.Resp(200, content=self.archive[key])
        return self.Resp(404)


class SourceTests(unittest.TestCase):
    def test_the_public_endpoint_comes_first(self):
        http = Http()
        rows_, source, note = tr.BinanceDaily(http).candles("BTCUSDT", date(2026, 10, 9), date(2026, 10, 10))
        self.assertEqual((source, note), (tr.API_SOURCE, ""))
        self.assertEqual([r[0] for r in rows_], ["2026-10-09", "2026-10-10"])
        self.assertEqual(rows_[1][4], 1.8)
        self.assertEqual(len(http.calls), 1)

    def test_the_daily_files_are_the_fallback_and_microsecond_times_are_read(self):
        us = int(datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp() * 1_000_000)
        line = f"{us},1,2,0.5,1.5,10,{us + 86399999999},0,5,0,0,0"
        http = Http(api=403, archive={"BTCUSDT-1d-2026-10-09.zip": zip_bytes("a.csv", [line])})
        rows_, source, note = tr.BinanceDaily(http).candles("BTCUSDT", date(2026, 10, 9), date(2026, 10, 10))
        self.assertEqual(source, tr.ARCHIVE_SOURCE)
        self.assertIn("HTTP 403", note)
        self.assertEqual([r[0] for r in rows_], ["2026-10-09"])      # the 10th isn't published yet (404): fine

    def test_both_failing_is_an_error_naming_both(self):
        class Dead(Http):
            def get(self, url, timeout=None, params=None):
                import requests
                raise requests.ConnectionError("boom")
        with self.assertRaises(tr.FetchError) as ctx:
            tr.BinanceDaily(Dead()).candles("BTCUSDT", date(2026, 10, 9), date(2026, 10, 10))
        self.assertIn(tr.API_SOURCE, str(ctx.exception))
        self.assertIn(tr.ARCHIVE_SOURCE, str(ctx.exception))


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name

    def write(self, trades, equity):
        with open(os.path.join(self.folder, "trades.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(tr.TRADE_COLUMNS)
            for line, pnl, entry in trades:
                row = dict.fromkeys(tr.TRADE_COLUMNS, "")
                row.update(line=line, coin="ETH", pnl_usdt=pnl, entry_date=entry)
                w.writerow([row[c] for c in tr.TRADE_COLUMNS])
        with open(os.path.join(self.folder, "equity.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(tr.EQUITY_COLUMNS)
            for r in equity:
                w.writerow(r)

    def text(self):
        lines, passed = sc.trend_section(self.folder, REAL["trend"])
        return "\n".join(lines), passed

    def days(self, n):
        return [(D0 + timedelta(days=i)).isoformat() for i in range(n)]

    def test_the_gate_is_the_same_as_everyone_elses(self):
        self.assertEqual((sc.MIN_CLOSED, sc.MIN_DAYS), (30, 14))
        # 30 trades on 15 days, profit with and without the best one: PASS
        days = self.days(15)
        trades = [("trend", 2.0, days[i % 15]) for i in range(30)] + [("trend + BTC filter", 1.0, days[0])]
        self.write(trades, [[days[0], 1000, 1000, 990, 0, 0, 1, 0, 0], [days[1], 1100, 1000, 1200, 5, 0, 3, 0, 0]])
        text, passed = self.text()
        self.assertEqual(passed, ["trend"])
        self.assertIn("| trend | 30 | 30 | +60.00 USDT | +58.00 USDT | 15 | 5.0% | **PASS** |", text)
        self.assertIn("<!-- checklist-pass: trend -->", text)
        self.assertIn("| trend + BTC filter | 1 | 1 | +1.00 USDT | +0.00 USDT | 1 | 0.0% | not yet: "
                      "29 more closed trades; not above 0 without the best trade; trades on 13 more days |", text)

    def test_each_part_of_the_gate_can_fail(self):
        days = self.days(20)
        eq = [[days[0], 1000, 1000, 1000, 0, 0, 0, 0, 0]]
        base = [("trend", 2.0, days[i % 20]) for i in range(30)]
        self.write(base[:29], eq)
        self.assertIn("1 more closed trades", self.text()[0])
        self.write([("trend", 2.0, days[0])] * 29 + [("trend", 50.0, days[1])] + [("trend", -60.0, days[2])] * 3, eq)
        self.assertIn("profit after costs not above 0", self.text()[0])
        self.write([("trend", 100.0, days[0])] + [("trend", -1.0, days[1])] * 29, eq)
        self.assertIn("not above 0 without the best trade", self.text()[0])
        self.write([("trend", 2.0, days[i % 5]) for i in range(30)], eq)
        self.assertIn("trades on 9 more days", self.text()[0])

    def test_more_than_30_percent_from_the_peak_is_fail_kill_and_never_a_pass(self):
        days = self.days(15)
        trades = [("trend", 2.0, days[i % 15]) for i in range(30)]
        self.write(trades, [[days[0], 1000, 1000, 1000, 0, 0, 0, 0, 0],
                            [days[1], 700, 1000, 1000, 31.5, 0, 0, 0, 0]])
        text, passed = self.text()
        self.assertEqual(passed, [])
        self.assertIn("**FAIL KILL** (fell 31.5% from its peak)", text)
        self.assertEqual(text.count("FAIL KILL"), 2)         # (the second one is the legend line)

    def test_buy_and_hold_and_the_max_falls_each_get_a_line(self):
        days = self.days(3)
        self.write([], [[days[0], 1000, 1000, 1000, 0, 0, 0, 0, 0], [days[2], 980, 995, 1130, 4, 2.5, 12, 0, 0]])
        text, _ = self.text()
        self.assertIn("**Buy and hold** (same 18 coins in equal parts from the start day): 1130.00 USDT "
                      "(+13.0%), max fall 12.0%.", text)
        self.assertIn("**Max fall from peak:** trend 4.0%; trend + BTC filter 2.5%; buy and hold 12.0%.", text)
        self.assertIn("Started 2026-01-01, latest day 2026-01-03", text)
        self.assertIn("survivorship", text)

    def test_no_results_yet(self):
        text, passed = self.text()
        self.assertIn("No results yet", text)
        self.assertEqual(passed, [])

    def test_it_is_in_the_daily_report_and_the_pass_is_named(self):
        days = self.days(15)
        self.write([("trend", 2.0, days[i % 15]) for i in range(30)],
                   [[days[0], 1000, 1000, 1000, 0, 0, 0, 0, 0], [days[1], 1060, 1000, 1000, 0, 0, 0, 0, 0]])
        lines, passed = sc.trend_section(self.folder, REAL["trend"])
        body = sc.report([], "2026-01-02", None, None, trend=lines)
        self.assertIn("### Trend forward test", body)
        self.assertIn(sc.PASS_MARKER.format("trend"), body)
        self.assertEqual(passed, ["trend"])


class RunScriptTests(unittest.TestCase):
    def test_the_script_runs_and_a_rerun_changes_nothing(self):
        import trend_bot
        cfg = small()
        src = Fake({"BTC": BTC_UP, "ETH": ETH, "SOL": SOL})
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, "trend")
            tr.Trend(cfg, folder, src, out=lambda *a: None).run(at(S + 1))
            before = snapshot(folder)
            tr.Trend(cfg, folder, src, out=lambda *a: None).run(at(S + 1))
            self.assertEqual(snapshot(folder), before)
        self.assertTrue(callable(trend_bot.main))


if __name__ == "__main__":
    unittest.main()
