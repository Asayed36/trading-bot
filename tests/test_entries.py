"""Checks that every paper buy, in every strategy, saves buys vs sells over
the last hour, insider-network status and DexScreener's 5-minute and 1-hour
price change to entries.csv, without changing any trade (Jupiter's organic
score: tests/test_jupiter.py). Run with:  python -m unittest -v
"""

import copy
import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import load_config, run  # noqa: E402
from screener.convergence import ConvergenceStrategy  # noqa: E402
from screener.demo import EARLY_GOOD, GOOD, TOKENS, DemoApi, demo_rpc_factory  # noqa: E402
from screener.filters import Result, insider_status  # noqa: E402
from screener.paper_trader import ENTRY_COLUMNS, PaperTrader, now_utc  # noqa: E402

CFG = load_config()
QUIET = dict(out=lambda *a: None)


def rows(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class HourlyTxnsApi(DemoApi):
    """Demo data plus last-hour trade counts for the main demo tokens."""

    def pairs_for_tokens(self, addresses):
        pairs = super().pairs_for_tokens(addresses)
        for p in pairs:
            if p["baseToken"]["address"] in TOKENS:
                p["txns"]["h1"] = {"buys": 120, "sells": 45}
                p["priceChange"].update(m5=3.5, h1=-12)
        return pairs


class EntryRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_main_and_early_buys_are_recorded(self):
        run(HourlyTxnsApi(), CFG, self.d, **QUIET)
        main = {r["symbol"]: r for r in rows(os.path.join(self.d, "entries.csv"))}
        self.assertEqual(list(main["GOODCAT"].keys()), ENTRY_COLUMNS)
        self.assertEqual((main["GOODCAT"]["buys_1h"], main["GOODCAT"]["sells_1h"]), ("120", "45"))
        self.assertEqual(main["GOODCAT"]["insider_flagged"], "no")
        frens = main["FRENS"]  # the demo token with an insider network (a WARN, still bought)
        self.assertEqual((frens["insider_flagged"], frens["insider_networks"],
                          frens["insider_linked_wallets"], frens["insider_top_holders"]),
                         ("yes", "1", "7", "0"))
        self.assertEqual(frens["token_address"], "DEMOinsider")
        self.assertEqual(frens["price_usd"], "0.002")
        (pully,) = rows(os.path.join(self.d, "early", "entries.csv"))
        self.assertEqual((pully["symbol"], pully["buys_1h"], pully["sells_1h"],
                          pully["insider_flagged"]), ("PULLY", "400", "300", "no"))

    def test_price_change_at_entry_is_recorded(self):
        run(HourlyTxnsApi(), CFG, self.d, **QUIET)
        main = {r["symbol"]: r for r in rows(os.path.join(self.d, "entries.csv"))}
        self.assertEqual((main["GOODCAT"]["price_change_5m_pct"],
                          main["GOODCAT"]["price_change_1h_pct"]), ("3.5", "-12"))
        (pully,) = rows(os.path.join(self.d, "early", "entries.csv"))
        self.assertEqual((pully["price_change_5m_pct"], pully["price_change_1h_pct"]),
                         ("2", "-30"))

    def test_old_file_gets_the_new_columns(self):
        """An entries.csv saved before the price-change columns existed is
        upgraded in place: old rows kept, new columns blank for them."""
        old_columns = ENTRY_COLUMNS[:10]
        path = os.path.join(self.d, "entries.csv")
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(old_columns)
            w.writerow(["2026-10-01 00:52:07", "OLD", "OLDaddr", "0.0001", "10", "5",
                        "no", "0", "0", "0"])
        trader = PaperTrader(CFG["paper_trading"], self.d)
        trader.buy(Result("NEW", "NEW", "NEW", {"priceUsd": "1.5",
                                                 "priceChange": {"m5": 7.25, "h1": 40}}))
        old, new = rows(path)
        self.assertEqual(list(old.keys()), ENTRY_COLUMNS)
        self.assertEqual((old["symbol"], old["buys_1h"], old["price_change_5m_pct"]),
                         ("OLD", "10", ""))
        self.assertEqual((new["symbol"], new["price_change_5m_pct"],
                          new["price_change_1h_pct"]), ("NEW", "7.25", "40"))

    def test_one_row_per_buy_and_rows_are_kept(self):
        run(HourlyTxnsApi(), CFG, self.d, **QUIET)
        run(HourlyTxnsApi(), CFG, self.d, **QUIET)                 # no new buys
        self.assertEqual(len(rows(os.path.join(self.d, "entries.csv"))), 2)
        run(HourlyTxnsApi({GOOD: 0.5}), CFG, self.d, **QUIET)      # GOODCAT stopped out
        entries = rows(os.path.join(self.d, "entries.csv"))
        self.assertEqual(sorted(r["symbol"] for r in entries), ["FRENS", "GOODCAT"])

    def test_missing_data_is_blank_or_unknown(self):
        trader = PaperTrader(CFG["paper_trading"], self.d)
        trader.buy(Result("X", "X", "X", {"priceUsd": "1.5"}))    # no txns, no report
        (row,) = rows(os.path.join(self.d, "entries.csv"))
        self.assertEqual((row["buys_1h"], row["sells_1h"], row["insider_flagged"],
                          row["insider_networks"], row["price_change_5m_pct"],
                          row["price_change_1h_pct"]), ("", "", "unknown", "", "", ""))
        self.assertIsNone(insider_status(None))

    def test_convergence_buys_are_recorded(self):
        cfg = dict(CFG, convergence=dict(CFG["convergence"], helius_every_minutes=2))
        live, t0 = {}, now_utc()

        def go(minutes):
            s = ConvergenceStrategy(cfg, self.d, rpc_factory=demo_rpc_factory(live=live))
            s.apply(s.fetch(DemoApi(), now=t0 + timedelta(minutes=minutes)), **QUIET)

        go(0)
        go(1)
        for wallet, ago in (("whale", 9), ("h0", 6), ("h1", 3)):
            when = t0 + timedelta(minutes=2 - ago)
            live.setdefault(wallet, []).append({"mint": EARLY_GOOD, "side": "buy", "sol": 0.5,
                                                "tokens": 100.0, "time": int(when.timestamp())})
        go(2)
        (row,) = rows(os.path.join(self.d, "convergence", "entries.csv"))
        self.assertEqual((row["token_address"], row["buys_1h"], row["sells_1h"],
                          row["insider_flagged"], row["price_change_5m_pct"],
                          row["price_change_1h_pct"]), (EARLY_GOOD, "400", "300", "no", "2", "-30"))

    def test_trades_are_unchanged(self):
        """Same demo run with and without the entry record: identical trades."""
        run(HourlyTxnsApi(), CFG, self.d, **QUIET)
        with tempfile.TemporaryDirectory() as other:
            original = PaperTrader._entry
            PaperTrader._entry = lambda *a, **k: None   # as before this change
            try:
                run(HourlyTxnsApi(), CFG, other, **QUIET)
            finally:
                PaperTrader._entry = original
            for sub in ("", "early"):
                a = os.path.join(self.d, sub, "positions.json")
                b = os.path.join(other, sub, "positions.json")
                with open(a) as fa, open(b) as fb:
                    pa, pb = json.load(fa)["open_positions"], json.load(fb)["open_positions"]
                clean = [copy.deepcopy(p) for p in (pa, pb)]
                for side in clean:
                    for p in side:
                        p.pop("entry_time", None)
                        (p.get("issue_details") or {}).pop("passed_at", None)
                self.assertEqual(clean[0], clean[1], sub or "main")
                self.assertFalse(os.path.exists(os.path.join(other, sub, "entries.csv")))


if __name__ == "__main__":
    unittest.main()
