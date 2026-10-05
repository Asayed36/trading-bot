"""Checks for building the convergence strategy's list of tracked wallets:
recent sellers of the week's winners as candidates, a new round every day
that grows the list (wallets scored lately skipped, tracked ones re-checked
weekly), credits paced per day, and the summary of why candidates didn't
qualify. Run with:  python -m unittest -v
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

from run import load_config  # noqa: E402
from screener.api import ApiError, RateLimited  # noqa: E402
from screener.convergence import ConvergenceStrategy, qualifies  # noqa: E402
from screener.demo import DemoApi, demo_rpc_factory, demo_trader_history  # noqa: E402
from screener.paper_trader import now_utc  # noqa: E402

CFG = running(load_config())
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
        started = next(n for n in plan["notes"] if "new candidate wallets" in n)
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


class GrowingListTests(Base):
    def test_a_new_round_every_day_not_every_week(self):
        t0 = now_utc()
        self.go(now=t0)                             # 3 wallets: whale, h0, h1
        plan = self.go(now=t0 + timedelta(hours=23))
        self.assertFalse(any("started" in n for n in plan["notes"]))
        plan = self.go(now=t0 + timedelta(hours=25))
        self.assertTrue(any("list refresh started" in n for n in plan["notes"]))

    def test_new_qualifiers_join_the_list_and_scored_wallets_are_skipped(self):
        t0 = now_utc()
        self.go(now=t0)
        self.assertEqual(sorted(w["wallet"] for w in self.state()["tracked"]),
                         ["h0", "h1", "whale"])
        # The next day a recent seller of the winner is also a proven trader:
        # it joins the 3 already tracked. The others were scored yesterday.
        api = TradesApi([trade("seller1", "sell", 900)])
        history = dict(self.history, seller1=self.history["whale"])
        plan = self.go(api, now=t0 + timedelta(hours=25), history=history)
        started = next(n for n in plan["notes"] if "new candidate wallets" in n)
        self.assertIn("1 new candidate wallets to score (1 recent sellers, 0 top holders of 1 "
                      "winners; 7 scored in the last 7 days skipped)", started)
        self.assertEqual(sorted(w["wallet"] for w in self.state()["tracked"]),
                         ["h0", "h1", "seller1", "whale"])

    def test_tracked_wallets_are_rechecked_weekly_and_leave_when_they_fail(self):
        t0 = now_utc()
        self.go(now=t0)
        later = t0 + timedelta(days=7, hours=1)
        history = demo_trader_history(later)        # the same traders, a week on...
        history.pop("h1")                           # ...but h1 stopped trading
        plan = self.go(now=later, history=history)
        started = next(n for n in plan["notes"] if "refresh started" in n)
        self.assertIn("3 tracked wallet(s) to re-check", started)
        self.assertTrue(any("left the list on its re-check" in n for n in plan["notes"]))
        self.assertEqual(sorted(w["wallet"] for w in self.state()["tracked"]), ["h0", "whale"])

    def test_wallets_with_too_few_transactions_arent_read(self):
        history = dict(self.history, few=self.history["whale"][:4])   # 4 transactions
        calls = []

        def factory(meter):
            rpc = demo_rpc_factory(history, {})(meter)[0]
            real = rpc.transaction

            def transaction(sig):
                calls.append(sig)
                return real(sig)
            rpc.transaction = transaction
            return rpc, rpc
        api = TradesApi([trade("few", "sell", 900)])
        s = ConvergenceStrategy(FAST, self.tmp.name, rpc_factory=factory)
        s.apply(s.fetch(api), out=lambda *a: None)
        self.assertTrue(calls)                                   # the others were read
        self.assertFalse(any(sig.startswith("few-") for sig in calls))
        self.assertNotIn("few", [w["wallet"] for w in self.state()["tracked"]])
        self.assertIn("few", self.state()["checked"])             # not scored again this week
        self.assertEqual(qualifies({"few_tx": True, "transactions": 4}, FAST["convergence"]),
                         (False, "only 4 transactions (too few for enough closed trades)"))

    def test_winners_not_used_lately_come_first(self):
        state = {"winners": [{"address": a, "symbol": a, "change": ch, "seen": now_utc().isoformat(),
                              "pair": None} for a, ch in (("A", 900), ("B", 500), ("C", 300))],
                 "winners_used": {"A": now_utc().isoformat()}}
        s = ConvergenceStrategy(dict(FAST, convergence=dict(FAST["convergence"],
                                                             winners_per_refresh=2)),
                                self.tmp.name, rpc_factory=demo_rpc_factory({}, {}))
        job = s._new_round(state, now_utc())
        self.assertEqual([w["address"] for w in job["winners"]], ["B", "C"])   # A: used today
        self.assertEqual(sorted(state["winners_used"]), ["A", "B", "C"])

    def test_winners_are_read_two_a_run(self):
        self.assertEqual(FAST["convergence"]["winners_per_run"], 2)
        winners = [{"address": f"W{i}", "symbol": f"W{i}", "change": 500 - i,
                    "seen": now_utc().isoformat(), "pair": f"POOL{i}"} for i in range(5)]
        self.go(history={})                                   # a first, empty list
        state = self.state()
        state["winners"] = winners
        state["list_updated"] = (now_utc() - timedelta(days=2)).isoformat()
        self.save(state)
        api = TradesApi([])
        reads = []
        for run in range(4):
            api.asked.clear()
            self.go(api, history={})
            reads.append(len(api.asked))
        # 6 winners (these 5 and the demo's ROCKET), never more than 2 a run
        self.assertEqual(reads, [2, 2, 2, 0])
        self.assertNotIn("refresh", self.state())             # the round finished

    def test_scoring_waits_once_todays_share_is_used(self):
        t0 = now_utc()
        self.go(now=t0)
        state = self.state()
        state["list_updated"] = (t0 - timedelta(days=2)).isoformat()     # a round is due
        state["refresh_spent"] = {t0.date().isoformat(): 10**6}          # today's share used
        self.save(state)
        plan = self.go(now=t0)
        self.assertTrue(any("today's share of the credits is used" in n for n in plan["notes"]))
        self.assertNotIn("refresh", self.state())


class SummaryTests(Base):
    def test_summary_says_why_candidates_failed(self):
        plan = self.go(history={})                  # nobody has traded
        done = next(n for n in plan["notes"] if "list refreshed" in n)
        self.assertIn("list refreshed: tracking 0 wallet(s); 10 too few closed trades; "
                      "0 swaps in 0 transactions", done)

    def test_summary_is_saved_with_the_list(self):
        self.go()
        self.assertEqual(self.state()["list_summary"],
                         "7 too few closed trades, 3 qualified; 36 swaps in 36 transactions")


if __name__ == "__main__":
    unittest.main()
