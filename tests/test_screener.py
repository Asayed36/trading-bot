"""Automated checks that the screener and paper trader follow the rules.
Run with:  python -m unittest -v
"""

import csv
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import load_config, run  # noqa: E402
from screener import filters  # noqa: E402
from screener.demo import GOOD, TOKENS, DemoApi  # noqa: E402
from screener.filters import FAIL, PASS, WARN, Result  # noqa: E402
from screener.paper_trader import PaperTrader, now_utc  # noqa: E402

CFG = load_config()


def status(checks, name):
    return next(c.status for c in checks if c.name.startswith(name))


class FilterTests(unittest.TestCase):
    def test_demo_run_only_buys_clean_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            results = run(DemoApi(), CFG, d, out=lambda *a: None)
        passed = sorted(r.symbol for r in results if r.passed)
        self.assertEqual(passed, ["FRENS", "GOODCAT"])  # FRENS passes with a WARN
        self.assertEqual(len(results), len(TOKENS))  # the ethereum token was ignored

    def test_insiders_are_warning_by_default_but_can_fail(self):
        pair, report = TOKENS["DEMOinsider"]
        self.assertEqual(status(filters.safety_checks(report, pair, CFG["filters"]), "Insider"), WARN)
        strict = dict(CFG["filters"], insider_networks_are_fail=True)
        self.assertEqual(status(filters.safety_checks(report, pair, strict), "Insider"), FAIL)

    def test_missing_data_fails(self):
        f = CFG["filters"]
        self.assertEqual(filters.market_checks(None, f)[0].status, FAIL)
        self.assertEqual(filters.safety_checks(None, None, f)[0].status, FAIL)
        pair = dict(TOKENS[GOOD][0], liquidity={}, marketCap=None, fdv=None)
        checks = filters.market_checks(pair, f)
        self.assertEqual(status(checks, "Liquidity"), FAIL)
        self.assertEqual(status(checks, "Market cap"), FAIL)

    def test_pool_wallet_not_counted_as_holder(self):
        pair, report = TOKENS[GOOD]
        self.assertEqual(status(filters.safety_checks(report, pair, CFG["filters"]), "Top 10"), PASS)
        keep_pools = dict(CFG["filters"], exclude_pools_from_holders=False)
        self.assertEqual(status(filters.safety_checks(report, pair, keep_pools), "Top 10"), FAIL)

    def test_creator_check_without_balance_field(self):
        pair, report = TOKENS[GOOD]
        report = dict(report, creatorBalance=None)
        # creator isn't among the holders, all of whom hold < 5%
        self.assertEqual(status(filters.safety_checks(report, pair, CFG["filters"]), "Creator"), PASS)
        report["topHolders"] = report["topHolders"] + [{"address": "x", "owner": "CREATOR", "pct": 9}]
        self.assertEqual(status(filters.safety_checks(report, pair, CFG["filters"]), "Creator"), FAIL)

    def test_prefers_allowed_dex_pool(self):
        curve = dict(TOKENS[GOOD][0], dexId="pumpfun", liquidity={"usd": 999_999})
        chosen = filters.best_pair([curve, TOKENS[GOOD][0]], GOOD, ["pumpswap", "raydium"])
        self.assertEqual(chosen["dexId"], "pumpswap")


class PaperTradingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trader = PaperTrader(CFG["paper_trading"], self.tmp.name)
        self.t0 = now_utc()
        pair = dict(TOKENS[GOOD][0], priceUsd="1.0")
        self.trader.buy(Result(GOOD, "GOODCAT", "Demo", pair), when=self.t0)

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, price, hours):
        return self.trader.update({GOOD: price}, when=self.t0 + timedelta(hours=hours))

    def journal(self):
        with open(self.trader.journal_path) as fh:
            return list(csv.DictReader(fh))

    def test_take_profit_sells_half(self):
        sells = self.at(1.5, 1)
        # half = $5 cost -> worth $7.50, minus 3% of $5 ($0.15) = +$2.35
        self.assertEqual(len(sells), 1)
        self.assertAlmostEqual(sells[0]["pnl_usd"], 2.35)
        self.assertEqual(self.trader.open_positions[0]["remaining_fraction"], 0.5)
        self.assertEqual(self.at(1.6, 2), [])  # doesn't sell half again

    def test_stop_loss(self):
        sells = self.at(0.7, 1)
        self.assertAlmostEqual(sells[0]["pnl_usd"], 7 - 10 - 0.3)
        self.assertEqual(self.trader.open_positions, [])

    def test_trailing_stop_after_peak(self):
        self.at(2.0, 1)                # take profit on half, peak = 2.0
        self.assertEqual(self.at(1.3, 2), [])   # 35% below peak: hold
        sells = self.at(1.2, 3)        # 40% below peak: sell the rest
        self.assertIn("trailing stop", sells[0]["reason"])
        self.assertAlmostEqual(sells[0]["pnl_usd"], 6 - 5 - 0.15)
        self.assertAlmostEqual(self.trader.state["running_total_pnl_usd"], 4.85 + 0.85)

    def test_time_exit_only_when_flat(self):
        self.assertEqual(self.at(1.05, 47), [])          # not 48h yet
        self.assertEqual(self.trader.update({GOOD: 1.15}, when=self.t0 + timedelta(hours=49)), [])
        sells = self.at(0.95, 50)
        self.assertIn("time exit", sells[0]["reason"])
        self.assertAlmostEqual(sells[0]["pnl_usd"], 9.5 - 10 - 0.3)

    def test_no_price_means_no_action(self):
        self.assertEqual(self.trader.update({}, when=self.t0 + timedelta(hours=100)), [])
        self.assertEqual(len(self.trader.open_positions), 1)

    def test_no_rebuy_and_journal(self):
        self.assertIsNone(self.trader.buy(Result(GOOD, "GOODCAT", "Demo", TOKENS[GOOD][0])))
        self.at(1.5, 1)
        self.at(0.8, 2)  # more than 40% below the 1.5 peak
        rows = self.journal()
        self.assertEqual([r["action"] for r in rows], ["BUY", "SELL", "SELL"])
        # first sell +2.35, second sell $4.00 - $5 - $0.15 = -1.15, total +1.20
        self.assertEqual(rows[-1]["pnl_usd"], "-1.15")
        self.assertEqual(rows[-1]["running_total_pnl_usd"], "1.20")
        self.assertIsNone(self.trader.buy(Result(GOOD, "GOODCAT", "Demo", TOKENS[GOOD][0])))

    def test_state_survives_restart(self):
        self.trader.save()
        again = PaperTrader(CFG["paper_trading"], self.tmp.name)
        self.assertEqual(len(again.open_positions), 1)


if __name__ == "__main__":
    unittest.main()
