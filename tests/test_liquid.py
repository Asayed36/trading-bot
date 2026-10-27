"""Checks for the "liquid" paper strategy (screener/liquid.py, run inside main_1min.py), with
the made-up data of screener/demo.py. Paper trading only: nothing here touches a wallet."""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

import main_1min as m1  # noqa: E402
from run import load_config  # noqa: E402
from screener.demo import GOOD, DemoApi  # noqa: E402
from screener.liquid import LiquidVersion, entry_problem  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = running(load_config())
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
VERSIONS = ("l1", "l2", "l3", "l4")


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def result(price=1.0, liquidity=60_000, address="TOKEN"):
    pair = {"pairAddress": f"POOL-{address}", "priceUsd": str(price) if price else None}
    if liquidity is not None:
        pair["liquidity"] = {"usd": liquidity}
    return SimpleNamespace(address=address, symbol=address[:5], pair=pair, price=price,
                           insider=None, record=None)


def version(name, d):
    section = CFG["liquid"]
    v = next(v for v in section["versions"] if v["name"] == name)
    return LiquidVersion(section, v, d, CFG["paper_trading"]["buy_amount_usd"])


def trader(name, d):
    v = version(name, d)
    t = m1.LiquidSafeTrader(v.cfg, v.folder)
    return t


def buy_at(t, price=1.0, when=NOW):
    return t.buy(result(price), when=when, fetched_at=when)


class ConfigTests(unittest.TestCase):
    def test_the_numbers_asked_for(self):
        lc = CFG["liquid"]
        self.assertEqual((lc["min_liquidity_usd"], lc["buy_slippage_pct"],
                          lc["round_trip_cost_pct"]), (50_000, 1.5, 3))
        v = {x["name"]: x for x in lc["versions"]}
        self.assertEqual(list(v), list(VERSIONS))
        self.assertEqual(
            {k: v["l1"].get(k) for k in ("take_profit_pct", "take_profit_sell_fraction",
                                         "trailing_stop_pct", "stop_loss_pct",
                                         "max_hold_minutes")},
            {"take_profit_pct": 50, "take_profit_sell_fraction": 0.5, "trailing_stop_pct": 15,
             "stop_loss_pct": None, "max_hold_minutes": 30})
        self.assertEqual((v["l2"]["take_profit_pct"], v["l2"]["trailing_stop_pct"],
                          v["l2"]["max_hold_minutes"], v["l2"].get("stop_loss_pct")),
                         (100, 20, 60, None))
        self.assertEqual((v["l3"]["take_profit_pct"], v["l3"]["trailing_stop_pct"],
                          v["l3"]["stop_loss_pct"], v["l3"]["max_hold_minutes"]),
                         (50, 15, 25, 30))
        self.assertEqual({k: v["l4"].get(k) for k in ("take_profit_pct", "trailing_stop_pct",
                                                      "stop_loss_pct", "max_hold_minutes")},
                         {"take_profit_pct": None, "trailing_stop_pct": None,
                          "stop_loss_pct": None, "max_hold_minutes": 60})
        for name in VERSIONS:
            self.assertEqual(v[name]["folder"], f"main-1min/liquid/{name}")

    def test_a_version_needs_a_time_exit(self):
        with self.assertRaises(ValueError):
            LiquidVersion(CFG["liquid"], {"name": "x", "folder": "x"}, "/tmp", 10)


class EntryRuleTests(unittest.TestCase):
    def test_liquidity_threshold(self):
        self.assertIsNone(entry_problem(result(liquidity=50_000), NOW, 50_000))
        self.assertIsNone(entry_problem(result(liquidity=1_000_000), NOW, 50_000))
        self.assertIn("below", entry_problem(result(liquidity=49_999.99), NOW, 50_000))

    def test_no_price_or_no_liquidity_is_skipped(self):
        self.assertEqual(entry_problem(result(price=None), NOW, 50_000), "no price")
        self.assertEqual(entry_problem(result(price=0), NOW, 50_000), "no price")
        self.assertEqual(entry_problem(result(liquidity=None), NOW, 50_000),
                         "no liquidity value")


class ExitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, t, price, minutes):
        return t.update({"TOKEN": price}, when=NOW + timedelta(minutes=minutes),
                        fetched_at=NOW + timedelta(minutes=minutes))

    def test_buy_pays_slippage_and_the_buy_amount(self):
        t = trader("l1", self.d)
        pos = buy_at(t, 2.0)
        self.assertAlmostEqual(pos["entry_price"], 2.0 * 1.015)
        self.assertEqual(pos["cost_usd"], 10)
        self.assertIsNone(buy_at(t, 2.0))                      # never twice
        j = rows(os.path.join(t.state_path.replace("positions.json", ""), "journal.csv"))
        self.assertEqual(j[0]["usd_amount"], "10.00")
        self.assertIn("first check with enough liquidity", j[0]["reason"])
        self.assertIn("paid +1.5%", j[0]["reason"])

    def test_l1_sells_half_at_plus_50_then_trails_15_from_the_peak(self):
        t = trader("l1", self.d)
        buy_at(t, 1.0)                                        # entry 1.015
        self.assertEqual(self.go(t, 1.5, 1), [])              # +47.8%: not yet
        (sale,) = self.go(t, 1.6, 2)                          # +57.6%
        self.assertIn("take profit", sale["reason"])
        self.assertFalse(sale["closed"])
        self.assertEqual(self.go(t, 1.9, 3), [])              # a new peak, still holding
        self.assertEqual(self.go(t, 1.64, 4), [])             # 13.7% below the 1.9 peak
        (last,) = self.go(t, 1.6, 5)                          # 15.8% below the peak
        self.assertIn("trailing stop", last["reason"])
        self.assertTrue(last["closed"])
        self.assertEqual(t.open_positions, [])

    def test_trailing_does_not_apply_before_the_half_is_sold(self):
        t = trader("l1", self.d)
        buy_at(t, 1.0)
        self.go(t, 1.4, 1)                                    # +38%, below the +50% sale
        self.assertEqual(self.go(t, 0.9, 2), [])              # 36% below its peak: no rule
        self.assertEqual(len(t.open_positions), 1)

    def test_l1_sells_everything_30_minutes_after_the_buy(self):
        t = trader("l1", self.d)
        buy_at(t, 1.0)
        self.assertEqual(self.go(t, 1.0, 29), [])
        (sale,) = self.go(t, 1.0, 30)
        self.assertIn("time exit", sale["reason"])
        self.assertTrue(sale["closed"])

    def test_l1_has_no_stop_loss_but_l3_stops_at_minus_25(self):
        l1, l3 = trader("l1", self.d), trader("l3", self.d)
        buy_at(l1)
        buy_at(l3)
        self.assertEqual(self.go(l1, 0.5, 5), [])             # -51%: l1 just holds
        self.assertEqual(self.go(l3, 0.8, 5), [])             # -21%: not yet
        (sale,) = self.go(l3, 0.7, 6)                         # -31%
        self.assertIn("stop loss", sale["reason"])
        self.assertTrue(sale["closed"])

    def test_l2_waits_for_plus_100_then_trails_20_and_stops_after_60_minutes(self):
        t = trader("l2", self.d)
        buy_at(t)
        self.assertEqual(self.go(t, 1.8, 5), [])              # +77%: no sale in l2
        (sale,) = self.go(t, 2.1, 6)                          # +107%
        self.assertIn("take profit", sale["reason"])
        self.assertEqual(self.go(t, 1.8, 7), [])              # 14% below 2.1
        (last,) = self.go(t, 1.6, 8)                          # 24% below 2.1
        self.assertIn("trailing stop", last["reason"])
        t2 = trader("l2", os.path.join(self.d, "other"))
        buy_at(t2)
        self.assertEqual(self.go(t2, 1.0, 59), [])
        (sale,) = self.go(t2, 1.0, 60)
        self.assertIn("time exit", sale["reason"])

    def test_l4_has_no_rules_but_the_hour(self):
        t = trader("l4", self.d)
        buy_at(t)
        for minutes, price in ((5, 3.0), (10, 0.2), (59, 1.0)):
            self.assertEqual(self.go(t, price, minutes), [])
        (sale,) = self.go(t, 1.0, 60)
        self.assertIn("time exit", sale["reason"])
        self.assertTrue(sale["closed"])

    def test_costs_are_three_percent_round_trip_plus_the_slippage(self):
        t = trader("l4", self.d)
        buy_at(t, 1.0)
        (sale,) = self.go(t, 1.0, 60)                         # sold at the market price
        self.assertAlmostEqual(sale["pnl_usd"], 10 * (1 / 1.015 - 1) - 0.30, places=9)

    def test_a_half_sale_pays_its_share_of_the_costs(self):
        t = trader("l1", self.d)
        buy_at(t, 1.0)
        (sale,) = self.go(t, 1.6, 1)
        self.assertAlmostEqual(sale["pnl_usd"], 5 * (1.6 / 1.015 - 1) - 0.15, places=9)

    def test_no_price_no_exit(self):
        t = trader("l4", self.d)
        buy_at(t)
        self.assertEqual(t.update({}, when=NOW + timedelta(minutes=90)), [])
        self.assertEqual(len(t.open_positions), 1)


class Api(DemoApi):
    pass


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def bot(self, cfg=CFG, api=None):
        return m1.MainOneMinute(cfg, self.d, api or DemoApi())

    def folder(self, name):
        return os.path.join(self.d, "main-1min", "liquid", name)

    def test_first_check_buys_every_liquid_token_in_every_version(self):
        lines = []
        self.bot().run_once(NOW, lines.append)
        candidates = rows(os.path.join(self.d, "main-1min", "candidates.csv"))
        liquid = {r["token_address"] for r in candidates
                  if r["liquidity_usd"] and float(r["liquidity_usd"]) >= 50_000
                  and r["price_usd"]}
        self.assertIn(GOOD, liquid)
        self.assertNotIn("DEMOcurve", liquid)                    # 10,000 of liquidity
        for name in VERSIONS:
            bought = {r["token_address"] for r in rows(os.path.join(self.folder(name),
                                                                    "journal.csv"))}
            self.assertEqual(bought, liquid, name)
            entry = rows(os.path.join(self.folder(name), "entries.csv"))[0]
            self.assertAlmostEqual(float(entry["fill_price_usd"]),
                                   float(entry["price_usd"]) * 1.015, places=9)
            self.assertEqual(entry["buy_slippage_pct"], "1.5")
        self.assertIn("[l1] BUY  GOODCAT $10", "\n".join(lines))

    def test_a_token_is_bought_once_only(self):
        bot = self.bot()
        bot.run_once(NOW, lambda *a: None)
        before = {n: len(rows(os.path.join(self.folder(n), "journal.csv"))) for n in VERSIONS}
        bot.run_once(NOW + timedelta(minutes=1), lambda *a: None)
        self.bot().run_once(NOW + timedelta(minutes=2), lambda *a: None)   # after a restart
        after = {n: len(rows(os.path.join(self.folder(n), "journal.csv"))) for n in VERSIONS}
        self.assertEqual(before, after)

    def test_a_token_already_in_candidates_csv_is_not_a_first_check(self):
        first = self.bot()
        first.run_once(NOW, lambda *a: None)
        for n in VERSIONS:                                     # forget the liquid buys only
            for name in ("journal.csv", "entries.csv", "positions.json"):
                os.remove(os.path.join(self.folder(n), name))
        self.bot().run_once(NOW + timedelta(minutes=1), lambda *a: None)
        for n in VERSIONS:
            self.assertEqual(rows(os.path.join(self.folder(n), "journal.csv")), [], n)

    def test_exits_run_every_minute_on_main_1mins_prices(self):
        self.bot().run_once(NOW, lambda *a: None)
        # +60% (a little less after the 1.5% slippage): l1 and l3 sell half, l2 and l4 hold.
        later = self.bot(api=DemoApi({GOOD: 1.6}))
        later.run_once(NOW + timedelta(minutes=1), lambda *a: None)
        sold = {n: [r for r in rows(os.path.join(self.folder(n), "journal.csv"))
                    if r["action"] == "SELL" and r["token_address"] == GOOD] for n in VERSIONS}
        self.assertEqual({n: len(s) for n, s in sold.items()},
                         {"l1": 1, "l2": 0, "l3": 1, "l4": 0})
        self.assertIn("take profit", sold["l1"][0]["reason"])
        # 31 minutes after the buys: l1 and l3 sell the rest, l2 and l4 keep waiting.
        later.run_once(NOW + timedelta(minutes=31), lambda *a: None)
        left = {n: json.load(open(os.path.join(self.folder(n), "positions.json")))
                ["open_positions"] for n in VERSIONS}
        self.assertEqual(left["l1"], [])
        self.assertEqual(left["l3"], [])
        self.assertTrue(left["l2"] and left["l4"])
        later.run_once(NOW + timedelta(minutes=61), lambda *a: None)
        for n in VERSIONS:
            self.assertEqual(json.load(open(os.path.join(self.folder(n), "positions.json")))
                             ["open_positions"], [], n)

    def test_stopped_version_buys_nothing(self):
        import copy
        cfg = copy.deepcopy(CFG)
        cfg["liquid"]["versions"][3]["stopped"] = True
        self.bot(cfg).run_once(NOW, lambda *a: None)
        self.assertEqual(rows(os.path.join(self.folder("l4"), "journal.csv")), [])
        self.assertTrue(rows(os.path.join(self.folder("l1"), "journal.csv")))

    def test_turned_off_changes_nothing(self):
        import copy
        cfg = copy.deepcopy(CFG)
        cfg["liquid"]["enabled"] = False
        self.bot(cfg).run_once(NOW, lambda *a: None)
        self.assertFalse(os.path.exists(os.path.join(self.d, "main-1min", "liquid")))

    def test_no_jupiter_lookup_for_its_buys(self):
        asked = []
        bot = m1.MainOneMinute(CFG, self.d, DemoApi(), lambda a: asked.append(a) or {})
        bot.run_once(NOW, lambda *a: None)
        # (main (1 min) B/C are the only ones that ask Jupiter: liquid never does)
        entry = rows(os.path.join(self.folder("l1"), "entries.csv"))[0]
        self.assertEqual(entry["jupiter_organic_score"], "")

    def test_health_json_lists_the_versions(self):
        self.bot().run_once(NOW, lambda *a: None)
        with open(os.path.join(self.d, "main-1min", "health.json")) as fh:
            data = json.load(fh)
        for n in VERSIONS:
            self.assertGreater(data["versions"][n]["open"], 0)
        hour = next(iter(data["calls_per_hour"].values()))
        self.assertGreater(hour["l1 buys"], 0)


class HealthRowTests(unittest.TestCase):
    def test_a_row_per_version(self):
        from screener.health import health_lines
        with tempfile.TemporaryDirectory() as d:
            m1.MainOneMinute(CFG, d, DemoApi()).run_once(NOW, lambda *a: None)
            now = NOW + timedelta(minutes=2)
            text = "\n".join(health_lines(d, CFG, now))
        for n in VERSIONS:
            line = next(x for x in text.splitlines()
                        if x.startswith(f"| main (1 min) liquid {n}: server"))
            self.assertIn("open; last 24 h:", line)
            self.assertIn("liquidity is at least $50,000", line)

    def test_stopped_version_is_information(self):
        import copy
        from screener.health import health_lines
        cfg = copy.deepcopy(CFG)
        cfg["liquid"]["versions"][0]["stopped"] = True
        with tempfile.TemporaryDirectory() as d:
            text = "\n".join(health_lines(d, cfg, NOW))
        line = next(x for x in text.splitlines() if x.startswith("| main (1 min) liquid l1: server"))
        self.assertIn("stopped (no new buys)", line)


class FilesTests(unittest.TestCase):
    def test_the_four_folders_are_pushed_and_allowed(self):
        for n in VERSIONS:
            for name in ("journal.csv", "positions.json", "entries.csv"):
                path = f"data/main-1min/liquid/{n}/{name}"
                self.assertNotEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                                   cwd=HERE).returncode, 0, path)
            self.assertEqual(subprocess.run(
                ["git", "check-ignore", "-q", f"data/main-1min/liquid/{n}/positions.json.tmp"],
                cwd=HERE).returncode, 0)
        with open(os.path.join(HERE, "deploy", "push_results.sh")) as fh:
            self.assertIn("data/main-1min ", fh.read())       # the whole folder is pushed

    def test_the_bot_restarts_when_the_liquid_section_changes(self):
        self.assertIn("liquid", m1.CONFIG_SECTIONS)

    def test_no_wallet_words_in_the_module(self):
        with open(os.path.join(HERE, "screener", "liquid.py")) as fh:
            source = fh.read().lower()
        for word in ("private_key", "keypair", "sign_transaction", "sendtransaction"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
