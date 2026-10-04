"""Checks for the "main (1 min)" paper strategy (main_1min.py), with the
made-up data of screener/demo.py.
Run with:  python -m unittest -v
"""

import csv
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compare  # noqa: E402
import main_1min as m1  # noqa: E402
from run import load_config, run  # noqa: E402
from screener.api import ApiError, RateLimited  # noqa: E402
from screener.demo import GOOD, DemoApi  # noqa: E402

CFG = load_config()
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class Api(DemoApi):
    """DemoApi that records RugCheck questions and can fail on demand."""

    def __init__(self, price_moves=None):
        super().__init__(price_moves)
        self.rugcheck, self.rugcheck_down, self.dex_down = [], None, False

    def latest_profiles(self):
        if self.dex_down:
            raise RateLimited("api.dexscreener.com kept saying 'too many requests'")
        return super().latest_profiles()

    def rugcheck_report(self, address):
        self.rugcheck.append(address)
        if self.rugcheck_down:
            raise self.rugcheck_down
        return super().rugcheck_report(address)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.api = Api()

    def tearDown(self):
        self.tmp.cleanup()

    def bot(self, cfg=CFG, api=None):
        return m1.MainOneMinute(cfg, self.d, api or self.api)

    def path(self, name):
        return os.path.join(self.d, "main-1min", name)


class SameAsMainTests(Base):
    def test_the_same_buys_as_main_in_its_own_folder(self):
        lines = []
        self.bot().run_once(NOW, lines.append)
        mine = rows(self.path("journal.csv"))
        with tempfile.TemporaryDirectory() as other:
            run(DemoApi(), CFG, other, out=lambda *a: None)
            main = rows(os.path.join(other, "journal.csv"))
        self.assertTrue(mine)
        self.assertEqual([(r["action"], r["symbol"], r["reason"], r["usd_amount"]) for r in mine],
                         [(r["action"], r["symbol"], r["reason"], r["usd_amount"]) for r in main])
        self.assertEqual(mine[0]["usd_amount"], "10.00")
        # Only its own folder: none of the GitHub main strategy's files.
        self.assertEqual(sorted(os.listdir(self.d)), ["main-1min"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "main-1min"))),
                         ["entries.csv", "health.json", "journal.csv", "positions.json"])
        self.assertIn("passed", lines[0])

    def test_mains_exits_and_costs(self):
        self.bot().run_once(NOW, lambda *a: None)
        Api.__init__(self.api, {GOOD: 1.6})                        # +60%
        self.bot().run_once(NOW + timedelta(minutes=1), lambda *a: None)
        sell = [r for r in rows(self.path("journal.csv")) if r["action"] == "SELL"]
        self.assertEqual(len(sell), 1)
        self.assertIn("take profit: up 60%", sell[0]["reason"])
        # Half of $10 sold at 1.6x, less 3% of the $5 cost: $8.00 - $5.00 - $0.15.
        self.assertEqual(sell[0]["pnl_usd"], "2.85")
        Api.__init__(self.api, {GOOD: 0.9})                        # 44% below the peak
        self.bot().run_once(NOW + timedelta(minutes=2), lambda *a: None)
        reasons = [r["reason"] for r in rows(self.path("journal.csv")) if r["action"] == "SELL"]
        self.assertIn("trailing stop: down 44% from peak", reasons[-1])
        # Main's own settings, not a copy that could drift.
        self.assertIs(self.bot().pt, CFG["paper_trading"])
        self.assertIs(self.bot().f, CFG["filters"])


class RateLimitTests(Base):
    def test_rugcheck_only_for_market_passes_and_reused_for_10_minutes(self):
        self.bot_ = self.bot()
        self.bot_.run_once(NOW, lambda *a: None)
        first = list(self.api.rugcheck)
        self.assertTrue(first)
        self.assertNotIn("DEMOcurve", first)     # failed the market checks: never asked
        self.assertNotIn("DEMOpump", first)
        self.assertNotIn("DEMOsell", first)
        self.assertEqual(len(first), len(set(first)))
        for minute in range(1, 10):               # the next 9 minutes: from memory
            self.bot_.run_once(NOW + timedelta(minutes=minute), lambda *a: None)
        self.assertEqual(self.api.rugcheck, first)
        self.bot_.run_once(NOW + timedelta(minutes=10), lambda *a: None)
        self.assertEqual(sorted(self.api.rugcheck[len(first):]), sorted(first))

    def test_at_most_rugcheck_max_per_run(self):
        cfg = dict(CFG, main_1min=dict(CFG["main_1min"], rugcheck_max_per_run=2))
        bot = self.bot(cfg)
        lines = []
        bot.run_once(NOW, lines.append)
        self.assertEqual(len(self.api.rugcheck), 2)
        self.assertIn("waiting for RugCheck", lines[0])
        bot.run_once(NOW + timedelta(minutes=1), lines.append)
        self.assertEqual(len(self.api.rugcheck), 4)
        self.assertEqual(len(set(self.api.rugcheck)), 4)          # new ones, not the same

    def test_rugcheck_429_pauses_it_and_the_run_goes_on(self):
        self.bot().run_once(NOW, lambda *a: None)                 # GOODCAT bought
        bot = self.bot()
        Api.__init__(self.api, {GOOD: 0.6})
        self.api.rugcheck_down = RateLimited("api.rugcheck.xyz kept saying 'too many requests'")
        bot.run_once(NOW + timedelta(minutes=1), lambda *a: None)
        self.assertEqual(len(self.api.rugcheck), 1)              # stopped at the first 429
        # Exits still run that minute: -40% is main's stop loss.
        sells = [r for r in rows(self.path("journal.csv")) if r["action"] == "SELL"]
        self.assertIn("stop loss", sells[-1]["reason"])
        for minute in range(2, 6):                                 # paused 5 minutes
            bot.run_once(NOW + timedelta(minutes=minute), lambda *a: None)
        self.assertEqual(len(self.api.rugcheck), 1)
        with open(self.path("health.json")) as fh:
            self.assertIn("rugcheck_paused_until", json.load(fh))
        self.api.rugcheck_down = None
        bot.run_once(NOW + timedelta(minutes=6), lambda *a: None)
        self.assertGreater(len(self.api.rugcheck), 1)

    def test_a_rugcheck_error_fails_the_safety_checks_like_main(self):
        self.api.rugcheck_down = ApiError("api.rugcheck.xyz answered with error 500")
        self.bot().run_once(NOW, lambda *a: None)
        self.assertEqual(rows(self.path("journal.csv")), [])

    def test_dexscreener_down_skips_the_run_and_changes_nothing(self):
        self.bot().run_once(NOW, lambda *a: None)
        with open(self.path("positions.json")) as fh:
            before = fh.read()
        self.api.dex_down = True
        lines = []
        self.assertIsNone(self.bot().run_once(NOW + timedelta(minutes=1), lines.append))
        self.assertIn("skipped, nothing changed", lines[0])
        with open(self.path("positions.json")) as fh:
            self.assertEqual(fh.read(), before)
        with open(self.path("health.json")) as fh:
            health = json.load(fh)
        self.assertEqual(health["last_ok"], NOW.isoformat())
        self.assertIn("too many requests", health["last_error"])

    def test_requests_per_hour_are_recorded(self):
        bot = self.bot()
        for minute in range(3):
            bot.run_once(NOW + timedelta(minutes=minute), lambda *a: None)
        with open(self.path("health.json")) as fh:
            hour = json.load(fh)["calls_per_hour"]["2026-10-04T12:00"]
        self.assertEqual(hour["runs"], 3)
        self.assertEqual(hour["rugcheck"], len(self.api.rugcheck))
        # Each minute: profiles, boosts, the candidates' pairs, and (from the
        # second minute) the open positions' prices: well under 60 a minute.
        self.assertEqual(hour["dexscreener"], 3 + 4 + 4)


class LoopTests(unittest.TestCase):
    def test_runs_at_the_start_of_every_minute_and_survives_a_crash(self):
        calls, sleeps, clock = [], [], [1_000_000.0 + 7]

        class Bot:
            def run_once(self, now, out):
                calls.append(now)
                if len(calls) == 2:
                    raise ValueError("a bad answer")
                clock[0] += 3

        def sleep(seconds):
            sleeps.append(round(seconds, 6))
            clock[0] += seconds

        with self.assertLogs("main_1min", "ERROR"):
            m1.forever(Bot(), 60, clock=lambda: clock[0], sleep=sleep,
                       stop=lambda: len(calls) >= 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [10, 60])           # to the next minute after each run
        self.assertTrue(all(t.second == 0 for t in calls[1:]))       # on the minute

    def test_test_mode_saves_nothing(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(m1, "PublicApi", lambda *a: DemoApi()), \
                mock.patch.object(m1, "JupiterOrganic", lambda: None), \
                mock.patch.object(m1, "HERE", d), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(m1.main(["--test"]), 0)
            self.assertEqual(os.listdir(d), [])
        self.assertIn("nothing is saved", out.getvalue())


class SafetyTests(unittest.TestCase):
    def test_only_the_read_only_lookups(self):
        api = m1.CountingApi(DemoApi())
        self.assertEqual({k for k in vars(m1.CountingApi) if not k.startswith("_")},
                         {"latest_profiles", "latest_boosts", "pairs_for_tokens",
                          "rugcheck_report"})
        with open(m1.__file__) as fh:
            source = fh.read().lower()
        for word in ("private_key", "keypair", "sign_transaction", "sendtransaction"):
            self.assertNotIn(word, source)
        self.assertEqual(api.calls, {"dexscreener": 0, "rugcheck": 0})


class CompareTests(unittest.TestCase):
    def test_shown_next_to_main(self):
        with tempfile.TemporaryDirectory() as d:
            m1.MainOneMinute(CFG, d, DemoApi()).run_once(NOW, lambda *a: None)
            cfg = dict(CFG, files={"data_folder": d})
            with mock.patch.object(compare, "load_config", lambda: cfg), \
                    mock.patch.dict(os.environ, {"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""}), \
                    mock.patch("sys.argv", ["compare.py", "--date", "2026-10-04"]), \
                    mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(compare.main(), 0)
        text = out.getvalue()
        header = next(line for line in text.splitlines() if line.startswith("| | main"))
        self.assertTrue(header.startswith("| | main | main (1 min) | early"), header)
        self.assertIn("| main (1 min): server |", text)


if __name__ == "__main__":
    unittest.main()
