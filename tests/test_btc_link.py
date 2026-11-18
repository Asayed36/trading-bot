"""Checks for lab/btc_link.py (which coins follow Bitcoin least), with fake price data only:
nothing here reaches Binance."""

import csv
import math
import os
import random
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "lab"))
sys.path.insert(0, HERE)

import btc_link as bl  # noqa: E402

START = date(2025, 11, 17)


def series_from(returns, start=START, first_close=100.0):
    """{day: close} from a list of daily returns (the first day has no return)."""
    closes, c = {start.isoformat(): first_close}, first_close
    for i, r in enumerate(returns, 1):
        c *= 1 + r
        closes[(start + timedelta(days=i)).isoformat()] = c
    return closes


def btc_returns(n=364, seed=7):
    rnd = random.Random(seed)
    out = [rnd.gauss(0, 0.02) for _ in range(n)]
    out[10], out[50], out[100] = -0.05, -0.04, 0.06            # big BTC days
    return out


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.br = btc_returns()
        self.btc = series_from(self.br)

    def test_a_copy_of_btc_has_correlation_and_beta_1(self):
        m = bl.measure(series_from(self.br), self.btc)
        self.assertAlmostEqual(m["corr_1y"], 1.0, places=9)
        self.assertAlmostEqual(m["beta_1y"], 1.0, places=9)
        self.assertAlmostEqual(m["corr_90d"], 1.0, places=9)

    def test_twice_the_moves_has_beta_2(self):
        m = bl.measure(series_from([2 * r for r in self.br]), self.btc)
        self.assertAlmostEqual(m["beta_1y"], 2.0, places=9)
        self.assertAlmostEqual(m["corr_1y"], 1.0, places=9)

    def test_the_opposite_moves_have_correlation_minus_1(self):
        m = bl.measure(series_from([-r for r in self.br]), self.btc)
        self.assertAlmostEqual(m["corr_1y"], -1.0, places=9)
        self.assertAlmostEqual(m["beta_1y"], -1.0, places=9)

    def test_independent_moves_have_a_low_correlation(self):
        rnd = random.Random(99)
        m = bl.measure(series_from([rnd.gauss(0, 0.03) for _ in self.br]), self.btc)
        self.assertLess(abs(m["corr_1y"]), 0.15)

    def test_the_90_days_are_the_last_90(self):
        # moves with BTC for 274 days, then the opposite for the last 90
        coin = series_from(self.br[:-90] + [-r for r in self.br[-90:]])
        m = bl.measure(coin, self.btc)
        self.assertAlmostEqual(m["corr_90d"], -1.0, places=9)
        self.assertGreater(m["corr_1y"], -1.0)

    def test_big_btc_days(self):
        coin = [0.0] * len(self.br)
        coin[10], coin[50], coin[100] = 0.02, -0.01, 0.03         # rose on 1 of 2 down days
        m = bl.measure(series_from(coin), self.btc)
        down = sum(1 for r in self.br if r < -0.03)
        up = sum(1 for r in self.br if r > 0.03)
        self.assertEqual((m["btc_down_days"], m["btc_up_days"]), (down, up))
        rose = sum(1 for i, r in enumerate(self.br) if r < -0.03 and coin[i] > 0)
        self.assertEqual(m["coin_rose_on_btc_down_days"], rose)
        moves = [coin[i] for i, r in enumerate(self.br) if r < -0.03]
        self.assertAlmostEqual(m["avg_move_on_btc_down_days_pct"], sum(moves) / len(moves) * 100)

    def test_total_change_and_biggest_fall(self):
        coin = series_from([0.5, -0.5, 0.2] + [0.0] * 361)        # 100 -> 150 -> 75 -> 90
        m = bl.measure(coin, self.btc)
        self.assertAlmostEqual(m["total_change_pct"], -10.0)
        self.assertAlmostEqual(m["max_drawdown_pct"], -50.0)
        self.assertEqual(m["days"], 365)

    def test_a_short_history_keeps_only_the_90_day_figures(self):
        start = START + timedelta(days=300)
        coin = series_from(self.br[300:], start=start)               # 65 days
        m = bl.measure(coin, self.btc)
        self.assertTrue(m["short_history"])
        self.assertEqual(m["days"], 65)
        self.assertAlmostEqual(m["corr_90d"], 1.0, places=9)
        for key in ("corr_1y", "beta_1y", "btc_down_days", "total_change_pct",
                    "max_drawdown_pct", "avg_move_on_btc_down_days_pct"):
            self.assertIsNone(m[key], key)

    def test_missing_days_are_not_counted_as_one_day_moves(self):
        coin = series_from(self.br)
        gap = sorted(coin)[200]
        del coin[gap]
        self.assertNotIn(gap, bl.returns(coin))
        next_day = (date.fromisoformat(gap) + timedelta(days=1)).isoformat()
        self.assertNotIn(next_day, bl.returns(coin))

    def test_too_few_days_or_a_flat_coin_cannot_be_measured(self):
        self.assertEqual(bl.corr_beta([0.01] * 10, [0.02] * 10), (None, None))
        self.assertEqual(bl.corr_beta([0.01 * i for i in range(30)], [0.0] * 30), (None, None))


class CoinChoiceTests(unittest.TestCase):
    def test_top_by_volume_plus_the_extra_ones_listed(self):
        vols = {"ETH": 9e9, "SOL": 8e9, "USDC": 7e9, "XRP": 6e9, "BTCUP": 5e9, "FDUSD": 4e9,
                "ADA": 3e9, "QNT": 1e6, "PEPE": 2e6, "BTC": 1e12}
        chosen = bl.choose(vols, top=3, extra=["QNT", "PEPE", "NOTLISTED", "ETH"])
        self.assertEqual(chosen, ["ETH", "SOL", "XRP", "QNT", "PEPE"])

    def test_no_stablecoin_fiat_or_leveraged_token(self):
        for base in ("USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "BTCUP", "ETHDOWN",
                     "XRPBULL", "BNBBEAR", "BTC"):
            self.assertFalse(bl.wanted(base), base)
        for base in ("ETH", "PAXG", "PEPE", "UP" + "X", "JUP", "SYRUP", "CUP"):
            self.assertTrue(bl.wanted(base), base)                    # coins that end in UP

    def test_tokenized_stocks_and_wrapped_bitcoin_are_left_out(self):
        for base in ("NVDAB", "TSLAB", "SPYB", "QQQB", "TQQQB", "SOXLB", "SOXSB", "WBTC"):
            self.assertFalse(bl.wanted(base), base)
        vols = {"NVDAB": 9e9, "ETH": 1e9, "WBTC": 8e9}
        self.assertEqual(bl.choose(vols, top=2, extra=[]), ["ETH"])

    def test_a_coin_that_stays_at_one_dollar_is_a_stablecoin_whatever_its_name(self):
        self.assertTrue(bl.pegged({"2026-01-01": 0.9995, "2026-01-02": 1.0008}))
        self.assertFalse(bl.pegged({"2026-01-01": 0.99, "2026-01-02": 1.05}))
        self.assertFalse(bl.pegged({"2026-01-01": 2.0}))
        self.assertFalse(bl.pegged({}))
        for base in ("U", "RWUSD"):
            self.assertFalse(bl.wanted(base))

    def test_a_failed_download_is_tried_again_and_only_404_means_not_listed(self):
        class Resp:
            def __init__(self, code, content=b""):
                self.status_code, self.content = code, content

        import io as _io, zipfile as _zip
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as zf:
            zf.writestr("x.csv", "1763337600000,1,1,1,1,10,0,12345.5,0,0,0,0\n")
        answers = [Resp(503), Resp(200, buf.getvalue())]

        class Http:
            def get(self, *a, **k):
                return answers.pop(0)
        self.assertEqual(bl.day_volume(Http(), "JUPUSDT", "2026-11-16", sleep=lambda s: None),
                         12345.5)
        answers[:] = [Resp(404)]
        self.assertIsNone(bl.day_volume(Http(), "TONUSDT", "2026-11-16", sleep=lambda s: None))
        answers[:] = [Resp(500), Resp(500), Resp(500)]
        with self.assertRaises(RuntimeError):
            bl.day_volume(Http(), "X", "2026-11-16", sleep=lambda s: None)

    def test_memecoins_are_marked(self):
        for base in ("DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "PENGU", "TRUMP", "BOME",
                     "NEIRO", "PNUT", "MEME", "TURBO"):
            self.assertIn(base, bl.MEMECOINS)
        self.assertNotIn("QNT", bl.MEMECOINS)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        br = btc_returns()
        rnd = random.Random(3)
        series = {"BTC": series_from(br)}
        for i in range(12):                       # coins from 0.0 to 1.0 linked to BTC
            k = i / 11
            series[f"C{i:02d}"] = series_from([k * r + (1 - k) * rnd.gauss(0, 0.02) for r in br])
        series["PEPE"] = series_from([-r for r in br])                 # a memecoin, anti-BTC
        series["NEW"] = series_from(br[300:], start=START + timedelta(days=300))
        rnd2 = random.Random(5)                                         # a new $1 coin
        series["NEWUSD"] = series_from([rnd2.gauss(0, 0.0003) for _ in br], first_close=1.0)
        self.rows = bl.build(series, {"PEPE": 5e6}, "2025-11-17", "2026-11-16", self.tmp.name)

    def read(self, name):
        with open(os.path.join(self.tmp.name, name)) as fh:
            return fh.read()

    def test_the_csv_has_every_coin_and_every_number(self):
        with open(os.path.join(self.tmp.name, "btc_link.csv"), newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(list(rows[0]), bl.COLUMNS)
        self.assertEqual(len(rows), 14)
        pepe = next(r for r in rows if r["coin"] == "PEPE")
        self.assertEqual((pepe["memecoin"], pepe["rank"], pepe["avg_daily_volume_usdt"]),
                         ("yes", "1", "5000000.000"))
        self.assertAlmostEqual(float(pepe["corr_90d"]), -1.0, places=6)
        new = next(r for r in rows if r["coin"] == "NEW")
        self.assertEqual((new["short_history"], new["days"], new["corr_1y"], new["total_change_pct"]),
                         ("yes", "65", "", ""))

    def test_the_table_is_sorted_by_the_90_day_correlation_lowest_first(self):
        corrs = [r["corr_90d"] for r in self.rows]
        self.assertEqual(corrs, sorted(corrs))
        md = self.read("btc_link.md").split("## Closest to their 1-year low")[0]
        table = [line for line in md.splitlines() if line.startswith("| ") and line[2].isdigit()]
        self.assertTrue(table[0].startswith("| 1 | PEPE | yes |"))
        self.assertEqual(len(table), 14)

    def test_the_summary_names_the_ten_and_their_worst_days_and_the_survivor_note(self):
        md = self.read("btc_link.md")
        summary = md.split("**The 10 least Bitcoin-linked coins")[1].split("**Read with care")[0]
        named = [line for line in summary.splitlines() if line[:1].isdigit()]
        self.assertEqual(len(named), 10)
        self.assertIn("**PEPE** (memecoin): 90-day correlation -1.00", named[0])
        self.assertIn("days down more than 3% it rose on", named[0])
        self.assertIn("survivorship bias", md)
        self.assertIn("by their price staying at $1: NEWUSD", md)
        self.assertIn("tokenized stocks and stock funds (AAOIB, AMDB, AVGOB, BMNRB, BNCB, CBRSB", md)
        self.assertNotIn("| NEWUSD |", md)
        self.assertIn("results look better than reality", md)
        self.assertIn("Refresh: `python lab/btc_link.py`", md)

    def test_it_is_not_a_lab_idea(self):
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "history.csv")))
        with open(os.path.join(HERE, "lab", "btc_link.py")) as fh:
            source = fh.read()
        for word in ("append_history", "run_lab", "lab/rules"):
            self.assertNotIn(word, source)                           # no lab idea is counted


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------
# distance from the 1-year low and high
# ---------------------------------------------------------------------

def candles(closes, highs=None, lows=None, start=START):
    """{day: close} and {day: (high, low)} from lists (high/low default to the close +-1%)."""
    cl, hl = {}, {}
    for i, c in enumerate(closes):
        d = (start + timedelta(days=i)).isoformat()
        cl[d] = c
        hl[d] = (highs[i] if highs else c * 1.01, lows[i] if lows else c * 0.99)
    return cl, hl


class ExtremesTests(unittest.TestCase):
    def test_a_coin_closing_exactly_at_its_low(self):
        closes = [10.0] * 364 + [4.0]
        lows = [9.0] * 364 + [4.0]                                      # the last day's low = close
        cl, hl = candles(closes, highs=[12.0] * 365, lows=lows)
        e = bl.extremes(cl, hl)
        self.assertEqual((e["low_1y"], e["low_1y_date"], e["days_since_low"]),
                         (4.0, max(cl), 0))
        self.assertEqual(e["from_low_1y_pct"], 0.0)
        self.assertAlmostEqual(e["from_high_1y_pct"], (4 / 12 - 1) * 100)
        self.assertFalse(e["partial_year"])

    def test_the_lows_and_highs_are_the_daily_ones_not_the_closes(self):
        closes = [100.0] * 365
        lows = [95.0] * 365
        highs = [105.0] * 365
        lows[100], highs[200] = 50.0, 300.0
        cl, hl = candles(closes, highs, lows)
        e = bl.extremes(cl, hl)
        self.assertEqual((e["low_1y"], e["high_1y"]), (50.0, 300.0))
        self.assertEqual(e["low_1y_date"], (START + timedelta(days=100)).isoformat())
        self.assertEqual(e["high_1y_date"], (START + timedelta(days=200)).isoformat())
        self.assertAlmostEqual(e["from_low_1y_pct"], 100.0)            # 100 is 100% above 50
        self.assertAlmostEqual(e["from_high_1y_pct"], (100 / 300 - 1) * 100)
        self.assertEqual(e["days_since_low"], 264)
        self.assertEqual(e["latest_close"], 100.0)

    def test_the_latest_of_equal_lows_counts(self):
        cl, hl = candles([10.0] * 10, highs=[11.0] * 10, lows=[5, 9, 9, 5, 9, 9, 9, 9, 9, 9])
        self.assertEqual(bl.extremes(cl, hl, full_days=10)["days_since_low"], 6)

    def test_a_short_history_uses_its_days_and_is_marked(self):
        cl, hl = candles([2.0, 1.0, 1.5])
        e = bl.extremes(cl, hl)
        self.assertTrue(e["partial_year"])
        self.assertAlmostEqual(e["low_1y"], 0.99)
        self.assertAlmostEqual(e["from_low_1y_pct"], (1.5 / 0.99 - 1) * 100)

    def test_without_highs_and_lows_the_closes_are_used(self):
        cl, _ = candles([3.0, 1.0, 2.0])
        e = bl.extremes(cl)
        self.assertEqual((e["low_1y"], e["high_1y"], e["from_low_1y_pct"]), (1.0, 3.0, 100.0))


class LowSectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        br = btc_returns()
        series, hl = {"BTC": series_from(br)}, {}
        rnd = random.Random(11)
        for i in range(25):                                             # 25 coins, then 2 memes
            closes = list(series_from([rnd.gauss(0, 0.03) for _ in br]).values())
            closes[-1] = min(closes) * (1 + i / 100)                    # i% above the low close
            name = f"K{i:02d}"
            series[name], hl[name] = candles(closes, highs=[c for c in closes],
                                             lows=[c for c in closes])
        series["PEPE"], hl["PEPE"] = candles([5.0, 4.0, 2.0] + [3.0] * 362,
                                             highs=[5.0, 4.0, 2.0] + [3.0] * 362,
                                             lows=[5.0, 4.0, 2.0] + [3.0] * 362)
        series["BONK"], hl["BONK"] = candles([1.0] * 100 + [0.5],      # a short memecoin, at its low
                                             start=START + timedelta(days=264),
                                             highs=[1.0] * 100 + [0.5], lows=[1.0] * 100 + [0.5])
        self.rows = bl.build(series, {}, "2025-11-17", "2026-11-16", self.tmp.name, highs_lows=hl)
        with open(os.path.join(self.tmp.name, "btc_link.md")) as fh:
            self.md = fh.read()

    def section(self):
        return self.md.split("## Closest to their 1-year low")[1]

    def test_the_20_closest_lowest_first(self):
        closest = self.section().split("**Every memecoin:**")[0]
        rows = [x for x in closest.splitlines() if x.startswith("| ") and x[2].isdigit()]
        self.assertEqual(len(rows), 20)
        # both exactly at their low (+0.0%): equal values in name order
        self.assertTrue(rows[0].startswith("| 1 | BONK (101 days) | yes |"))
        self.assertTrue(rows[1].startswith("| 2 | K00 |  |"))
        self.assertIn("| +0.0% |", rows[0])
        self.assertIn("| +0.0% |", rows[1])
        values = [float(x.split(" | ")[5].rstrip("%")) for x in rows]
        self.assertEqual(values, sorted(values))

    def test_every_memecoin_is_listed(self):
        memes = self.section().split("**Every memecoin:**")[1]
        rows = [x for x in memes.splitlines() if x.startswith("| ") and x[2].isdigit()]
        self.assertEqual([x.split(" | ")[1] for x in rows], ["BONK (101 days)", "PEPE"])
        self.assertIn("| 2 (" + (START + timedelta(days=2)).isoformat() + ") | +50.0% |", rows[1])

    def test_the_csv_has_the_new_columns(self):
        with open(os.path.join(self.tmp.name, "btc_link.csv"), newline="") as fh:
            rows = {r["coin"]: r for r in csv.DictReader(fh)}
        for col in ("latest_close", "low_1y", "low_1y_date", "from_low_1y_pct", "high_1y",
                    "from_high_1y_pct", "days_since_low", "partial_year"):
            self.assertIn(col, rows["PEPE"])
        self.assertEqual(rows["PEPE"]["low_1y"], "2")
        with tempfile.TemporaryDirectory() as d:                       # a tiny price keeps its digits
            bl.write_csv([{"coin": "SHIB", "latest_close": 0.0000061234567, "low_1y": 5.9e-06}],
                         os.path.join(d, "x.csv"))
            with open(os.path.join(d, "x.csv"), newline="") as fh:
                shib = next(csv.DictReader(fh))
            self.assertEqual((shib["latest_close"], shib["low_1y"]), ("6.1234567e-06", "5.9e-06"))
        self.assertEqual((rows["PEPE"]["from_low_1y_pct"], rows["PEPE"]["days_since_low"],
                          rows["BONK"]["partial_year"], rows["BONK"]["from_low_1y_pct"]),
                         ("50.000", "362", "yes", "0.000"))

    def test_the_correlation_table_and_summary_are_kept(self):
        head = self.md.split("## Closest to their 1-year low")[0]
        self.assertIn("**The 10 least Bitcoin-linked coins (last 90 days):**", head)
        self.assertIn("| # | Coin | Meme | Days | Corr 90d | Corr 1y |", head)
        self.assertTrue(self.md.rstrip().endswith("(writes lab/results/btc_link.csv and this file)."))


class CacheTests(unittest.TestCase):
    def test_only_the_days_the_cache_lacks_are_downloaded(self):
        have = {d: None for d in ("2025-11-17", "2026-11-16")}
        self.assertEqual(bl.missing_ranges(have, date(2025, 11, 18), date(2026, 11, 17)),
                         [(date(2026, 11, 17), date(2026, 11, 17))])
        self.assertEqual(bl.missing_ranges({}, date(2025, 11, 18), date(2026, 11, 17)),
                         [(date(2025, 11, 18), date(2026, 11, 17))])
        self.assertEqual(bl.missing_ranges(have, date(2025, 11, 10), date(2026, 11, 16)),
                         [(date(2025, 11, 10), date(2025, 11, 16))])

    def test_earlier_runs_files_and_the_coins_own_file_are_merged(self):
        with tempfile.TemporaryDirectory() as d:
            for name, rows in (("ONE-2025-11-17-2026-11-16.csv", [("2026-11-15", 1, 2, 0.5, 1, 9),
                                                                  ("2026-11-16", 1, 2, 0.5, 1.5, 9)]),
                               ("ONE.csv", [("2026-11-17", 1, 2, 0.5, 2, 9)]),
                               ("ONEX-2025-11-17-2026-11-16.csv", [("2026-11-18", 9, 9, 9, 9, 9)])):
                with open(os.path.join(d, name), "w", newline="") as fh:
                    csv.writer(fh).writerows(rows)
            have = bl.cached(d, "ONE")
        self.assertEqual(sorted(have), ["2026-11-15", "2026-11-16", "2026-11-17"])
        self.assertEqual(have["2026-11-17"][4], 2.0)
