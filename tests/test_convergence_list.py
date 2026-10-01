"""Checks for building the convergence strategy's list of tracked wallets:
recent sellers of the week's winners as candidates, a quick retry when a
finished list is too small to ever give a signal, and the summary of why
candidates didn't qualify. Run with:  python -m unittest -v
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import load_config  # noqa: E402
from screener.api import ApiError, RateLimited  # noqa: E402
from screener.convergence import ConvergenceStrategy  # noqa: E402
from screener.demo import DemoApi, demo_rpc_factory, demo_trader_history  # noqa: E402
from screener.paper_trader import now_utc  # noqa: E402

CFG = load_config()
FAST = dict(CFG, convergence=dict(CFG["convergence"], helius_every_minutes=2))
WINNER_POOL = "POOL-ROCKET"   # the demo winner's pool


def trade(wallet, kind, usd):
    return {"tx_from_address": wallet, "kind": kind, "volume_in_usd": str(usd),
            "block_timestamp": "2026-10-01T12:00:00Z"}


class TradesApi(DemoApi):
    """Demo data plus recent trades in the demo winner's pool."""

    def __init__(self, trades, fail=None):
        super().__init__()
        self.trades, self.fail, self.asked = trades, fail, []

    def gecko_pool_trades(self, pool):
        self.asked.append(pool)
        if self.fail:
            raise self.fail
        return self.trades if pool == WINNER_POOL else []


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history = demo_trader_history()

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, api=None, now=None, history=None):
        hist = self.history if history is None else history
        s = ConvergenceStrategy(FAST, self.tmp.name, rpc_factory=demo_rpc_factory(hist, {}))
        plan = s.fetch(api or DemoApi(), now=now)
        s.apply(plan, out=lambda *a: None)
        return plan

    def state(self):
        with open(os.path.join(self.tmp.name, "convergence", "positions.json")) as fh:
            return json.load(fh)

    def save(self, state):
        with open(os.path.join(self.tmp.name, "convergence", "positions.json"), "w") as fh:
            json.dump(state, fh)


class CandidateTests(Base):
    def test_recent_sellers_are_scored_first(self):
        api = TradesApi([trade("seller1", "sell", 900), trade("seller2", "sell", 300),
                         trade("buyer", "buy", 5000), trade("dust", "sell", 5)])
        history = dict(self.history, seller1=self.history["whale"])
        plan = self.go(api, history=history)
        self.assertEqual(api.asked, [WINNER_POOL])
        started = next(n for n in plan["notes"] if "refresh started" in n)
        self.assertIn("2 recent sellers, 10 top holders of 1 winners", started)
        tracked = [w["wallet"] for w in self.state()["tracked"]]
        self.assertIn("seller1", tracked)          # a profitable seller joins the list
        for wallet in ("buyer", "dust"):           # buys and tiny sells don't count
            self.assertNotIn(wallet, json.dumps(self.state()))

    def test_winners_remember_their_pool(self):
        self.go()
        (winner,) = self.state()["winners"]
        self.assertEqual(winner["pair"], WINNER_POOL)

    def test_pool_looked_up_for_winners_saved_before(self):
        self.go(history={})                         # an empty list, as on the server
        state = self.state()
        for w in state["winners"]:
            w.pop("pair")                           # saved before pools were kept
        state["list_updated"] = (now_utc() - timedelta(days=2)).isoformat()
        self.save(state)
        api = TradesApi([trade("seller1", "sell", 900)])
        self.go(api)
        self.assertEqual(api.asked, [WINNER_POOL])

    def test_geckoterminal_trouble_falls_back_to_holders(self):
        for error in (ApiError("down"), RateLimited("busy")):
            with self.subTest(error=type(error).__name__):
                self.tearDown()
                self.setUp()
                self.go(TradesApi([], fail=error))
                self.assertEqual(sorted(w["wallet"] for w in self.state()["tracked"]),
                                 ["h0", "h1", "whale"])


class SmallListRetryTests(Base):
    def empty_list(self):
        plan = self.go(history={})                  # nobody qualifies
        state = self.state()
        self.assertEqual(state["tracked"], [])
        self.assertNotIn("refresh", state)
        return plan

    def test_empty_list_is_rebuilt_after_a_day_not_a_week(self):
        self.empty_list()
        t0 = now_utc()
        plan = self.go(now=t0 + timedelta(hours=23))
        self.assertFalse(any("started" in n for n in plan["notes"]))
        self.assertEqual(self.state()["tracked"], [])
        plan = self.go(now=t0 + timedelta(hours=25))
        self.assertTrue(any("list retry started" in n for n in plan["notes"]))
        self.assertEqual(sorted(w["wallet"] for w in self.state()["tracked"]),
                         ["h0", "h1", "whale"])

    def test_small_list_from_before_this_fix_is_rebuilt_now(self):
        self.empty_list()
        state = self.state()
        state.pop("list_summary")                   # as saved on the server before
        self.save(state)
        plan = self.go(now=now_utc() + timedelta(hours=1))
        self.assertTrue(any("list retry started" in n for n in plan["notes"]))
        self.assertEqual(len(self.state()["tracked"]), 3)

    def test_no_retry_when_credits_are_half_used(self):
        self.empty_list()
        state = self.state()
        state["helius"]["used"] = int(CFG["convergence"]["helius_monthly_credits"] * 0.51)
        self.save(state)
        plan = self.go(now=now_utc() + timedelta(hours=25))
        self.assertFalse(any("started" in n for n in plan["notes"]))

    def test_a_good_list_still_waits_a_week(self):
        self.go()                                   # 3 wallets: enough for a signal
        plan = self.go(now=now_utc() + timedelta(days=3))
        self.assertFalse(any("started" in n for n in plan["notes"]))
        plan = self.go(now=now_utc() + timedelta(days=7, hours=1))
        self.assertTrue(any("weekly list refresh started" in n for n in plan["notes"]))


class SummaryTests(Base):
    def test_summary_says_why_candidates_failed(self):
        plan = self.go(history={})                  # nobody has traded
        done = next(n for n in plan["notes"] if "list refreshed" in n)
        self.assertIn("0 of 10 candidates qualified", done)
        self.assertIn("10 too few closed trades; 0 swaps in 0 transactions", done)

    def test_summary_is_saved_with_the_list(self):
        self.go()
        self.assertEqual(self.state()["list_summary"],
                         "7 too few closed trades, 3 qualified; 36 swaps in 36 transactions")


if __name__ == "__main__":
    unittest.main()
