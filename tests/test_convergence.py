"""Checks for the "convergence" paper strategy and its Helius credit budget.
Run with:  python -m unittest -v
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

from run import load_config, run  # noqa: E402
from screener.api import ApiError, RateLimited  # noqa: E402
from screener.compare import helius_lines  # noqa: E402
from screener.convergence import (BudgetPaused, ConvergenceStrategy,  # noqa: E402
                                  CreditMeter, Rpc, cycle_start, decode_swaps,
                                  next_cycle_start, qualifies, score_trader)
from screener.demo import (EARLY_GOOD, DemoApi, DemoRpc, _swap,  # noqa: E402
                           demo_rpc_factory, demo_trader_history)
from screener.paper_trader import now_utc  # noqa: E402

CFG = running(load_config())
# helius_every_minutes = 2 means no gap between Helius checks, so these tests
# can run the strategy several times in a row. The gap has its own tests.
C = dict(CFG["convergence"], helius_every_minutes=2)
FAST = dict(CFG, convergence=C)
QUIET = dict(out=lambda *a: None)
TRACKED = ["whale", "h0", "h1"]


def with_conv(**changes):
    return dict(CFG, convergence=dict(C, **changes))


class DecodeAndScoreTests(unittest.TestCase):
    def tx(self, wallet="W", sol_change=-1.0, token_change=500.0, mint="M", extra=None, err=None):
        pre, post = [{"owner": wallet, "mint": mint, "uiTokenAmount": {"uiAmountString": "100"}}], \
            [{"owner": wallet, "mint": mint,
              "uiTokenAmount": {"uiAmountString": str(100 + token_change)}}]
        for m, change in (extra or {}).items():
            pre.append({"owner": wallet, "mint": m, "uiTokenAmount": {"uiAmountString": "10"}})
            post.append({"owner": wallet, "mint": m,
                         "uiTokenAmount": {"uiAmountString": str(10 + change)}})
        return {"blockTime": 1000,
                "transaction": {"message": {"accountKeys": [{"pubkey": "payer"},
                                                            {"pubkey": wallet}]}},
                "meta": {"err": err, "preBalances": [0, 5 * 10**9],
                         "postBalances": [0, int((5 + sol_change) * 10**9)],
                         "preTokenBalances": pre, "postTokenBalances": post}}

    def test_decode(self):
        buy = decode_swaps(self.tx(), "W")
        self.assertEqual(buy, [{"mint": "M", "side": "buy", "tokens": 500.0, "sol": 1.0,
                                "time": 1000}])
        sell = decode_swaps(self.tx(sol_change=2.0, token_change=-100.0), "W")
        self.assertEqual((sell[0]["side"], sell[0]["sol"]), ("sell", 2.0))
        # paid in wrapped SOL instead of SOL
        wsol = "So11111111111111111111111111111111111111112"
        self.assertEqual(decode_swaps(self.tx(sol_change=0, extra={wsol: -1.5}), "W")[0]["sol"], 1.5)
        usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        self.assertEqual(decode_swaps(self.tx(extra={usdc: -5}), "W"), [])     # stablecoin
        self.assertEqual(decode_swaps(self.tx(extra={"OTHER": 3}), "W"), [])   # two tokens
        self.assertEqual(decode_swaps(self.tx(sol_change=0.5), "W"), [])       # airdrop-ish
        self.assertEqual(decode_swaps(self.tx(err={"x": 1}), "W"), [])         # failed tx
        self.assertEqual(decode_swaps(self.tx(), "SOMEONE_ELSE"), [])
        self.assertEqual(decode_swaps(None, "W"), [])

    def test_score(self):
        swaps = [
            {"mint": "A", "side": "buy", "tokens": 100, "sol": 1.0, "time": 1},
            {"mint": "A", "side": "buy", "tokens": 100, "sol": 3.0, "time": 2},   # avg 0.02/token
            {"mint": "A", "side": "sell", "tokens": 50, "sol": 2.0, "time": 3},   # +1.0
            {"mint": "B", "side": "sell", "tokens": 10, "sol": 9.0, "time": 4},   # no cost: ignored
            {"mint": "C", "side": "buy", "tokens": 10, "sol": 1.0, "time": 5},
            {"mint": "C", "side": "sell", "tokens": 20, "sol": 0.4, "time": 6},   # only 10 held: -0.8
        ]
        s = score_trader(swaps)
        self.assertEqual((s["closed"], s["wins"]), (2, 1))
        self.assertAlmostEqual(s["realized_sol"], 0.2)
        self.assertEqual(s["top_share"], 100.0)

    def test_qualifies(self):
        good = {"closed": 6, "realized_sol": 4.5, "win_rate": 83.0, "top_share": 22.0}
        self.assertTrue(qualifies(good, C)[0])
        for change in ({"too_active": True}, {"closed": 2}, {"realized_sol": 0.5},
                       {"win_rate": 20.0}, {"top_share": 90.0}):
            self.assertFalse(qualifies(dict(good, **change), C)[0], change)


class CreditMeterTests(unittest.TestCase):
    def test_cycle_start(self):
        t = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        self.assertEqual(cycle_start(t, 15).date().isoformat(), "2026-10-15")
        self.assertEqual(cycle_start(t, 25).date().isoformat(), "2026-09-25")
        jan = datetime(2027, 1, 3, tzinfo=timezone.utc)
        self.assertEqual(cycle_start(jan, 10).date().isoformat(), "2026-12-10")

    def test_spend_pause_and_reset(self):
        c = dict(C, helius_monthly_credits=1000, pause_at_pct=80, helius_cycle_day=1)
        state = {}
        t = datetime(2026, 10, 5, tzinfo=timezone.utc)
        meter = CreditMeter(state, c, t)
        self.assertEqual(meter.cap, 800)
        for _ in range(80):
            meter.spend(10)
        with self.assertRaises(BudgetPaused):
            meter.spend(10)
        state["helius"] = meter.export()
        self.assertEqual(state["helius"]["by_day"], {"2026-10-05": 800})
        same = CreditMeter(state, c, t + timedelta(days=3))
        self.assertEqual(same.used, 800)
        fresh = CreditMeter(state, c, datetime(2026, 11, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(fresh.used, 0)


class RpcSecretTests(unittest.TestCase):
    def test_api_key_never_in_errors(self):
        rpc = Rpc("https://mainnet.helius-rpc.com/?api-key=SECRET123", "Helius")
        import requests
        cases = [
            mock.Mock(side_effect=requests.ConnectionError("https://x/?api-key=SECRET123 failed")),
            mock.Mock(return_value=mock.Mock(status_code=500)),
            mock.Mock(return_value=mock.Mock(status_code=429)),
            mock.Mock(return_value=mock.Mock(status_code=200, json=lambda: {
                "error": {"message": "bad request"}})),
        ]
        for post in cases:
            with mock.patch("screener.convergence.requests.post", post):
                with self.assertRaises(ApiError) as caught:
                    rpc.call("getTransaction", ["sig"])
            self.assertNotIn("SECRET123", str(caught.exception))
            self.assertNotIn("SECRET123", repr(caught.exception.__cause__))

    def test_credits_counted_before_each_call(self):
        meter = CreditMeter({}, dict(C, helius_monthly_credits=100, pause_at_pct=10), now_utc())
        rpc = Rpc("https://example.invalid", "Helius", meter, 10)
        with mock.patch("screener.convergence.requests.post",
                        return_value=mock.Mock(status_code=200, json=lambda: {"result": []})):
            rpc.signatures("W", 5)
            with self.assertRaises(BudgetPaused):
                rpc.signatures("W", 5)
        self.assertEqual(meter.used, 10)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "convergence")
        self.live = {}
        self.history = demo_trader_history()

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, cfg=FAST, api=None, now=None, factory=None):
        strategy = ConvergenceStrategy(cfg, self.tmp.name,
                                       rpc_factory=factory or demo_rpc_factory(self.history,
                                                                               self.live))
        lines = []
        plan = strategy.fetch(api or DemoApi(), now=now)
        strategy.apply(plan, lines.append)
        return strategy, plan, lines

    def state(self):
        with open(os.path.join(self.folder, "positions.json")) as fh:
            return json.load(fh)

    def buy(self, wallet, minutes_ago, mint=EARLY_GOOD, side="buy"):
        when = now_utc() - timedelta(minutes=minutes_ago)
        self.live.setdefault(wallet, []).append(_swap(mint, side, 0.5, 100.0, when))

    def build_list(self):
        self.go()                                  # weekly list: whale, h0, h1
        self.assertEqual(sorted(w["wallet"] for w in self.state()["tracked"]), sorted(TRACKED))
        self.go()                                  # first look at each wallet

    def test_three_wallets_converge_then_smart_money_exit(self):
        self.build_list()
        for wallet, ago in zip(TRACKED, (15, 9, 3)):
            self.buy(wallet, ago)
        strategy, plan, _ = self.go()
        (pos,) = strategy.trader.open_positions
        self.assertEqual(pos["address"], EARLY_GOOD)
        self.assertEqual(sorted(pos["wallets"]), sorted(TRACKED))
        self.assertEqual(pos["cost_usd"], 5)
        # one seller isn't enough...
        self.buy("whale", 1, side="sell")
        strategy, _, _ = self.go()
        self.assertEqual(len(strategy.trader.open_positions), 1)
        # ...two are
        self.buy("h0", 0, side="sell")
        strategy, _, lines = self.go()
        self.assertFalse(strategy.trader.open_positions)
        self.assertTrue(any("smart money exit: 2 of the buyers sold" in line for line in lines))

    def test_no_signal_without_real_convergence(self):
        self.build_list()
        self.buy("whale", 10)
        self.buy("h0", 5)                          # only 2 wallets
        strategy, plan, _ = self.go()
        self.assertEqual(plan["signals"], [])
        self.buy("h1", 45, mint="SPREAD")          # 3 wallets, but 40 min apart
        self.buy("whale", 5, mint="SPREAD")
        self.buy("h0", 4, mint="SPREAD")
        strategy, plan, _ = self.go()
        self.assertEqual(plan["signals"], [])

    def test_old_convergence_is_not_bought(self):
        self.build_list()
        for wallet, ago in zip(TRACKED, (40, 35, 30)):   # converged, but 30 min ago
            self.buy(wallet, ago)
        _, plan, _ = self.go()
        self.assertEqual(plan["signals"], [])

    def test_pauses_before_passing_the_limit(self):
        # 80% of 1,000 = 800 credits: enough to build the list (460) and a few
        # live checks (30 each), then it must pause instead of going over.
        small = with_conv(helius_monthly_credits=1_000, max_tx_per_candidate=20,
                          refresh_credits_per_run=500)
        # The last day of the cycle: the whole rest is today's share.
        end = next_cycle_start(cycle_start(now_utc(), C["helius_cycle_day"]))
        last_day = end - timedelta(hours=12)
        self.history = demo_trader_history(last_day)
        for _ in range(6):  # the refresh is spread over runs: 2 wallets per run here
            self.go(small, now=last_day)
        self.assertEqual(len(self.state()["tracked"]), 3)
        for _ in range(15):
            self.go(small, now=last_day)
        state = self.state()
        self.assertLessEqual(state["helius"]["used"], 800)
        self.assertGreater(state["helius"]["used"], 700)
        self.assertIn("paused_until", state)
        _, _, lines = self.go(small, now=last_day)
        self.assertTrue(any("PAUSED" in line for line in lines))
        # the next cycle resumes
        later = datetime.fromisoformat(state["paused_until"]) + timedelta(hours=1)
        _, plan, _ = self.go(small, now=later)
        self.assertIsNone(plan["paused"])
        self.assertNotIn("paused_until", self.state())

    def test_positions_managed_while_paused(self):
        self.build_list()
        for wallet, ago in zip(TRACKED, (15, 9, 3)):
            self.buy(wallet, ago)
        self.go()
        tiny = with_conv(helius_monthly_credits=1)         # nothing left: paused
        strategy, plan, _ = self.go(tiny, api=DemoApi({EARLY_GOOD: 0.5}))
        self.assertTrue(plan["paused"])
        self.assertFalse(strategy.trader.open_positions)   # -50%: hard stop still fired

    def test_credits_saved_when_entry_checks_fail(self):
        class RugCheckLimited(DemoApi):
            def rugcheck_report(self, address):
                if address == EARLY_GOOD:
                    raise RateLimited("RugCheck kept saying 'too many requests'")
                return super().rugcheck_report(address)

        self.build_list()
        before = self.state()["helius"]["used"]
        for wallet, ago in zip(TRACKED, (15, 9, 3)):
            self.buy(wallet, ago)
        _, plan, lines = self.go(api=RugCheckLimited())
        self.assertGreater(self.state()["helius"]["used"], before)
        self.assertTrue(any("entry checks failed" in line for line in lines))

    def test_without_key_nothing_is_spent(self):
        strategy = ConvergenceStrategy(FAST, self.tmp.name)      # no key, no fake
        plan = strategy.fetch(DemoApi())
        strategy.apply(plan, **QUIET)
        self.assertTrue(any("HELIUS_API_KEY" in n for n in plan["notes"]))
        self.assertNotIn("helius", self.state())

    def test_refresh_waits_to_keep_credits_for_live_checks(self):
        self.build_list()
        state = self.state()
        state["list_updated"] = (now_utc() - timedelta(days=8)).isoformat()   # refresh due
        state["helius"]["used"] = state["helius"]["cap"] - 1_000  # less than one refresh slice
        with open(os.path.join(self.folder, "positions.json"), "w") as fh:
            json.dump(state, fh)
        _, plan, _ = self.go()
        self.assertTrue(any("refresh waiting" in n for n in plan["notes"]))


class RunTogetherTests(unittest.TestCase):
    def test_run_includes_convergence_and_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            lines = []
            run(DemoApi(), CFG, d, out=lines.append, rpc_factory=demo_rpc_factory())
            self.assertTrue(any(line.startswith("STEP 6") for line in lines))
            day = now_utc().date().isoformat()
            text = "\n".join(helius_lines(os.path.join(d, "convergence"), day))
            self.assertIn("| Status | active |", text)
            self.assertIn("| Wallets tracked | 3 |", text)
            self.assertIn("80%", text)

    def test_rpc_error_does_not_stop_other_strategies(self):
        class Broken(DemoRpc):
            def signatures(self, *a, **k):
                raise ApiError("Helius getSignaturesForAddress: error 503")

        def factory(meter):
            rpc = Broken(meter)
            return rpc, rpc

        with tempfile.TemporaryDirectory() as d:
            results = run(DemoApi(), CFG, d, out=lambda *a: None, rpc_factory=factory)
            self.assertEqual(sorted(r.symbol for r in results if r.passed), ["FRENS", "GOODCAT"])


if __name__ == "__main__":
    unittest.main()
