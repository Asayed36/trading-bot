"""Checks for the "early" paper strategy, the daily comparison, and that the
main strategy is unaffected by either. Run with:  python -m unittest -v
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import load_config, run  # noqa: E402
from screener.api import ApiError, RateLimited  # noqa: E402
from screener.compare import report, strategy_stats  # noqa: E402
from screener.demo import EARLY_GOOD, EARLY_TOKENS, GOOD, DemoApi  # noqa: E402
from screener.early import (EarlyStrategy, EarlyTrader, gecko_tokens,  # noqa: E402
                            pullback_checks)
from screener.filters import FAIL, PASS, Result  # noqa: E402
from screener.github_issues import MARKER_RE, issue_body, issue_title, marker  # noqa: E402
from screener.paper_trader import now_utc  # noqa: E402

CFG = load_config()
E = CFG["early"]
QUIET = dict(out=lambda *a: None)


def read(path):
    with open(path) as fh:
        return fh.read()


class EarlyScreeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, api=None, dead=()):
        strategy = EarlyStrategy(CFG, self.tmp.name)
        strategy.trader.state["dead_creators"] = list(dead)
        return strategy, strategy.fetch(api or DemoApi(), **QUIET)

    def result(self, plan, symbol):
        return next(r for r in plan["results"] if r.symbol == symbol)

    def failed(self, result):
        return [c.name for c in result.checks if c.status == FAIL]

    def test_only_the_clean_pullback_passes(self):
        _, plan = self.plan()
        self.assertEqual([r.symbol for r in plan["results"] if r.passed], ["PULLY"])
        self.assertEqual(self.failed(self.result(plan, "DOGGO")), ["Not a copycat name"])
        self.assertEqual(self.failed(self.result(plan, "INSIDY")), ["No insider flags"])
        self.assertEqual(self.failed(self.result(plan, "WHALY")), ["Top 10 holders"])
        # these two never reach the RugCheck stage
        self.assertEqual(plan["waiting"]["Graduated 30+ min ago"], 1)      # FRESHY
        self.assertEqual(plan["waiting"]["Pullback after a spike"], 1)     # CHASEY
        # the main demo tokens are 3 days old, so they're not even watched
        self.assertNotIn(GOOD, plan["watch"])
        self.assertEqual(len(plan["watch"]), len(EARLY_TOKENS))

    def test_known_bad_creator_is_skipped(self):
        _, plan = self.plan(dead=["DEV-PULLY"])
        self.assertEqual(self.failed(self.result(plan, "PULLY")), ["Creator has no dead tokens"])

    def test_dead_token_remembers_its_creator(self):
        # PULLY's market cap collapses to $1,200: it's dead, so its creator is
        # remembered and it leaves the watchlist.
        api = DemoApi({EARLY_GOOD: 0.01})
        strategy, plan = self.plan(api)
        self.assertIn("DEV-PULLY", plan["dead_add"])
        self.assertNotIn(EARLY_GOOD, plan["watch"])
        strategy.apply(plan, lambda *a, **k: {}, **QUIET)
        self.assertIn("DEV-PULLY", strategy.trader.state["dead_creators"])

    def test_pullback_rules(self):
        entry = {"peak": 1.0, "low_before_peak": 0.5}  # a +100% spike

        def pair(price, m5=1.0, buys=10, sells=5):
            return {"priceUsd": str(price), "priceChange": {"m5": m5},
                    "txns": {"h1": {"buys": buys, "sells": sells}}}

        def statuses(p, e=entry):
            return [c.status for c in pullback_checks(p, e, E)]

        self.assertEqual(statuses(pair(0.7)), [PASS, PASS, PASS])       # 30% off the peak
        self.assertEqual(statuses(pair(0.9))[0], FAIL)                  # only 10% off
        self.assertEqual(statuses(pair(0.4))[0], FAIL)                  # 60% off: collapse
        self.assertEqual(statuses(pair(0.7, m5=-2))[1], FAIL)           # still falling
        self.assertEqual(statuses(pair(0.7, buys=5, sells=9))[2], FAIL)  # sellers in charge
        small = {"peak": 1.0, "low_before_peak": 0.8}                   # only +25%
        self.assertEqual(statuses(pair(0.7), small)[0], FAIL)

    def test_copycat_rule_allows_only_the_most_liquid(self):
        from screener import early
        pair = EARLY_TOKENS[EARLY_GOOD][0]  # PULLY, $25,000 liquidity
        now = now_utc()
        old = (now - timedelta(days=30)).timestamp() * 1000
        new = (now - timedelta(days=1)).timestamp() * 1000

        class Search:
            def __init__(self, *others):  # (created_ms, liquidity) per other PULLY
                self.others = others

            def search_pairs(self, q):
                return [{"chainId": "solana", "pairCreatedAt": created,
                         "liquidity": {} if liq is None else {"usd": liq},
                         "baseToken": {"address": f"OTHER{i}", "symbol": "pully", "name": "x"}}
                        for i, (created, liq) in enumerate(self.others)]

        def status(api, own_pair=pair):
            return early.copycat_check(api, EARLY_GOOD, own_pair, E, now).status

        self.assertEqual(status(Search()), PASS)                        # no namesakes
        self.assertEqual(status(Search((new, 5_000), (None, 9_000))), PASS)  # we're the most liquid
        self.assertEqual(status(Search((new, 5_000), (new, 40_000))), FAIL)  # one has more
        self.assertEqual(status(Search((new, 25_000))), FAIL)            # a tie isn't "highest"
        self.assertEqual(status(Search((new, None))), PASS)              # unknown counts as $0
        self.assertEqual(status(Search((old, 900_000))), PASS)           # older than 7 days: ignored
        no_liq = dict(pair, liquidity={})
        self.assertEqual(status(Search((new, 1)), no_liq), FAIL)        # our own is unknown
        detail = early.copycat_check(Search((new, 5_000)), EARLY_GOOD, pair, E, now).detail
        self.assertIn("most liquidity of 2 tokens called PULLY", detail)

    def test_gecko_tokens(self):
        pools = DemoApi().gecko_new_pools()
        pools.append({"relationships": {"base_token": {"data": {"id": "eth_0xabc"}}}})
        pools.append({"bad": "shape"})
        tokens = gecko_tokens(pools)
        self.assertEqual(tokens, list(EARLY_TOKENS))  # no SOL, no other chains, no dupes
        self.assertEqual(gecko_tokens(None), [])

    def test_watchlist_carries_over_and_expires(self):
        strategy, plan = self.plan()
        strategy.apply(plan, lambda *a, **k: {}, **QUIET)
        again = EarlyStrategy(CFG, self.tmp.name)
        self.assertEqual(set(again.trader.state["watchlist"]), set(EARLY_TOKENS))
        # 5 hours later every demo token is over 6 hours old: all dropped
        later = again.fetch(DemoApi(), now=now_utc() + timedelta(hours=5), **QUIET)
        self.assertEqual(later["watch"], {})


class EarlyExitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trader = EarlyTrader(E["paper_trading"], self.tmp.name)
        self.t0 = now_utc()
        self.trader.buy(Result("TOK", "TOK", "Tok", {"priceUsd": "1.0"}), when=self.t0)

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, price, minutes):
        return self.trader.update({"TOK": price}, when=self.t0 + timedelta(minutes=minutes))

    def test_sell_half_at_2x_then_trailing_stop(self):
        sells = self.at(2.0, 20)
        self.assertEqual(len(sells), 1)
        self.assertIn("take profit", sells[0]["reason"])
        self.assertEqual(self.trader.open_positions[0]["remaining_fraction"], 0.5)
        self.assertEqual(self.at(2.0, 60), [])             # no time stop after profit
        sells = self.at(1.5, 90)                            # 25% off the 2.0 peak: hold
        self.assertEqual(sells, [])
        sells = self.at(1.1, 120)                           # 45% off the peak
        self.assertIn("trailing stop after profit", sells[0]["reason"])
        self.assertFalse(self.trader.open_positions)

    def test_time_stop_after_45_minutes_without_2x(self):
        self.assertEqual(self.at(1.3, 44), [])
        sells = self.at(1.3, 46)
        self.assertIn("time stop: no 2x after 46 min", sells[0]["reason"])
        # $13 - $10 - 5% fees = +$2.50
        self.assertAlmostEqual(sells[0]["pnl_usd"], 2.5)

    def test_hard_stop(self):
        sells = self.at(0.69, 5)
        self.assertIn("hard stop: down 31%", sells[0]["reason"])

    def test_max_hold_after_profit(self):
        self.at(2.0, 10)
        sells = self.at(2.5, 24 * 60 + 1)
        self.assertIn("max hold", sells[0]["reason"])


class RunTogetherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.early = os.path.join(self.tmp.name, "early")

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_strategies_keep_separate_records(self):
        results = run(DemoApi(), CFG, self.tmp.name, **QUIET)
        self.assertEqual(sorted(r.symbol for r in results if r.passed), ["FRENS", "GOODCAT"])
        main = read(os.path.join(self.tmp.name, "journal.csv"))
        early = read(os.path.join(self.early, "journal.csv"))
        self.assertIn("GOODCAT", main)
        self.assertNotIn("PULLY", main)
        self.assertIn("PULLY", early)
        self.assertNotIn("GOODCAT", early)

    def test_main_strategy_identical_with_early_off(self):
        off = dict(CFG, early=dict(CFG["early"], enabled=False))
        with tempfile.TemporaryDirectory() as other:
            run(DemoApi(), off, other, **QUIET)
            run(DemoApi(), CFG, self.tmp.name, **QUIET)
            a = json.loads(read(os.path.join(other, "positions.json")))
            b = json.loads(read(os.path.join(self.tmp.name, "positions.json")))
            self.assertFalse(os.path.exists(os.path.join(other, "early")))
        strip = [{k: v for k, v in p.items() if k not in ("entry_time", "issue_details")}
                 for p in a["open_positions"]]
        self.assertEqual(strip, [{k: v for k, v in p.items()
                                  if k not in ("entry_time", "issue_details")}
                                 for p in b["open_positions"]])

    def test_early_source_rate_limit_skips_only_early(self):
        class GeckoLimited(DemoApi):
            def gecko_new_pools(self, page=1):
                raise RateLimited("GeckoTerminal kept saying 'too many requests'")

        run(DemoApi(), CFG, self.tmp.name, **QUIET)
        before = read(os.path.join(self.early, "positions.json"))
        lines = []
        run(GeckoLimited({GOOD: 0.5}), CFG, self.tmp.name, out=lines.append)
        self.assertIn("stop loss", read(os.path.join(self.tmp.name, "journal.csv")))  # main traded
        self.assertEqual(read(os.path.join(self.early, "positions.json")), before)   # early didn't
        self.assertTrue(any("Skipped this run" in line for line in lines))

    def test_gecko_error_is_not_fatal(self):
        class GeckoDown(DemoApi):
            def gecko_new_pools(self, page=1):
                raise ApiError("GeckoTerminal answered with error 503")

        lines = []
        run(GeckoDown(), CFG, self.tmp.name, out=lines.append)
        self.assertTrue(any("GeckoTerminal unavailable" in line for line in lines))
        self.assertFalse(any("Skipped this run" in line for line in lines))


class EarlyIssueTests(unittest.TestCase):
    def test_title_label_and_marker_are_per_strategy(self):
        pos = {"address": "ADDR", "symbol": "PULLY", "entry_price": 0.0006,
               "entry_time": "2026-09-30T10:00:00+00:00",
               "issue_details": {"name": "Pully", "url": "u", "passed_at": "2026-09-30T10:00:00+00:00",
                                 "market_cap_usd": 1, "liquidity_usd": 1, "change_24h_pct": 1,
                                 "top_holders": [], "extra": [["Token age", "3.0h"]]}}
        self.assertEqual(issue_title(pos, "early"), "PASSED (early): PULLY")
        self.assertEqual(issue_title(pos, "main"), "PASSED: PULLY")
        body = issue_body(pos, E["paper_trading"], "note", "early")
        for text in ("**Strategy:** early", "| Token age | 3.0h |", "$0.0012 (+100%)",
                     "$0.00042 (-30%)", "2026-09-30 10:45 UTC (45 min)",
                     "40% below the highest price"):
            self.assertIn(text, body)
        self.assertEqual(MARKER_RE.search(marker("ADDR", "early")).groups(), ("ADDR", "early"))
        self.assertEqual(MARKER_RE.search(marker("ADDR")).groups(), ("ADDR", None))

    def test_early_issue_opened_by_run(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_screener import FakeGitHub
        gh = FakeGitHub()
        with tempfile.TemporaryDirectory() as d:
            run(DemoApi(), CFG, d, issues=gh, **QUIET)
            run(DemoApi(), CFG, d, issues=gh, **QUIET)  # no duplicates
        early = [i for i in gh.issues.values() if "strategy: early" in i["labels"]]
        self.assertEqual([i["title"] for i in early], ["PASSED (early): PULLY"])
        self.assertIn("passed", early[0]["labels"])
        self.assertIn(marker(EARLY_GOOD, "early"), early[0]["body"])


class CompareTests(unittest.TestCase):
    def write(self, folder, rows, open_positions=()):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "journal.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time_utc", "action", "symbol", "token_address", "reason",
                        "price_usd", "usd_amount", "pnl_usd", "pnl_pct", "running_total_pnl_usd"])
            w.writerows(rows)
        with open(os.path.join(folder, "positions.json"), "w") as fh:
            json.dump({"open_positions": list(open_positions)}, fh)

    def test_stats_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, [
                ["2026-09-29 10:00:00", "BUY", "A", "a", "", "1", "10", "0", "0", "0"],
                ["2026-09-29 11:00:00", "SELL", "A", "a", "tp", "2", "9.7", "4.70", "0", "0"],
                ["2026-09-30 01:00:00", "SELL", "A", "a", "trail", "1.5", "7", "2.00", "0", "0"],
                ["2026-09-30 02:00:00", "BUY", "B", "b", "", "1", "10", "0", "0", "0"],
                ["2026-09-30 03:00:00", "SELL", "B", "b", "stop", "0.6", "5.7", "-4.30", "0", "0"],
                ["2026-09-30 04:00:00", "BUY", "C", "c", "", "1", "10", "0", "0", "0"],
            ], [{"address": "c", "remaining_fraction": 1.0, "tokens": 10, "last_price": 1.2,
                 "cost_usd": 10}])
            s = strategy_stats(d, 3, "2026-09-30")
            self.assertEqual((s["buys_today"], s["closed_today"]), (2, 2))
            self.assertEqual((s["wins_today"], s["losses_today"]), (1, 1))
            self.assertAlmostEqual(s["realized_today"], -2.30)
            self.assertAlmostEqual(s["realized"], 2.40)
            self.assertEqual((s["closed"], s["wins"], s["win_rate"]), (2, 1, 50))
            self.assertAlmostEqual(s["best"], 6.70)
            self.assertAlmostEqual(s["unrealized"], 12 - 10 - 0.3)
            text = report([("main", d, 3), ("early", os.path.join(d, "none"), 5)], "2026-09-30")
            self.assertIn("<!-- daily-comparison: 2026-09-30 -->", text)
            self.assertIn("| Win rate | 50% (1 of 2) | – |", text)
            self.assertIn("| **Total P&L** | **$+4.10** | **$+0.00** |", text)


if __name__ == "__main__":
    unittest.main()
