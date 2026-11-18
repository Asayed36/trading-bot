"""Checks for the exact market prices (recording only, nothing may read them for any buy, sell,
filter or exit):

  - screener/backdrop.py: btc/eth/sol_price_usd from the same Binance answer (lastPrice), in
    candidates.csv and entries.csv next to the change columns, with no extra request;
  - screener/market_prices.py: the once-a-minute log in data/market/ (inside launch-bot);
  - market_prices.py: the lookup command;
  - screener/health.py: the "market prices: server" row.

All Binance answers here are fake. Run with:  python -m unittest -v
"""

import asyncio
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

import launch_bot  # noqa: E402
import market_prices as lookup  # noqa: E402
from run import load_config  # noqa: E402
from screener import backdrop as bd  # noqa: E402
from screener import health  # noqa: E402
from screener import market_prices as mp  # noqa: E402
from screener import token_record as tr  # noqa: E402
from screener.filters import Result  # noqa: E402
from screener.paper_trader import ENTRY_COLUMNS, PaperTrader  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = running(load_config())
NOW = datetime(2026, 11, 18, 19, 0, 0, tzinfo=timezone.utc)
MINT = "MintPRICE"
PAIR = {"dexId": "pumpswap", "pairAddress": "P1", "priceUsd": "0.5", "marketCap": 250000,
        "liquidity": {"usd": 40000}, "pairCreatedAt": int((NOW - timedelta(hours=1)).timestamp() * 1000),
        "baseToken": {"address": MINT, "symbol": "AAA", "name": "Aaa"}}
# Binance's rolling-window ticker answers: strings, as Binance sends them
H1 = [{"symbol": "BTCUSDT", "priceChangePercent": "0.4567", "lastPrice": "91234.56000000"},
      {"symbol": "ETHUSDT", "priceChangePercent": "1.234", "lastPrice": "3100.12000000"},
      {"symbol": "SOLUSDT", "priceChangePercent": "-0.5", "lastPrice": "141.37000000"}]
D1 = [{"symbol": "BTCUSDT", "priceChangePercent": "-2.5", "lastPrice": "91234.56000000"},
      {"symbol": "ETHUSDT", "priceChangePercent": "-3.1", "lastPrice": "3100.12000000"},
      {"symbol": "SOLUSDT", "priceChangePercent": "-4.0", "lastPrice": "141.37000000"}]
PRICES = {"btc_price_usd": 91234.56, "eth_price_usd": 3100.12, "sol_price_usd": 141.37}
# Binance's latest-price ticker answer (/api/v3/ticker/price)
LATEST = [{"symbol": "BTCUSDT", "price": "91234.56000000"},
          {"symbol": "ETHUSDT", "price": "3100.12000000"},
          {"symbol": "SOLUSDT", "price": "141.37000000"}]


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


def ticker_get(calls):
    def get(url, **kw):
        calls.append((url, kw))
        return Resp(H1 if kw["params"]["windowSize"] == "1h" else D1)
    return get


def rows(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------
# 1. the prices next to the changes (screener/backdrop.py)
# ---------------------------------------------------------------------

class BackdropPriceTests(unittest.TestCase):
    def test_last_price_comes_from_the_1h_answer_exactly(self):
        self.assertEqual({k: v for k, v in bd.parse("1h", H1).items() if k in bd.PRICE_COLUMNS},
                         PRICES)
        self.assertEqual(bd.parse("1d", D1), {"btc_change_24h_pct": -2.5})   # no price from 1d
        for junk in ("x", "nan", "inf", "0", "-5", None, ""):
            got = bd.parse("1h", [{"symbol": "BTCUSDT", "priceChangePercent": "1", "lastPrice": junk}])
            self.assertEqual(got, {"btc_change_1h_pct": 1.0}, junk)

    def test_no_extra_request_and_the_prices_come_with_the_changes(self):
        calls = []
        b = bd.MarketBackdrop(get=ticker_get(calls), clock=lambda: NOW)
        values = b()
        self.assertEqual(len(calls), 2)                      # the same 2 requests as before
        for c, v in PRICES.items():
            self.assertEqual(values[c], v)
        self.assertEqual(values["btc_change_1h_pct"], 0.46)
        for _ in range(20):
            b()
        self.assertEqual(len(calls), 2)                      # the 15-minute cache still holds

    def test_the_cache_file_keeps_the_prices(self):
        with tempfile.TemporaryDirectory() as d:
            cache, calls = os.path.join(d, "backdrop_cache.json"), []
            bd.MarketBackdrop(cache, get=ticker_get(calls), clock=lambda: NOW)()
            again = bd.MarketBackdrop(cache, get=ticker_get(calls),
                                      clock=lambda: NOW + timedelta(minutes=5))()
            self.assertEqual(len(calls), 2)
            for c, v in PRICES.items():
                self.assertEqual(again[c], v)

    def test_candidates_csv_has_the_prices_after_the_changes(self):
        cols = tr.CANDIDATE_COLUMNS
        i = cols.index("sol_change_1h_pct")
        self.assertEqual(cols[i + 1:i + 4], ["btc_price_usd", "eth_price_usd", "sol_price_usd"])
        with tempfile.TemporaryDirectory() as d:
            calls = []
            log = tr.CandidateLog(d, "test", backdrop=bd.MarketBackdrop(get=ticker_get(calls),
                                                                         clock=lambda: NOW))
            pair = dict(PAIR)
            self.assertTrue(log.add(Result(MINT, "AAA", "Aaa", pair), None, {}, NOW, "FAIL", "x",
                                    True, "d"))
            (row,) = rows(os.path.join(d, "candidates.csv"))
            self.assertEqual((row["btc_price_usd"], row["eth_price_usd"], row["sol_price_usd"]),
                             ("91234.56", "3100.12", "141.37"))
            self.assertEqual(row["btc_change_1h_pct"], "0.46")

    def test_entries_csv_has_the_prices_after_btc_change_1h_and_old_rows_stay(self):
        i = ENTRY_COLUMNS.index("btc_change_1h_pct")
        self.assertEqual(ENTRY_COLUMNS[i + 1:], ["btc_price_usd", "eth_price_usd", "sol_price_usd"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "entries.csv")
            old_cols = ENTRY_COLUMNS[:i + 1]               # a file from before the prices
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(old_cols)
                w.writerow(["2026-11-01 00:00:00", "OLD"] + [""] * (len(old_cols) - 3) + ["0.2"])
            values = dict(bd.parse("1h", H1), **bd.parse("1d", D1))
            calls = []
            with mock.patch.object(PaperTrader, "backdrop", lambda: (calls.append(1), values)[1]):
                trader = PaperTrader(CFG["paper_trading"], d)
                self.assertIsNotNone(trader.buy(Result(MINT, "AAA", "Aaa", PAIR), when=NOW))
            self.assertEqual(len(calls), 1)                  # one lookup for the four cells
            old, new = rows(path)
            self.assertEqual((old["symbol"], old["btc_change_1h_pct"], old["btc_price_usd"]),
                             ("OLD", "0.2", ""))
            self.assertEqual((new["btc_change_1h_pct"], new["btc_price_usd"], new["eth_price_usd"],
                              new["sol_price_usd"]), ("0.46", "91234.56", "3100.12", "141.37"))

    def test_a_buy_is_the_same_with_or_without_the_prices(self):
        """Recording only: the journal and positions do not depend on the prices."""
        out = []
        for source in (lambda: dict(bd.parse("1h", H1)), lambda: {}, None):
            with tempfile.TemporaryDirectory() as d, \
                    mock.patch.object(PaperTrader, "backdrop", source):
                trader = PaperTrader(CFG["paper_trading"], d)
                self.assertIsNotNone(trader.buy(Result(MINT, "AAA", "Aaa", PAIR), when=NOW))
                with open(os.path.join(d, "journal.csv")) as fh:
                    journal = fh.read()
                out.append((journal, json.dumps(trader.state, sort_keys=True, default=str)))
        self.assertEqual(out[0], out[1])
        self.assertEqual(out[0], out[2])


# ---------------------------------------------------------------------
# 2. the once-a-minute log (screener/market_prices.py)
# ---------------------------------------------------------------------

class MinuteLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "market")
        self.calls = []

    def get(self, answer):
        def get(url, **kw):
            self.calls.append((url, kw))
            if isinstance(answer, Exception):
                raise answer
            return answer
        return get

    def health(self):
        with open(os.path.join(self.folder, "health.json")) as fh:
            return json.load(fh)

    def test_one_public_request_for_all_three_with_a_5_second_timeout(self):
        log = mp.MarketPriceLog(self.folder, get=self.get(Resp(LATEST)))
        row = log.record(NOW)
        self.assertEqual(row, {"time_utc": "2026-11-18 19:00:00", "btc_usd": "91234.56",
                               "eth_usd": "3100.12", "sol_usd": "141.37"})
        (url, kw), = self.calls
        self.assertEqual(url, "https://data-api.binance.vision/api/v3/ticker/price")
        self.assertEqual(kw, {"params": {"symbols": '["BTCUSDT","ETHUSDT","SOLUSDT"]'}, "timeout": 5})
        self.assertEqual(mp.URL.split("/")[2], bd.URL.split("/")[2])   # the backdrop's host

    def test_the_daily_file_and_its_columns(self):
        log = mp.MarketPriceLog(self.folder, get=self.get(Resp(LATEST)))
        log.record(NOW - timedelta(minutes=1))               # 18:59 on the 18th
        log.record(NOW)
        log.record(datetime(2026, 11, 19, 0, 0, 7, tzinfo=timezone.utc))    # a new UTC day
        day18 = rows(os.path.join(self.folder, "prices-2026-11-18.csv"))
        self.assertEqual([r["time_utc"] for r in day18], ["2026-11-18 18:59:00", "2026-11-18 19:00:00"])
        with open(os.path.join(self.folder, "prices-2026-11-18.csv")) as fh:
            self.assertEqual(fh.readline().strip(), "time_utc,btc_usd,eth_usd,sol_usd")
        (r19,) = rows(os.path.join(self.folder, "prices-2026-11-19.csv"))
        self.assertEqual(r19["time_utc"], "2026-11-19 00:00:07")

    def test_a_failed_request_leaves_the_row_blank_is_not_retried_and_is_counted(self):
        for answer in (OSError("timed out"), Resp({"code": -1003, "msg": "too many"}, 429),
                       Resp(ValueError("not json")), Resp({"code": 0}), Resp([])):
            with self.subTest(answer=answer):
                self.calls.clear()
                folder = os.path.join(self.tmp.name, str(len(os.listdir(self.tmp.name))))
                log = mp.MarketPriceLog(folder, get=self.get(answer))
                row = log.record(NOW)
                self.assertEqual(len(self.calls), 1)                  # no retry
                self.assertEqual(row, {"time_utc": "2026-11-18 19:00:00", "btc_usd": "",
                                       "eth_usd": "", "sol_usd": ""})
                (saved,) = rows(os.path.join(folder, "prices-2026-11-18.csv"))
                self.assertEqual(saved, row)
                with open(os.path.join(folder, "health.json")) as fh:
                    h = json.load(fh)
                self.assertEqual(h["days"]["2026-11-18"], {"rows": 1, "failures": 1})
                self.assertNotIn("last_price", h)
                self.assertTrue(h["last_error"])

    def test_a_missing_coin_leaves_only_its_cell_blank_and_counts_as_a_failure(self):
        log = mp.MarketPriceLog(self.folder, get=self.get(Resp(LATEST[:2] + [{"symbol": "SOLUSDT",
                                                                               "price": "x"}])))
        row = log.record(NOW)
        self.assertEqual((row["btc_usd"], row["eth_usd"], row["sol_usd"]), ("91234.56", "3100.12", ""))
        h = self.health()
        self.assertEqual(h["days"]["2026-11-18"], {"rows": 1, "failures": 1})
        self.assertEqual(h["last_error"], "no price for sol_usd")
        self.assertEqual(h["last_price"]["btc_usd"], "91234.56")

    def test_one_row_a_minute_even_across_a_restart(self):
        log = mp.MarketPriceLog(self.folder, get=self.get(Resp(LATEST)))
        self.assertIsNotNone(log.record(NOW))
        self.assertIsNone(log.record(NOW + timedelta(seconds=30)))
        again = mp.MarketPriceLog(self.folder, get=self.get(Resp(LATEST)))   # a restart
        self.assertIsNone(again.record(NOW + timedelta(seconds=50)))
        self.assertIsNotNone(again.record(NOW + timedelta(minutes=1)))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(rows(os.path.join(self.folder, "prices-2026-11-18.csv"))), 2)
        self.assertEqual(self.health()["days"]["2026-11-18"], {"rows": 2, "failures": 0})

    def test_health_counts_per_day_and_keeps_the_last_good_price(self):
        answers = [Resp(LATEST), OSError("down"), Resp(LATEST)]

        def get(url, **kw):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        log = mp.MarketPriceLog(self.folder, get=get)
        for i in range(3):
            log.record(NOW + timedelta(minutes=i))
        h = self.health()
        self.assertEqual(h["days"]["2026-11-18"], {"rows": 3, "failures": 1})
        self.assertEqual(h["last_price"]["time_utc"], "2026-11-18 19:02:00")
        self.assertEqual(h["updated"], "2026-11-18 19:02:00")
        self.assertEqual(h["error_at"], "2026-11-18 19:01:00")

    def test_old_days_are_dropped_from_health(self):
        log = mp.MarketPriceLog(self.folder, get=self.get(Resp(LATEST)))
        for i in range(mp.KEEP_DAYS + 3):
            log.record(NOW + timedelta(days=i))
        self.assertEqual(len(self.health()["days"]), mp.KEEP_DAYS)

    def test_it_never_raises(self):
        def boom(*a, **k):
            raise RuntimeError("anything")
        log = mp.MarketPriceLog(self.folder, get=boom, clock=boom)
        self.assertIsNone(log.record())
        blocked = os.path.join(self.tmp.name, "a-file")
        with open(blocked, "w") as fh:
            fh.write("x")
        log = mp.MarketPriceLog(os.path.join(blocked, "market"), get=self.get(Resp(LATEST)))
        self.assertIsNone(log.record(NOW))                   # the folder can't be made

    def test_launch_bot_runs_it_once_a_minute_and_a_failure_never_stops_it(self):
        class Fake:
            def __init__(self):
                self.n = 0

            def record(self):
                self.n += 1
                raise RuntimeError("never reaches the bot")

        async def go():
            runner = launch_bot.Runner.__new__(launch_bot.Runner)
            runner.stop, runner.price_log = asyncio.Event(), Fake()
            clock = [1_000_000_059.0]
            with mock.patch.object(launch_bot.time, "time", lambda: clock[0]), \
                    mock.patch.object(launch_bot.asyncio, "wait_for",
                                      side_effect=self._timeouts(runner, clock, 3)):
                await runner.market_prices()
            return runner.price_log.n
        self.assertEqual(asyncio.run(go()), 3)

    @staticmethod
    def _timeouts(runner, clock, n):
        """A fake asyncio.wait_for: each wait is a minute passing; after n the bot stops."""
        waits = []

        async def wait_for(aw, timeout):
            aw.close()
            waits.append(timeout)
            assert 0 < timeout <= 60.5, timeout                # waits for the next minute's start
            clock[0] += timeout
            if len(waits) > n:
                runner.stop.set()
                return True
            raise asyncio.TimeoutError
        return wait_for

    def test_launch_bot_starts_it_only_for_the_real_service(self):
        with open(os.path.join(HERE, "launch_bot.py")) as fh:
            source = fh.read()
        self.assertIn("price_log = MarketPriceLog(os.path.join(folder, MARKET_FOLDER))", source)
        self.assertIn("Runner(cfg, folder, watcher, price_log=price_log)", source)
        self.assertIn("runner = Runner(quiet, folder)", source)   # --test saves no prices

    def test_files_are_pushed_and_temp_files_are_not(self):
        for path in ("data/market/prices-2027-01-15.csv", "data/market/health.json"):
            self.assertNotEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                               cwd=HERE).returncode, 0, path)
        for path in ("data/market/health.json.123.tmp", "data/market/other.txt"):
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                            cwd=HERE).returncode, 0, path)
        with open(os.path.join(HERE, "deploy", "push_results.sh")) as fh:
            text = fh.read()
        self.assertIn("data/market)", text)
        self.assertIn(" data/market)\n", text.split("FOLDERS=(")[1].split("\n")[0] + "\n")

    def test_recording_only_nothing_else_reads_the_prices(self):
        allowed = {"screener/backdrop.py", "screener/market_prices.py", "market_prices.py",
                   "launch_bot.py", "screener/health.py", "screener/token_record.py",
                   "screener/paper_trader.py"}
        # (sol_usd alone is the launch strategy's own SOL price, unrelated)
        words = (r"btc_price_usd\|eth_price_usd\|sol_price_usd\|market_prices\|MarketPriceLog"
                 r"\|data/market\|MARKET_FOLDER\|prices-")
        found = subprocess.run(["git", "grep", "-l", words, "--", "*.py", ":!tests/"],
                               cwd=HERE, capture_output=True, text=True).stdout.split()
        self.assertEqual(set(found) - allowed, set())
        for name in ("screener/market_prices.py", "market_prices.py"):
            with open(os.path.join(HERE, name)) as fh:
                source = fh.read().lower()
            for word in ("private_key", "secret", "wallet.", "sign(", "api_key", "post("):
                self.assertNotIn(word, source, name)


# ---------------------------------------------------------------------
# 3. the lookup command (market_prices.py)
# ---------------------------------------------------------------------

class LookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name

    def write(self, day, lines_):
        with open(os.path.join(self.folder, f"prices-{day}.csv"), "w", newline="") as fh:
            fh.write("time_utc,btc_usd,eth_usd,sol_usd\n" + "".join(l + "\n" for l in lines_))

    def run_it(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(lookup.main(["--folder", self.folder, *argv]), 0)
        return buf.getvalue().splitlines()

    def test_one_line_per_minute_with_the_change_from_the_first(self):
        self.write("2026-11-18", ["2026-11-18 19:00:00,100000,4000,200",
                                  "2026-11-18 19:01:00,101000,3960,200",
                                  "2026-11-18 19:02:01,99000,4040,210"])
        out = self.run_it("--at", "2026-11-18 19:00", "--minutes", "2")
        self.assertEqual(len(out), 2 + 3)                    # title, header, 3 minutes
        self.assertIn("2026-11-18 19:00 to 2026-11-18 19:02 UTC", out[0])
        self.assertEqual(out[2].split(), ["2026-11-18", "19:00", "100,000.00", "+0.00%",
                                          "4,000.00", "+0.00%", "200.00", "+0.00%"])
        self.assertEqual(out[3].split(), ["2026-11-18", "19:01", "101,000.00", "+1.00%",
                                          "3,960.00", "-1.00%", "200.00", "+0.00%"])
        self.assertEqual(out[4].split(), ["2026-11-18", "19:02", "99,000.00", "-1.00%",
                                          "4,040.00", "+1.00%", "210.00", "+5.00%"])

    def test_sixty_minutes_across_midnight_and_gaps(self):
        self.write("2026-11-18", ["2026-11-18 23:59:00,100,10,1"])
        self.write("2026-11-19", ["2026-11-19 00:00:00,110,,1.5", "2026-11-19 00:58:00,90,11,2"])
        out = self.run_it("--at", "2026-11-18 23:59", "--minutes", "60")
        self.assertEqual(len(out), 2 + 61)                   # from the time to 60 minutes later
        self.assertEqual(out[3].split(), ["2026-11-19", "00:00", "110.00", "+10.00%", "-",
                                          "1.50", "+50.00%"])
        self.assertEqual(out[4], "2026-11-19 00:01  no row saved")
        self.assertTrue(out[2 + 59].startswith("2026-11-19 00:58"))
        self.assertIn("-10.00%", out[2 + 59])                # 00:58: BTC 90 vs 100
        self.assertIn("+10.00%", out[2 + 59])                # ETH 11 vs 10
        self.assertEqual(out[-1], "2026-11-19 00:59  no row saved")

    def test_first_line_blank_uses_the_first_known_price_and_says_so(self):
        self.write("2026-11-18", ["2026-11-18 19:00:00,,,", "2026-11-18 19:01:00,50,5,2",
                                  "2026-11-18 19:02:00,55,5,2"])
        out = self.run_it("--at", "2026-11-18 19:00", "--minutes", "2")
        self.assertEqual(out[2].split(), ["2026-11-18", "19:00", "-", "-", "-"])
        self.assertIn("+10.00%", out[4])
        self.assertIn("Note: the first line has no price for BTC, ETH, SOL", out[-1])

    def test_no_files_says_how_to_get_them(self):
        out = self.run_it("--at", "2026-11-18 19:00", "--minutes", "1")
        self.assertIn("git pull", out[-1])

    def test_bad_input_is_refused(self):
        for argv in (["--at", "yesterday"], ["--at", "2026-11-18 19:00", "--minutes", "-1"], []):
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
                    mock.patch("sys.stderr", io.StringIO()):
                lookup.main(["--folder", self.folder, *argv])

    def test_it_reads_what_the_log_writes(self):
        log = mp.MarketPriceLog(self.folder, get=lambda url, **kw: Resp(LATEST))
        log.record(NOW)
        log.record(NOW + timedelta(minutes=1))
        out = self.run_it("--at", "2026-11-18 19:00", "--minutes", "1")
        self.assertEqual(out[2].split(), ["2026-11-18", "19:00", "91,234.56", "+0.00%",
                                          "3,100.12", "+0.00%", "141.37", "+0.00%"])


# ---------------------------------------------------------------------
# 4. the health row
# ---------------------------------------------------------------------

class HealthRowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name
        self.got = []

    def add(self, check, status, detail, problem=None):
        self.got.append((check, status, detail, problem))

    def save(self, data):
        os.makedirs(os.path.join(self.folder, "market"), exist_ok=True)
        with open(os.path.join(self.folder, "market", "health.json"), "w") as fh:
            json.dump(data, fh)

    def test_not_running_yet(self):
        health.add_market_prices(self.add, self.folder, CFG, NOW)
        ((name, status, detail, _),) = self.got
        self.assertEqual((name, status), ("market prices: server", health.INFO))
        self.assertIn("no prices pushed yet", detail)

    def test_rows_today_failures_and_the_last_price(self):
        self.save({"days": {"2026-11-17": {"rows": 1440, "failures": 2},
                            "2026-11-18": {"rows": 1140, "failures": 1}},
                   "last_price": {"time_utc": "2026-11-18 18:59:00", "btc_usd": "91234.56",
                                  "eth_usd": "3100.12", "sol_usd": "141.37"},
                   "last_error": "ReadTimeout: timed out", "error_at": "2026-11-18 03:12:00",
                   "updated": "2026-11-18 18:59:00"})
        health.add_market_prices(self.add, self.folder, CFG, NOW)
        ((name, status, detail, problem),) = self.got
        self.assertEqual((name, status, problem), ("market prices: server", health.OK, None))
        self.assertIn("today 1140 row(s), 1 failed; yesterday 1440 row(s), 2 failed", detail)
        self.assertIn("last price saved 2026-11-18 18:59 UTC (1 min ago): BTC $91,234.56, "
                      "ETH $3,100.12, SOL $141.37", detail)
        self.assertIn("last failure 2026-11-18 03:12:00 UTC", detail)

    def test_a_stale_log_warns(self):
        self.save({"days": {}, "last_price": {"time_utc": "2026-11-18 12:00:00", "btc_usd": "1"},
                   "updated": "2026-11-18 18:59:00"})
        health.add_market_prices(self.add, self.folder, CFG, NOW)
        ((_, status, detail, problem),) = self.got
        self.assertEqual(status, health.WARN)
        self.assertIn("no price saved since 2026-11-18 12:00 UTC", problem)
        self.assertIn("today 0 row(s), 0 failed", detail)

    def test_only_failures_warns(self):
        self.save({"days": {"2026-11-18": {"rows": 5, "failures": 5}}, "last_error": "HTTP 451",
                   "error_at": "2026-11-18 18:59:00", "updated": "2026-11-18 18:59:00"})
        health.add_market_prices(self.add, self.folder, CFG, NOW)
        ((_, status, detail, problem),) = self.got
        self.assertEqual(status, health.WARN)
        self.assertIn("no price saved yet", detail)
        self.assertIn("since ever", problem)

    def test_it_is_in_the_daily_comparison(self):
        self.save({"days": {"2026-11-18": {"rows": 3, "failures": 0}},
                   "last_price": {"time_utc": "2026-11-18 18:59:00", "btc_usd": "91234.56",
                                  "eth_usd": "3100.12", "sol_usd": "141.37"},
                   "updated": "2026-11-18 18:59:00"})
        text = "\n".join(health.health_lines(self.folder, CFG, NOW))
        self.assertIn("| market prices: server | ✅ today 3 row(s), 0 failed", text)
        self.save({"days": "junk", "last_price": {"time_utc": "not a time"}})
        text = "\n".join(health.health_lines(self.folder, CFG, NOW))
        self.assertIn("| market prices: server | ⚠️", text)


if __name__ == "__main__":
    unittest.main()
