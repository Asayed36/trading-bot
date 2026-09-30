"""Checks for the 5-minute schedule: the schedule change record, the
convergence strategy keeping Helius at every 15 minutes, and the
before/after split in the daily comparison. Run with:  python -m unittest -v
"""

import csv
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import HERE, load_config, record_schedule, run  # noqa: E402
from screener.compare import schedule_lines, schedule_split, strategy_stats  # noqa: E402
from screener.convergence import ConvergenceStrategy  # noqa: E402
from screener.demo import EARLY_GOOD, DemoApi, demo_rpc_factory  # noqa: E402
from screener.paper_trader import now_utc  # noqa: E402

CFG = load_config()
QUIET = dict(out=lambda *a: None)


def read_json(path):
    with open(path) as fh:
        return json.load(fh)


class ScheduleRecordTests(unittest.TestCase):
    def test_records_each_change_once(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "schedule.json")
            t0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
            record_schedule(d, 15, t0, **QUIET)
            record_schedule(d, 15, t0 + timedelta(hours=1), **QUIET)   # same: nothing added
            record_schedule(d, 5, t0 + timedelta(hours=2), **QUIET)    # changed: added once
            record_schedule(d, 5, t0 + timedelta(hours=3), **QUIET)
            history = read_json(path)["history"]
            self.assertEqual([h["every_minutes"] for h in history], [15, 5])
            self.assertEqual(history[1]["since"], "2026-10-01T11:00:00+00:00")

    def test_run_records_the_change(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "schedule.json"), "w") as fh:
                json.dump({"history": [{"every_minutes": 15,
                                        "since": "2026-09-30T01:50:37+00:00"}]}, fh)
            lines = []
            run(DemoApi(), CFG, d, out=lines.append)
            history = read_json(os.path.join(d, "schedule.json"))["history"]
            self.assertEqual([h["every_minutes"] for h in history], [15, 5])
            self.assertTrue(any("Schedule change recorded: every 5 minutes" in line
                                for line in lines))

    def test_cron_matches_config(self):
        with open(os.path.join(HERE, ".github", "workflows", "screener.yml")) as fh:
            cron = re.search(r'cron: "\*/(\d+) \* \* \* \*"', fh.read())
        self.assertEqual(int(cron.group(1)), CFG["schedule"]["run_every_minutes"])

    def test_repository_history_is_seeded(self):
        history = read_json(os.path.join(HERE, "data", "schedule.json"))["history"]
        self.assertEqual(history[0]["every_minutes"], 120)
        self.assertEqual(history[1], {"every_minutes": 15,
                                      "since": "2026-09-30T01:50:37+00:00"})


class HeliusPaceTests(unittest.TestCase):
    """The workflow runs every 5 minutes; Helius is still read every 15."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t0 = now_utc()
        self.live = {}

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, minutes, api=None):
        strategy = ConvergenceStrategy(CFG, self.tmp.name,
                                       rpc_factory=demo_rpc_factory(live=self.live))
        plan = strategy.fetch(api or DemoApi(), now=self.t0 + timedelta(minutes=minutes))
        strategy.apply(plan, **QUIET)
        return strategy.trader.state

    def test_helius_only_every_15_minutes(self):
        used = []
        for minutes in range(0, 65, 5):              # 13 runs, 5 minutes apart
            used.append(self.go(minutes)["helius"]["used"])
        checks = [m for m, (a, b) in zip(range(5, 65, 5), zip(used, used[1:])) if b > a]
        self.assertEqual(checks, [15, 30, 45, 60])   # plus the first run at 0

    def test_github_jitter_is_tolerated(self):
        self.go(0)
        state = self.go(13.5)                        # a 15-minute run that started early
        self.assertEqual(state["last_helius_check"][11:16],
                         (self.t0 + timedelta(minutes=13.5)).isoformat()[11:16])
        state = self.go(20)                          # too soon after 13.5
        self.assertEqual(state["last_helius_check"][11:16],
                         (self.t0 + timedelta(minutes=13.5)).isoformat()[11:16])

    def test_positions_still_checked_between_helius_checks(self):
        self.go(0)                                   # builds the tracked list
        self.go(15)                                  # first look at each wallet
        for wallet, ago in (("whale", 9), ("h0", 6), ("h1", 3)):
            when = self.t0 + timedelta(minutes=30 - ago)
            self.live.setdefault(wallet, []).append(
                {"mint": EARLY_GOOD, "side": "buy", "sol": 0.5, "tokens": 100.0,
                 "time": int(when.timestamp())})
        state = self.go(30)                          # Helius check: 3 wallets bought
        self.assertEqual(len(state["open_positions"]), 1)
        used = state["helius"]["used"]
        state = self.go(35, api=DemoApi({EARLY_GOOD: 0.5}))  # no Helius check this run...
        self.assertEqual(state["helius"]["used"], used)
        self.assertEqual(state["open_positions"], [])       # ...but the -50% stop still fired


class BeforeAfterTests(unittest.TestCase):
    def test_split_by_entry_time(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "journal.csv"), "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["time_utc", "action", "symbol", "token_address", "reason",
                            "price_usd", "usd_amount", "pnl_usd", "pnl_pct",
                            "running_total_pnl_usd"])
                w.writerows([
                    ["2026-10-01 09:00:00", "BUY", "A", "a", "", "1", "10", "0", "0", "0"],
                    ["2026-10-01 11:30:00", "SELL", "A", "a", "", "2", "19", "9.00", "0", "0"],
                    ["2026-10-01 10:30:00", "BUY", "B", "b", "", "1", "10", "0", "0", "0"],
                    ["2026-10-01 10:45:00", "SELL", "B", "b", "", "1", "6", "-4.00", "0", "0"],
                ])
            with open(os.path.join(d, "positions.json"), "w") as fh:
                json.dump({"open_positions": [
                    {"address": "c", "entry_time": "2026-10-01T10:40:00+00:00",
                     "remaining_fraction": 1.0, "tokens": 10, "last_price": 1.1,
                     "cost_usd": 10}]}, fh)
            with open(os.path.join(d, "schedule.json"), "w") as fh:
                json.dump({"history": [
                    {"every_minutes": 15, "since": "2026-09-30T01:50:37+00:00"},
                    {"every_minutes": 5, "since": "2026-10-01T10:00:00+00:00"}]}, fh)

            when, before, after = schedule_split(os.path.join(d, "schedule.json"))
            self.assertEqual((before, after), (15, 5))
            # A was bought before the change (sold after it): counts as "before"
            b = strategy_stats(d, 3, "", entered=(None, when))
            a = strategy_stats(d, 3, "", entered=(when, None))
            self.assertEqual((b["closed"], b["wins"], b["realized"], b["open"]), (1, 1, 9.0, 0))
            self.assertEqual((a["closed"], a["wins"], a["realized"], a["open"]), (1, 0, -4.0, 1))
            self.assertAlmostEqual(a["unrealized"], 11 - 10 - 0.3)
            text = "\n".join(schedule_lines([("main", d, 3)], os.path.join(d, "schedule.json")))
            self.assertIn("every 15 min until 2026-10-01 10:00 UTC, every 5 min since", text)
            self.assertIn("| Win rate | 100% (1 of 1) | 0% (0 of 1) |", text)

    def test_no_change_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("no change recorded yet",
                          schedule_lines([("main", d, 3)], os.path.join(d, "schedule.json"))[0])


if __name__ == "__main__":
    unittest.main()
