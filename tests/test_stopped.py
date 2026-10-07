"""Checks for stopped strategies (stopped = true in config.toml): no new
buys, open positions still finish under their normal exits, the files are
kept, and the comparison and health check say "stopped".
Run with:  python -m unittest -v
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

import compare  # noqa: E402
from run import load_config, run  # noqa: E402
from screener.demo import GOOD, DemoApi  # noqa: E402
from screener.health import INFO, health_lines  # noqa: E402
from screener.launch import LaunchEngine  # noqa: E402
from screener.momentum import MomentumEngine  # noqa: E402
from screener.paper_trader import PaperTrader  # noqa: E402

REAL = load_config()              # as it is now: the stopped strategies stopped
QUIET = dict(out=lambda *a: None)


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class ConfigTests(unittest.TestCase):
    def test_what_is_stopped_and_what_runs(self):
        self.assertTrue(REAL["main"]["stopped"])
        self.assertTrue(REAL["early"]["stopped"])
        self.assertTrue(REAL["launch"]["stopped"])
        momentum = {v["name"]: bool(v.get("stopped")) for v in REAL["momentum"]["variants"]}
        self.assertEqual(momentum, {"30pct-2min": True, "50pct-3min": True,
                                    "100pct-5min": True})
        # 2026-10-07: robinhood, main (1 min)'s own buying and version A
        # stopped too; B and the new C keep running inside main (1 min).
        self.assertTrue(REAL["robinhood"]["stopped"])
        self.assertTrue(REAL["main_1min"]["stopped"])
        versions = {v["name"]: bool(v.get("stopped")) for v in REAL["main_1min"]["versions"]}
        self.assertEqual(versions, {"A": True, "B": False, "C": False})
        for name in ("main_1min", "convergence", "news", "news_listings", "robinhood"):
            self.assertTrue(REAL[name]["enabled"], name)
        for name in ("convergence", "news", "news_listings"):
            self.assertFalse(REAL[name].get("stopped"), name)


class MainAndEarlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def test_main_screens_nothing_but_still_sells(self):
        run(DemoApi(), running(REAL), self.d, **QUIET)           # bought while running
        held = json.load(open(os.path.join(self.d, "positions.json")))["open_positions"]
        self.assertTrue(held)
        before = rows(os.path.join(self.d, "journal.csv"))
        lines = []
        with mock.patch("run.screen") as screen:
            run(DemoApi({GOOD: 0.5}), REAL, self.d, out=lines.append)   # -50%: the -30% stop
        screen.assert_not_called()                               # no screening at all
        after = rows(os.path.join(self.d, "journal.csv"))
        self.assertEqual(after[:len(before)], before)            # the journal is kept
        new = after[len(before):]
        self.assertTrue(new and all(r["action"] == "SELL" for r in new))
        self.assertIn("GOODCAT", [r["symbol"] for r in new])
        self.assertTrue(any("main strategy is stopped" in line for line in lines))

    def test_main_never_buys_when_stopped(self):
        run(DemoApi(), REAL, self.d, **QUIET)
        self.assertEqual(rows(os.path.join(self.d, "journal.csv")), [])

    def test_early_only_runs_while_it_holds_a_position(self):
        lines = []
        run(DemoApi(), REAL, self.d, out=lines.append)
        self.assertFalse(any("STEP 5" in line for line in lines))     # nothing held: not run
        self.assertEqual(rows(os.path.join(self.d, "early", "journal.csv")), [])

    def test_a_stopped_trader_still_sells(self):
        t = PaperTrader(REAL["paper_trading"], self.d)
        from types import SimpleNamespace
        r = SimpleNamespace(address="X", symbol="X", name="X", price=1.0, pair={}, insider=None)
        t.organic = None
        self.assertTrue(t.buy(r))
        t.buying = False
        self.assertFalse(t.can_buy("Y"))
        (sale,) = t.update({"X": 0.5})
        self.assertTrue(sale["closed"])


class ServerStrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_launch_speeds_make_no_new_buys(self):
        engine = LaunchEngine(REAL, self.tmp.name, clock=lambda: 0.0)
        self.assertEqual({n: t.buying for n, t in engine.traders.items()},
                         {"5s": False, "30s": False, "90s": False})
        engine = LaunchEngine(running(REAL), self.tmp.name, clock=lambda: 0.0)
        self.assertTrue(all(t.buying for t in engine.traders.values()))

    def stuck(self, minutes_ago):
        """The real stuck position (ATISWATER, 2026-10-05): bought at the
        creation price, never listed on DexScreener, so never priced again."""
        from datetime import datetime, timedelta, timezone
        entry = datetime(2026, 10, 5, 9, 13, 54, tzinfo=timezone.utc)
        for speed in ("5s", "30s", "90s"):
            folder = os.path.join(self.tmp.name, "launch", speed)
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "positions.json"), "w") as fh:
                json.dump({"open_positions": [{
                    "address": "2esPLfhEwwNRHkE9vFazVGyPRH21LU4dzgztVhzBeRMP",
                    "symbol": "ATISWATER", "pair_address": None, "entry_time": entry.isoformat(),
                    "entry_price": 3.379403541472507e-06, "peak_price": 3.379403541472507e-06,
                    "tokens": 1378164.7982681117, "cost_usd": 5.36261, "remaining_fraction": 1.0,
                    "took_profit": False, "last_price": 3.372413793103448e-06,
                    "sol_usd_at_entry": 120.87}],
                    "ever_bought": ["2esPLfhEwwNRHkE9vFazVGyPRH21LU4dzgztVhzBeRMP"],
                    "running_total_pnl_usd": -100.0}, fh)
        return (entry + timedelta(minutes=minutes_ago)).timestamp()

    def test_stuck_positions_close_at_the_last_known_price(self):
        t = self.stuck(110)
        engine = LaunchEngine(REAL, self.tmp.name, clock=lambda: t)
        self.assertEqual(len(engine.closed_stopped), 3)          # one per speed
        for speed, trader in engine.traders.items():
            self.assertEqual(trader.open_positions, [], speed)
            (row,) = rows(os.path.join(self.tmp.name, "launch", speed, "journal.csv"))
            self.assertEqual((row["action"], row["symbol"]), ("SELL", "ATISWATER"))
            self.assertEqual(row["reason"], "closed after the bot was stopped: at the last "
                                            "known price (-0%), no price after 110 min")
            self.assertAlmostEqual(float(row["price_usd"]), 3.3724137931e-06)
            # the normal costs: fees, slippage and the priority fee
            self.assertLess(float(row["pnl_usd"]), -1)
            saved = json.load(open(os.path.join(self.tmp.name, "launch", speed,
                                                "positions.json")))
            self.assertEqual(saved["open_positions"], [])
            self.assertAlmostEqual(saved["running_total_pnl_usd"], -100 + float(row["pnl_usd"]),
                                   places=1)

    def test_not_before_the_time_stop_and_grace_nor_when_running(self):
        t = self.stuck(35)
        engine = LaunchEngine(REAL, self.tmp.name, clock=lambda: t)
        self.assertEqual(engine.closed_stopped, [])               # 30 min + 10 min grace
        t = self.stuck(500)
        engine = LaunchEngine(running(REAL), self.tmp.name, clock=lambda: t)
        self.assertEqual(engine.closed_stopped, [])               # running: normal exits only
        self.assertEqual(engine.close_stopped(t), [])

    def test_a_priced_position_keeps_its_normal_exits(self):
        t = self.stuck(20)
        engine = LaunchEngine(REAL, self.tmp.name, clock=lambda: t)
        mint = "2esPLfhEwwNRHkE9vFazVGyPRH21LU4dzgztVhzBeRMP"
        engine.set_sol_price(120.87)
        engine.set_external_prices({mint: 3.5e-06}, t)
        engine.migrated.add(mint)
        engine.tick(t + 30 * 60)                                  # its time stop, priced
        (row,) = rows(os.path.join(self.tmp.name, "launch", "5s", "journal.csv"))
        self.assertTrue(row["reason"].startswith("time stop: 50 min"), row["reason"])

    def test_close_stuck_command(self):
        import launch_bot
        self.stuck(0)
        lines = []
        self.assertEqual(launch_bot.close_stuck(REAL, self.tmp.name, out=lines.append), 0)
        self.assertEqual(len([x for x in lines if "SELL ATISWATER closed after the bot was "
                              "stopped" in x]), 3)
        self.assertIn("Closed 3 stuck position(s); 0 still open.", lines[-1])
        self.assertEqual(launch_bot.close_stuck(running(REAL), self.tmp.name,
                                                out=lines.append), 1)

    def test_no_momentum_variant_buys(self):
        engine = MomentumEngine(REAL, self.tmp.name, clock=lambda: 0.0)
        self.assertEqual({n: t.buying for n, t in engine.traders.items()},
                         {"30pct-2min": False, "50pct-3min": False, "100pct-5min": False})


class ReportTests(unittest.TestCase):
    def test_comparison_columns_say_stopped(self):
        names = ["main", "main (1 min)", "main (1 min) A", "main (1 min) B", "main (1 min) C",
                 "early", "launch 5s", "momentum 30pct-2min", "momentum 100pct-5min",
                 "robinhood", "convergence", "news"]
        self.assertEqual([n for n in names if compare.stopped(REAL, n)],
                         ["main", "main (1 min)", "main (1 min) A", "early", "launch 5s",
                          "momentum 30pct-2min", "momentum 100pct-5min", "robinhood"])

    def test_health_says_stopped_with_open_positions(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "early"))
            with open(os.path.join(d, "early", "positions.json"), "w") as fh:
                json.dump({"open_positions": [{"address": "X"}]}, fh)
            from datetime import datetime, timezone
            text = "\n".join(health_lines(d, REAL, datetime(2026, 10, 5, tzinfo=timezone.utc)))
        rows_ = {line.split(" | ")[0][2:]: line for line in text.splitlines()
                 if line.startswith("| ")}
        self.assertIn(f"{INFO} stopped (no new buys); 1 open position(s) finishing",
                      rows_["early: last successful run"])
        self.assertIn(f"{INFO} stopped (no new buys); 0 open position(s): finished",
                      rows_["main: last successful run"])
        self.assertIn("Part K", rows_["launch: server push"])


if __name__ == "__main__":
    unittest.main()
