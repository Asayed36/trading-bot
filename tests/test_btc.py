"""Checks for Bitcoin's trend in entries.csv (screener/btc.py), with made-up
CoinGecko answers. Run with:  python -m unittest -v
"""

import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

from screener.btc import BtcTrend, trend  # noqa: E402
from screener.paper_trader import BTC_COLUMNS, JOURNAL_COLUMNS, PaperTrader  # noqa: E402
from screener.settings import load_config  # noqa: E402

CFG = running(load_config())
NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone.utc)


def daily(closes, now=NOW):
    """CoinGecko's daily points: one at 00:00 UTC per day, then "now"."""
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(
        days=len(closes) - 1)
    points = [[(start + timedelta(days=i)).timestamp() * 1000, c] for i, c in enumerate(closes)]
    return points + [[now.timestamp() * 1000, 999_999.0]]       # "now": not a close


class Resp:
    def __init__(self, status, prices=None):
        self.status_code, self.prices = status, prices

    def json(self):
        return {"prices": self.prices}


class TrendTests(unittest.TestCase):
    def test_above_and_below_the_200_day_average(self):
        closes = [50_000.0] * 193 + [60_000.0] * 6 + [70_000.0]
        self.assertEqual(trend(daily(closes)), {
            "btc_close_usd": 70_000.0, "btc_200d_avg_usd": 50_400.0, "btc_vs_200d": "above",
            "btc_7d_change_pct": 40.0})                     # 70,000 vs 50,000 a week before
        closes = [80_000.0] * 199 + [60_000.0]
        values = trend(daily(closes))
        self.assertEqual((values["btc_vs_200d"], values["btc_7d_change_pct"]), ("below", -25.0))

    def test_too_little_history(self):
        values = trend(daily([100.0] * 50 + [110.0]))
        self.assertEqual(values, {"btc_close_usd": 110.0, "btc_7d_change_pct": 10.0})
        self.assertEqual(trend(daily([100.0] * 5)), {})
        self.assertEqual(trend(None), {})


class BtcTrendTests(unittest.TestCase):
    def test_once_a_day_and_a_retry_after_a_failure(self):
        calls, answers = [], [Resp(502), Resp(200, daily([100.0] * 200))]
        now = [NOW]

        def get(url, params, headers, timeout):
            calls.append((url, params, headers))
            return answers.pop(0)

        btc = BtcTrend(key="k", get=get, clock=lambda: now[0])
        self.assertEqual(btc(), {})                              # CoinGecko failed
        now[0] += timedelta(minutes=10)
        self.assertEqual(btc(), {})                              # not asked again yet
        now[0] += timedelta(minutes=25)
        self.assertEqual(btc()["btc_vs_200d"], "below")          # equal to the average
        now[0] += timedelta(hours=5)
        btc()                                                    # the same day: no request
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], {"vs_currency": "usd", "days": 210, "interval": "daily"})
        self.assertEqual(calls[0][2], {"x-cg-demo-api-key": "k"})

    def test_never_raises(self):
        def down(*a, **k):
            import requests
            raise requests.ConnectionError("no network")
        self.assertEqual(BtcTrend(key="", get=down, clock=lambda: NOW)(), {})


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, PaperTrader, "market", None)

    def buy(self, folder):
        trader = PaperTrader(CFG["paper_trading"], os.path.join(self.tmp.name, folder))
        pair = {"priceUsd": "2.0", "pairAddress": "p"}
        trader.buy(SimpleNamespace(address="X", symbol="X", price=2.0, pair=pair, insider=None),
                   when=NOW)
        with open(trader.entries_path) as fh:
            return list(csv.DictReader(fh))[0]

    def test_every_buy_records_bitcoins_trend(self):
        PaperTrader.market = lambda: {"btc_close_usd": 70_000.0, "btc_200d_avg_usd": 50_000.0,
                                      "btc_vs_200d": "above", "btc_7d_change_pct": 3.5}
        row = self.buy("a")
        self.assertEqual([row[k] for k in BTC_COLUMNS], ["70000.0", "50000.0", "above", "3.5"])

    def test_blank_when_unknown_or_broken(self):
        self.assertEqual([self.buy("none")[k] for k in BTC_COLUMNS], ["", "", "", ""])

        def broken():
            raise RuntimeError("bug")
        PaperTrader.market = broken
        self.assertEqual([self.buy("broken")[k] for k in BTC_COLUMNS], ["", "", "", ""])


class OldJournalTests(unittest.TestCase):
    def test_an_older_journal_gets_the_new_columns(self):
        with tempfile.TemporaryDirectory() as d:
            old = JOURNAL_COLUMNS[:-2]
            with open(os.path.join(d, "journal.csv"), "w") as fh:
                fh.write(",".join(old) + "\n2026-10-01 00:00:00,BUY,OLD,o,passed all filters,"
                         "1,10.00,0.00,0.0,0.00\n")
            trader = PaperTrader(CFG["paper_trading"], d)
            trader.buy(SimpleNamespace(address="N", symbol="N", price=1.0, pair=None,
                                       insider=None), when=NOW, source="DexScreener",
                       fetched_at=NOW - timedelta(seconds=3))
            with open(trader.journal_path) as fh:
                rows = list(csv.DictReader(fh))
        self.assertEqual(list(rows[0]), JOURNAL_COLUMNS)
        self.assertEqual((rows[0]["symbol"], rows[0]["price_source"]), ("OLD", ""))
        self.assertEqual((rows[1]["price_source"], rows[1]["price_time_utc"]),
                         ("DexScreener", "2026-10-09 14:29:57"))


if __name__ == "__main__":
    unittest.main()


class ActivityTests(unittest.TestCase):
    """DexScreener's 5-minute buys/sells and 5-minute/1-hour volume, from the
    same answer as the price (2026-10-09): blank, not 0, when not given."""

    def buy(self, pair):
        with tempfile.TemporaryDirectory() as d:
            trader = PaperTrader(CFG["paper_trading"], d)
            trader.buy(SimpleNamespace(address="X", symbol="X", price=2.0, pair=pair,
                                       insider=None), when=NOW)
            with open(trader.entries_path) as fh:
                return list(csv.DictReader(fh))[0]

    def test_from_the_dexscreener_answer(self):
        row = self.buy({"priceUsd": "2.0", "txns": {"m5": {"buys": 37, "sells": 0},
                                                    "h1": {"buys": 575, "sells": 484}},
                        "volume": {"m5": 6858.65, "h1": 115817.25, "h24": 1}})
        big = self.buy({"priceUsd": "2.0", "volume": {"h1": 1234567.8}})
        self.assertEqual(big["volume_1h_usd"], "1234567.8")
        self.assertEqual([row[k] for k in ("buys_5m", "sells_5m", "volume_5m_usd",
                                           "volume_1h_usd", "buys_1h", "sells_1h")],
                         ["37", "0", "6858.65", "115817.25", "575", "484"])

    def test_blank_when_not_given(self):
        row = self.buy({"priceUsd": "2.0", "txns": {"h1": {"buys": 5, "sells": 1}}})
        self.assertEqual([row[k] for k in ("buys_5m", "sells_5m", "volume_5m_usd",
                                           "volume_1h_usd")], ["", "", "", ""])
