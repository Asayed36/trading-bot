"""Checks for the calibrated Helius credit counting, the transaction-version
fix, and that one unreadable transaction or wallet can't stall the strategy.
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

from run import load_config  # noqa: E402
from screener.api import RateLimited  # noqa: E402
from screener.convergence import (ConvergenceStrategy, CreditMeter, Rpc,  # noqa: E402
                                  RpcError, read_transaction)
from screener.demo import DemoApi, DemoRpc, demo_rpc_factory, demo_trader_history  # noqa: E402

CFG = running(load_config())
C = CFG["convergence"]
QUIET = dict(out=lambda *a: None)
VERSION_ERROR = ("Transaction version (1) is not supported by the requesting client. Please "
                 "try the request again with the following configuration parameter: "
                 "\"maxSupportedTransactionVersion\": 1")


def reply(result=None, error=None):
    body = {"jsonrpc": "2.0", "id": 1}
    body.update({"error": {"code": -32015, "message": error}} if error else {"result": result})
    return mock.Mock(status_code=200, json=lambda: body)


class TransactionVersionTests(unittest.TestCase):
    def test_retries_with_the_version_helius_asks_for(self):
        meter = CreditMeter({}, C, datetime.now(timezone.utc))
        rpc = Rpc("https://example.invalid/?api-key=K", "Helius", meter, 4)
        with mock.patch("screener.convergence.requests.post",
                        side_effect=[reply(error=VERSION_ERROR), reply({"ok": 1}),
                                     reply({"ok": 2})]) as post:
            self.assertEqual(rpc.transaction("sig1"), {"ok": 1})
            self.assertEqual(rpc.transaction("sig2"), {"ok": 2})   # remembers version 1
        versions = [c.kwargs["json"]["params"][1]["maxSupportedTransactionVersion"]
                    for c in post.call_args_list]
        self.assertEqual(versions, [0, 1, 1])
        self.assertEqual(meter.used, 3 * 4)                          # every call counted

    def test_other_errors_still_raise(self):
        rpc = Rpc("https://example.invalid", "Helius")
        with mock.patch("screener.convergence.requests.post",
                        return_value=reply(error="Transaction not found")):
            with self.assertRaises(RpcError):
                rpc.transaction("sig")

    def test_unreadable_transaction_is_skipped(self):
        class Broken:
            def transaction(self, sig):
                raise RpcError("Helius getTransaction: nope", "nope")

        plan = {}
        self.assertIsNone(read_transaction(Broken(), "sig", plan))
        self.assertIsNone(read_transaction(Broken(), "sig", plan))
        self.assertEqual(plan["unreadable"], 2)

        class Limited:
            def transaction(self, sig):
                raise RateLimited("429")

        with self.assertRaises(RateLimited):
            read_transaction(Limited(), "sig", {})


class StuckWalletTests(unittest.TestCase):
    def test_bad_wallet_and_bad_transaction_dont_block_the_list(self):
        class Flaky(DemoRpc):
            def signatures(self, wallet, limit, until=None):
                if wallet == "h2":                       # this wallet can't be read at all
                    self._spend()
                    raise RpcError("Helius getSignaturesForAddress: boom", "boom")
                return super().signatures(wallet, limit, until)

            def transaction(self, signature):
                if signature == "whale-3":               # one unreadable transaction
                    self._spend()
                    raise RpcError("Helius getTransaction: v1", VERSION_ERROR + "9")
                return super().transaction(signature)

        def factory(meter):
            rpc = Flaky(meter, demo_trader_history())
            return rpc, rpc

        cfg = dict(CFG, convergence=dict(C, helius_every_minutes=2))
        with tempfile.TemporaryDirectory() as d:
            s = ConvergenceStrategy(cfg, d, rpc_factory=factory)
            plan = s.fetch(DemoApi())
            s.apply(plan, **QUIET)
            with open(os.path.join(d, "convergence", "positions.json")) as fh:
                state = json.load(fh)
        self.assertEqual(sorted(w["wallet"] for w in state["tracked"]), ["h0", "h1", "whale"])
        self.assertNotIn("refresh", state)                     # the list was finished
        self.assertTrue(any("skipped 1 transaction" in n for n in plan["notes"]))


class CalibrationTests(unittest.TestCase):
    def test_old_count_is_rescaled_once(self):
        now = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
        state = {"helius": {"cycle_start": "2026-09-28T00:00:00+00:00", "used": 6430,
                            "by_day": {"2026-09-30": 6270, "2026-10-01": 160}}}
        meter = CreditMeter(state, C, now)
        self.assertEqual(meter.used, 2572)                       # 6430 x 4/10
        self.assertEqual(meter.meter["by_day"], {"2026-09-30": 2508, "2026-10-01": 64})
        state["helius"] = meter.export()
        self.assertEqual(CreditMeter(state, C, now).used, 2572)  # not scaled again
        lower = dict(C, helius_history_credits_per_call=3)
        self.assertEqual(CreditMeter(state, lower, now).used, 1929)  # x 3/4

    def test_live_and_history_calls_counted_at_their_rates(self):
        s = ConvergenceStrategy(CFG, tempfile.gettempdir(), api_key="K")
        history, live = s._rpcs(CreditMeter({}, C, datetime.now(timezone.utc)))
        self.assertEqual((history.per_call, live.per_call), (4, 2))
        self.assertIsNot(history, live)

    def test_config_fits_under_the_pause_with_50_wallets(self):
        self.assertEqual(C["tracked_wallets"], 50)
        checks = 30 * 24 * 60 / C["helius_every_minutes"]       # live checks a month
        decodes_per_wallet_day = 20                              # generous: bots are excluded
        live = C["tracked_wallets"] * C["helius_live_credits_per_call"] * (
            checks + decodes_per_wallet_day * 30)
        cap = C["helius_monthly_credits"] * C["pause_at_pct"] / 100
        # Live checks of a full list leave over a third of the allowance for
        # scoring candidates (which only ever gets what's left, see below).
        self.assertLess(live / cap, 0.65)

    def test_scoring_gets_at_most_a_days_share_of_whats_left(self):
        """Three days of runs every 15 minutes, with candidates that never
        run out: scoring stays within an even daily share of what the live
        checks leave, so the month stays under the pause limit."""
        now = datetime(2026, 9, 28, 0, 5, tzinfo=timezone.utc)
        cfg = dict(CFG, convergence=dict(C, helius_every_minutes=15, sellers_per_winner=5000,
                                         candidates_per_refresh=5000))
        trader = demo_trader_history(now)["whale"]                 # 12 swaps, profitable
        endless = {f"w{i}": trader for i in range(5000)}

        class Api(DemoApi):
            def gecko_pool_trades(self, pool):
                return [{"tx_from_address": w, "kind": "sell", "volume_in_usd": "100"}
                        for w in endless]

        with tempfile.TemporaryDirectory() as d:
            by_day = {}
            for day in range(3):
                for run in range(96):
                    t = now + timedelta(days=day, minutes=15 * run)
                    s = ConvergenceStrategy(cfg, d, rpc_factory=demo_rpc_factory(endless, {}))
                    s.apply(s.fetch(Api(), now=t), **QUIET)
                with open(os.path.join(d, "convergence", "positions.json")) as fh:
                    state = json.load(fh)
                by_day = state["refresh_spent"]
            cap = state["helius"]["cap"]
        # A day's share of what's left after keeping the live checks of the
        # (soon full) list until the cycle ends.
        reserve = 50 * C["helius_live_credits_per_call"] * 1.5 * 30 * 96
        self.assertEqual(len(by_day), 3)
        for day, spent in by_day.items():
            self.assertLess(spent, cap / 30, day)                       # never more
            # and it does use it (the demo charges 10 a live call, so less is left)
            self.assertGreater(spent, (cap - reserve) / 30 * 0.5, day)
        self.assertEqual(len(state["tracked"]), 50)             # the list filled up
        self.assertLess(state["helius"]["used"], cap)

if __name__ == "__main__":
    unittest.main()
