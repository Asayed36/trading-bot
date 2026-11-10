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
from screener.liquid import (LiquidVersion, count_entry, entry_filter_problems,  # noqa: E402
                             entry_problem)  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = running(load_config())
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
VERSIONS = ("l1", "l2", "l3", "l4")
NEW = ("l5", "l6")                    # added later; l1-l4 are unchanged by them


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
        self.assertEqual(list(v)[:4], list(VERSIONS))
        self.assertEqual(list(v)[4:], list(NEW))
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


# ---------------------------------------------------------------------
# l5 ("filtered l3") and l6 ("l4 with a stop loss"), added 2026-11-10
# ---------------------------------------------------------------------

def pair(age_minutes=60, change_5m=5.0, mcap=500_000, liquidity=60_000, now=NOW, fdv=None):
    created = now - timedelta(minutes=age_minutes) if age_minutes is not None else None
    p = {"pairAddress": "POOL", "priceUsd": "1.0", "liquidity": {"usd": liquidity},
         "priceChange": {"m5": change_5m}, "marketCap": mcap, "fdv": fdv}
    if created is not None:
        p["pairCreatedAt"] = created.timestamp() * 1000
    return p


def with_pair(**kw):
    return SimpleNamespace(address="TOKEN", symbol="TOKEN", price=1.0, pair=pair(**kw),
                           insider=None, record=None)


L5 = {"min_pool_age_minutes": 30.0, "max_price_change_5m_pct": 10.0, "min_market_cap_usd": 250000.0}


class NewVersionConfigTests(unittest.TestCase):
    def versions(self):
        return {v["name"]: v for v in CFG["liquid"]["versions"]}

    def test_l5_is_l3_plus_the_entry_filter(self):
        v = self.versions()
        exits = ("take_profit_pct", "take_profit_sell_fraction", "trailing_stop_pct",
                 "stop_loss_pct", "max_hold_minutes")
        self.assertEqual({k: v["l5"][k] for k in exits}, {k: v["l3"][k] for k in exits})
        self.assertEqual({k: v["l5"][k] for k in exits},
                         {"take_profit_pct": 50, "take_profit_sell_fraction": 0.5,
                          "trailing_stop_pct": 15, "stop_loss_pct": 25, "max_hold_minutes": 30})
        self.assertEqual((v["l5"]["min_pool_age_minutes"], v["l5"]["max_price_change_5m_pct"],
                          v["l5"]["min_market_cap_usd"]), (30, 10, 250000))
        self.assertEqual(v["l5"]["folder"], "main-1min/liquid/l5")
        self.assertTrue(v["l5"]["track_start"])

    def test_l6_is_l4_plus_a_stop_loss_and_has_no_entry_filter(self):
        v = self.versions()
        self.assertEqual({k: v["l6"].get(k) for k in ("take_profit_pct", "trailing_stop_pct",
                                                       "stop_loss_pct", "max_hold_minutes")},
                         {"take_profit_pct": None, "trailing_stop_pct": None,
                          "stop_loss_pct": 25, "max_hold_minutes": 60})
        for key in ("min_pool_age_minutes", "max_price_change_5m_pct", "min_market_cap_usd"):
            self.assertNotIn(key, v["l6"])
        self.assertEqual(v["l6"]["folder"], "main-1min/liquid/l6")
        self.assertTrue(v["l6"]["track_start"])

    def test_l1_to_l4_have_no_entry_filter_and_no_start_tracking(self):
        for n in VERSIONS:
            v = self.versions()[n]
            self.assertFalse(v.get("track_start"), n)
            for key in ("min_pool_age_minutes", "max_price_change_5m_pct", "min_market_cap_usd"):
                self.assertNotIn(key, v)
            self.assertEqual(LiquidVersion(CFG["liquid"], v, "/tmp", 10).entry, {})

    def test_the_liquid_trigger_and_the_costs_are_shared(self):
        lc = CFG["liquid"]
        self.assertEqual((lc["min_liquidity_usd"], lc["buy_slippage_pct"],
                          lc["round_trip_cost_pct"]), (50_000, 1.5, 3))
        for n in NEW:
            cfg = version(n, "/tmp").cfg
            self.assertEqual((cfg["buy_amount_usd"], cfg["buy_slippage_pct"],
                              cfg["round_trip_cost_pct"]), (10, 1.5, 3))


class EntryFilterTests(unittest.TestCase):
    def problems(self, **kw):
        return entry_filter_problems(with_pair(**kw), NOW, L5)

    def test_a_token_that_meets_every_condition_is_bought(self):
        self.assertEqual(self.problems(), [])

    def test_the_boundaries(self):
        self.assertEqual(self.problems(age_minutes=30), [])
        self.assertEqual(self.problems(age_minutes=29.9), [("pool_age", "failed")])
        self.assertEqual(self.problems(change_5m=10), [])
        self.assertEqual(self.problems(change_5m=10.01), [("price_change_5m", "failed")])
        self.assertEqual(self.problems(change_5m=-50), [])
        self.assertEqual(self.problems(mcap=250_000), [])
        self.assertEqual(self.problems(mcap=249_999), [("market_cap", "failed")])

    def test_every_failed_condition_is_listed(self):
        self.assertEqual(self.problems(age_minutes=5, change_5m=40, mcap=1000),
                         [("pool_age", "failed"), ("price_change_5m", "failed"),
                          ("market_cap", "failed")])

    def test_a_missing_value_is_never_bought(self):
        self.assertEqual(self.problems(age_minutes=None), [("pool_age", "missing")])
        self.assertEqual(self.problems(change_5m=None), [("price_change_5m", "missing")])
        self.assertEqual(self.problems(mcap=None), [("market_cap", "missing")])
        self.assertEqual(self.problems(age_minutes=None, change_5m=None, mcap=None),
                         [("pool_age", "missing"), ("price_change_5m", "missing"),
                          ("market_cap", "missing")])
        res = with_pair()
        res.pair["priceChange"] = None
        self.assertEqual(entry_filter_problems(res, NOW, L5), [("price_change_5m", "missing")])
        res.pair = None
        self.assertEqual(len(entry_filter_problems(res, NOW, L5)), 3)

    def test_the_market_cap_falls_back_to_fdv_like_candidates_csv(self):
        self.assertEqual(self.problems(mcap=None, fdv=400_000), [])

    def test_counting_each_condition(self):
        state = {}
        count_entry(state, NOW, [("pool_age", "failed"), ("market_cap", "missing")], False)
        count_entry(state, NOW, [], True)
        count_entry(state, NOW + timedelta(days=1), [("pool_age", "failed")], False)
        self.assertEqual(state["filter_skips"]["2026-10-04"],
                         {"considered": 2, "bought": 1, "skipped": 1, "failed_pool_age": 1,
                          "missing_market_cap": 1})
        self.assertEqual(state["filter_skips"]["2026-10-05"]["failed_pool_age"], 1)


class L6StopLossTests(ExitTests):
    """l6: l4's hour, plus a -25% stop loss and nothing else."""

    def test_l6_stops_at_minus_25_and_holds_otherwise(self):
        t = trader("l6", self.d)
        buy_at(t)                                              # entry 1.015
        self.assertEqual(self.go(t, 0.77, 5), [])              # -24.1%: not yet
        (sale,) = self.go(t, 0.75, 6)                          # -26.1%
        self.assertIn("stop loss", sale["reason"])
        self.assertTrue(sale["closed"])
        self.assertEqual(t.open_positions, [])

    def test_l6_has_no_take_profit_no_trailing_stop_and_sells_after_an_hour(self):
        t = trader("l6", os.path.join(self.d, "b"))
        buy_at(t)
        for minutes, price in ((5, 3.0), (10, 0.9), (59, 1.0)):
            self.assertEqual(self.go(t, price, minutes), [])
        (sale,) = self.go(t, 1.0, 60)
        self.assertIn("time exit", sale["reason"])

    def test_l6_costs_match_l4(self):
        a, b = trader("l4", os.path.join(self.d, "a")), trader("l6", os.path.join(self.d, "b"))
        buy_at(a)
        buy_at(b)
        (x,), (y,) = self.go(a, 1.2, 60), self.go(b, 1.2, 60)
        self.assertEqual(x["pnl_usd"], y["pnl_usd"])

    def test_l5_exits_are_l3s(self):
        a, b = trader("l3", os.path.join(self.d, "a")), trader("l5", os.path.join(self.d, "b"))
        buy_at(a)
        buy_at(b)
        for minutes, price in ((1, 1.6), (2, 1.9), (3, 1.6)):
            ra, rb = self.go(a, price, minutes), self.go(b, price, minutes)
            self.assertEqual([(s["reason"], s["pnl_usd"]) for s in ra],
                             [(s["reason"], s["pnl_usd"]) for s in rb])
        self.assertEqual(a.open_positions, b.open_positions)


class FilteredApi(DemoApi):
    """DemoApi whose pairs carry the given 5-minute change, market cap and pool age."""

    def __init__(self, change_5m=5.0, mcap=None, age_minutes=3 * 24 * 60):
        super().__init__()
        self.change_5m, self.mcap, self.age_minutes = change_5m, mcap, age_minutes

    def pairs_for_tokens(self, addresses):
        pairs = super().pairs_for_tokens(addresses)
        for p in pairs:
            p["priceChange"]["m5"] = self.change_5m
            if self.mcap is not None:
                p["marketCap"] = p["fdv"] = self.mcap
            if self.age_minutes is not None:       # relative to the tests' fixed clock (NOW)
                p["pairCreatedAt"] = (NOW - timedelta(minutes=self.age_minutes)).timestamp() * 1000
        return pairs


class NewVersionBotTests(BotTests):
    """The bot with l5 and l6 (BotTests' own tests run again on the bigger config)."""

    def liquid_tokens(self):
        candidates = rows(os.path.join(self.d, "main-1min", "candidates.csv"))
        return {r["token_address"] for r in candidates
                if r["liquidity_usd"] and float(r["liquidity_usd"]) >= 50_000 and r["price_usd"]}

    def bought(self, name):
        return {r["token_address"] for r in rows(os.path.join(self.folder(name), "journal.csv"))}

    def skips(self, name="l5"):
        with open(os.path.join(self.folder(name), "positions.json")) as fh:
            days = json.load(fh).get("filter_skips") or {}
        total = {}
        for counts in days.values():
            for key, n in counts.items():
                total[key] = total.get(key, 0) + n
        return total

    def test_l6_buys_exactly_what_l4_buys(self):
        self.bot(api=FilteredApi()).run_once(NOW, lambda *a: None)
        self.assertTrue(self.liquid_tokens())
        self.assertEqual(self.bought("l6"), self.bought("l4"))
        self.assertEqual(self.bought("l6"), self.liquid_tokens())

    def test_l5_buys_when_every_condition_holds(self):
        self.bot(api=FilteredApi(change_5m=5.0)).run_once(NOW, lambda *a: None)
        self.assertEqual(self.bought("l5"), self.liquid_tokens())
        self.assertEqual(self.bought("l5"), self.bought("l3"))
        n = len(self.liquid_tokens())
        self.assertEqual(self.skips(), {"considered": n, "bought": n})
        entry = rows(os.path.join(self.folder("l5"), "entries.csv"))[0]
        self.assertAlmostEqual(float(entry["fill_price_usd"]),
                               float(entry["price_usd"]) * 1.015, places=9)

    def test_l5_skips_each_failed_condition_and_counts_it(self):
        cases = ((dict(change_5m=11.0), "failed_price_change_5m"),
                 (dict(change_5m=5.0, mcap=100_000), "failed_market_cap"),
                 (dict(change_5m=5.0, age_minutes=10), "failed_pool_age"))
        for kw, key in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as d:
                self.d = d
                self.bot(api=FilteredApi(**kw)).run_once(NOW, lambda *a: None)
                n = len(self.liquid_tokens())
                self.assertGreater(n, 0)
                self.assertEqual(self.bought("l5"), set())
                skips = self.skips()
                self.assertEqual((skips["considered"], skips["skipped"], skips[key]), (n, n, n))
                self.assertNotIn("bought", skips)
                # the other versions are not affected by l5's filter
                self.assertEqual(self.bought("l3"), self.liquid_tokens())
                self.assertEqual(self.bought("l6"), self.liquid_tokens())
                self.assertFalse(os.path.exists(os.path.join(self.folder("l5"), "journal.csv")))

    def test_l5_does_not_buy_when_a_value_is_missing(self):
        self.bot(api=FilteredApi(change_5m=None)).run_once(NOW, lambda *a: None)
        n = len(self.liquid_tokens())
        self.assertEqual(self.bought("l5"), set())
        self.assertEqual(self.skips()["missing_price_change_5m"], n)
        self.assertEqual(self.bought("l3"), self.liquid_tokens())

    def test_l5_never_buys_a_token_twice(self):
        bot = self.bot(api=FilteredApi())
        bot.run_once(NOW, lambda *a: None)
        before = len(rows(os.path.join(self.folder("l5"), "journal.csv")))
        bot.run_once(NOW + timedelta(minutes=1), lambda *a: None)
        self.bot(api=FilteredApi()).run_once(NOW + timedelta(minutes=2), lambda *a: None)
        self.assertEqual(len(rows(os.path.join(self.folder("l5"), "journal.csv"))), before)
        self.assertEqual(self.skips()["considered"], before)          # counted once each

    def test_the_start_time_is_recorded_once_and_only_for_l5_and_l6(self):
        self.bot(api=FilteredApi()).run_once(NOW + timedelta(seconds=7.5), lambda *a: None)
        self.bot(api=FilteredApi()).run_once(NOW + timedelta(minutes=5), lambda *a: None)
        for n in NEW:
            with open(os.path.join(self.folder(n), "positions.json")) as fh:
                state = json.load(fh)
            self.assertEqual(state["started_utc"],        # the first run's minute, to the second
                             (NOW + timedelta(seconds=7)).isoformat())
        for n in VERSIONS:
            with open(os.path.join(self.folder(n), "positions.json")) as fh:
                state = json.load(fh)
            self.assertNotIn("started_utc", state)
            self.assertNotIn("filter_skips", state)

    def test_l1_to_l4_files_are_the_same_with_or_without_l5_and_l6(self):
        import copy
        only_old = copy.deepcopy(CFG)
        only_old["liquid"]["versions"] = [v for v in only_old["liquid"]["versions"]
                                          if v["name"] in VERSIONS]
        results = {}
        for label, cfg in (("old", only_old), ("new", CFG)):
            with tempfile.TemporaryDirectory() as d:
                bot = m1.MainOneMinute(cfg, d, FilteredApi())
                bot.run_once(NOW, lambda *a: None)
                later = m1.MainOneMinute(cfg, d, DemoApi({GOOD: 1.6}))
                later.run_once(NOW + timedelta(minutes=1), lambda *a: None)
                later.run_once(NOW + timedelta(minutes=31), lambda *a: None)
                files = {}
                for n in VERSIONS:
                    folder = os.path.join(d, "main-1min", "liquid", n)
                    for name in ("journal.csv", "entries.csv", "positions.json"):
                        with open(os.path.join(folder, name)) as fh:
                            text = fh.read()
                        if name == "positions.json":          # the slippage "since" is the wall clock
                            state = json.loads(text)
                            state.pop("buy_slippage", None)
                            text = json.dumps(state, sort_keys=True)
                        files[(n, name)] = text
                results[label] = files
        self.assertEqual(results["old"].keys(), results["new"].keys())
        for key in results["old"]:
            self.assertEqual(results["old"][key], results["new"][key], key)

    def test_the_new_versions_have_their_own_files(self):
        self.bot(api=FilteredApi()).run_once(NOW, lambda *a: None)
        for n in NEW:
            for name in ("journal.csv", "entries.csv", "positions.json"):
                self.assertTrue(os.path.exists(os.path.join(self.folder(n), name)), (n, name))
        for n in NEW:
            for name in ("journal.csv", "entries.csv", "positions.json"):
                path = f"data/main-1min/liquid/{n}/{name}"
                self.assertNotEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                                   cwd=HERE).returncode, 0, path)

    def test_l6_stop_loss_runs_in_the_bot(self):
        self.bot(api=FilteredApi()).run_once(NOW, lambda *a: None)
        self.bot(api=DemoApi({GOOD: 0.7})).run_once(NOW + timedelta(minutes=1), lambda *a: None)
        sold = lambda n: [r for r in rows(os.path.join(self.folder(n), "journal.csv"))  # noqa: E731
                          if r["action"] == "SELL" and r["token_address"] == GOOD]
        self.assertIn("stop loss", sold("l6")[0]["reason"])
        self.assertIn("stop loss", sold("l5")[0]["reason"])
        self.assertEqual(sold("l4"), [])                       # l4 has no stop loss
        self.assertEqual(sold("l1"), [])


class NewVersionReportTests(unittest.TestCase):
    def test_the_daily_comparison_has_a_column_for_each_new_version_and_the_filter_lines(self):
        import io
        import compare
        with tempfile.TemporaryDirectory() as d:
            m1.MainOneMinute(CFG, d, FilteredApi(change_5m=11.0)).run_once(NOW, lambda *a: None)
            cfg = dict(CFG, files={"data_folder": d})
            with unittest.mock.patch.object(compare, "load_config", lambda: cfg), \
                    unittest.mock.patch.dict(os.environ, {"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""}), \
                    unittest.mock.patch("sys.argv", ["compare.py", "--date", "2026-10-04"]), \
                    unittest.mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(compare.main(), 0)
        text = out.getvalue()
        header = next(x for x in text.splitlines() if x.startswith("| | main"))
        self.assertIn("main (1 min) liquid l4 | main (1 min) liquid l5 | main (1 min) liquid l6 "
                      "| early", header)
        self.assertIn("| main (1 min) liquid l5: server |", text)
        self.assertIn("| main (1 min) liquid l6: server |", text)
        self.assertIn("**main (1 min) liquid l5 entry filter** (started 2026-10-04 12:00 UTC", text)
        self.assertIn("5-minute price change above 10%:", text)
        self.assertIn("pool age under 30 min: 0 (no value: 0)", text)
        self.assertIn("market cap under $250,000: 0 (no value: 0)", text)
        self.assertNotIn("liquid l6 entry filter", text)           # l6 has no filter

    def test_only_trades_from_the_start_are_counted(self):
        from screener import compare as sc
        with tempfile.TemporaryDirectory() as d:
            journal = ("time_utc,action,symbol,token_address,reason,price_usd,usd_amount,pnl_usd,"
                       "pnl_pct,running_total_pnl_usd,price_source,price_time_utc\n"
                       "2026-11-09 10:00:00,BUY,OLD,OLDADDR,x,1,10.00,0.00,0.0,0.00,,\n"
                       "2026-11-09 10:30:00,SELL,OLD,OLDADDR,x,1,10.00,5.00,50.0,5.00,,\n"
                       "2026-11-10 10:00:00,BUY,NEW,NEWADDR,x,1,10.00,0.00,0.0,5.00,,\n"
                       "2026-11-10 10:30:00,SELL,NEW,NEWADDR,x,1,10.00,-2.00,-20.0,3.00,,\n")
            with open(os.path.join(d, "journal.csv"), "w") as fh:
                fh.write(journal)
            with open(os.path.join(d, "positions.json"), "w") as fh:
                json.dump({"open_positions": [], "started_utc": "2026-11-10T00:00:00"}, fh)
            stats = sc.strategy_stats(d, 3, "2026-11-10")
            self.assertEqual((stats["closed"], round(stats["realized"], 2)), (1, -2.0))
            self.assertEqual([t["symbol"] for t in sc.closed_trades(d)], ["NEW"])
            os.remove(os.path.join(d, "positions.json"))          # no start recorded: all counted
            self.assertEqual(sc.strategy_stats(d, 3, "2026-11-10")["closed"], 2)

    def test_the_health_row_says_what_l5_needs(self):
        from screener.health import health_lines
        with tempfile.TemporaryDirectory() as d:
            text = "\n".join(health_lines(d, CFG, NOW))
        line5 = next(x for x in text.splitlines() if x.startswith("| main (1 min) liquid l5: server"))
        self.assertIn("pool age at least 30 min", line5)
        self.assertIn("5-minute change at most 10%", line5)
        self.assertIn("market cap at least $250,000", line5)
        line6 = next(x for x in text.splitlines() if x.startswith("| main (1 min) liquid l6: server"))
        self.assertNotIn("pool age", line6)


class LiquidErrorTests(unittest.TestCase):
    """A broken liquid step never stops the rest of the minute."""

    def test_candidates_and_the_other_versions_still_run(self):
        import copy
        from unittest import mock
        cfg = copy.deepcopy(CFG)
        for v in cfg["main_1min"]["versions"]:
            v.pop("stopped", None)
        with tempfile.TemporaryDirectory() as d:
            from tests.test_main_1min import ChangingApi, Organic
            bot = m1.MainOneMinute(cfg, d, ChangingApi(h1=40.0), Organic(80))
            lines = []
            with mock.patch.object(m1.MainOneMinute, "_liquid",
                                   side_effect=RuntimeError("boom")), \
                    self.assertLogs("main_1min", level="ERROR") as logged:
                bot.run_once(NOW, lines.append)
                bot.run_once(NOW + timedelta(minutes=1), lines.append)
            self.assertIn("boom", "\n".join(logged.output))
            main = os.path.join(d, "main-1min")
            self.assertTrue(rows(os.path.join(main, "candidates.csv")))
            for name in ("b", "c"):                      # main (1 min) B and C still buy
                self.assertTrue(rows(os.path.join(main, name, "journal.csv")), name)
            with open(os.path.join(main, "health.json")) as fh:
                data = json.load(fh)
            errors = sum(h.get("liquid errors", 0) for h in data["calls_per_hour"].values())
            self.assertEqual(errors, 2)
            self.assertIn("passed", lines[0])            # the run's summary line still printed
            self.assertFalse(os.path.exists(os.path.join(main, "liquid", "l1", "journal.csv")))

    def test_a_failure_halfway_keeps_what_was_bought(self):
        import copy
        from unittest import mock
        cfg = copy.deepcopy(CFG)
        with tempfile.TemporaryDirectory() as d:
            bot = m1.MainOneMinute(cfg, d, DemoApi())
            real = m1.LiquidSafeTrader.buy
            calls = []

            def flaky(self, *a, **kw):
                calls.append(1)
                if len(calls) > 4:
                    raise RuntimeError("boom")
                return real(self, *a, **kw)
            with mock.patch.object(m1.LiquidSafeTrader, "buy", flaky), \
                    self.assertLogs("main_1min", level="ERROR"):
                bot.run_once(NOW, lambda *a: None)
            self.assertTrue(rows(os.path.join(d, "main-1min", "candidates.csv")))
            saved = rows(os.path.join(d, "main-1min", "liquid", "l1", "journal.csv"))
            self.assertEqual(len(saved), 1)              # the buy made before the error


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
