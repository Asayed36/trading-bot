"""Checks for the market backdrop and launch-time columns (screener/backdrop.py,
screener/token_record.py) and the timing report (screener/timing_report.py,
timing_report.py): recording and a report only, no buy or sell may change.
Run with:  python -m unittest -v
"""

import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

from run import load_config  # noqa: E402
from screener import backdrop as bd  # noqa: E402
from screener import timing_report as tre  # noqa: E402
from screener import token_record as tr  # noqa: E402
from screener.filters import Result  # noqa: E402
from screener.paper_trader import ENTRY_COLUMNS, PaperTrader  # noqa: E402

CFG = running(load_config())
NOW = datetime(2026, 10, 11, 14, 30, 0, tzinfo=timezone.utc)      # a Sunday
CREATED = NOW - timedelta(minutes=90)                              # 13:00 UTC, a Sunday
MINT = "MintAAAA"
PAIR = {"dexId": "pumpswap", "pairAddress": "P1", "priceUsd": "0.5", "marketCap": 250000,
        "liquidity": {"usd": 40000}, "pairCreatedAt": int(CREATED.timestamp() * 1000),
        "baseToken": {"address": MINT, "symbol": "AAA", "name": "Aaa"}}
COINS = [
    {"id": "bitcoin", "price_change_percentage_1h_in_currency": 0.4567,
     "price_change_percentage_24h_in_currency": -2.5},
    {"id": "ethereum", "price_change_percentage_1h_in_currency": 1.234},
    {"id": "solana", "price_change_percentage_1h_in_currency": None},
]


def rows(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class BackdropTests(unittest.TestCase):
    def test_parse_keeps_only_the_values_it_was_given(self):
        self.assertEqual(bd.parse(COINS), {"btc_change_1h_pct": 0.46, "btc_change_24h_pct": -2.5,
                                           "eth_change_1h_pct": 1.23})
        self.assertEqual(bd.parse([]), {})
        self.assertEqual(bd.parse([{"id": "bitcoin", "price_change_percentage_1h_in_currency": "x"}]), {})

    def test_one_cached_lookup_for_many_calls(self):
        clock = [NOW]
        calls = []

        def get(url, **kw):
            calls.append(kw)
            return Resp(COINS)
        b = bd.MarketBackdrop(key="k", get=get, clock=lambda: clock[0])
        for _ in range(50):
            self.assertEqual(b()["btc_change_1h_pct"], 0.46)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["timeout"], bd.TIMEOUT_SECONDS)
        self.assertEqual(calls[0]["headers"], {"x-cg-demo-api-key": "k"})
        self.assertEqual(calls[0]["params"]["ids"], "bitcoin,ethereum,solana")
        clock[0] = NOW + timedelta(minutes=bd.CACHE_MINUTES, seconds=1)
        b()
        self.assertEqual(len(calls), 2)

    def test_a_failed_lookup_is_blank_never_raises_and_is_retried_later(self):
        clock, calls = [NOW], []

        def get(url, **kw):
            calls.append(1)
            raise OSError("no network")
        b = bd.MarketBackdrop(key="", get=get, clock=lambda: clock[0])
        self.assertEqual(b(), {})
        self.assertEqual(b(), {})
        self.assertEqual(len(calls), 1)             # not hammered
        clock[0] = NOW + timedelta(seconds=bd.RETRY_SECONDS + 1)
        b()
        self.assertEqual(len(calls), 2)

    def test_bad_answers_are_blank(self):
        for resp in (Resp({"status": {"error_code": 429}}, 429), Resp("junk"), Resp(None, 200)):
            b = bd.MarketBackdrop(key="", get=lambda *a, **k: resp, clock=lambda: NOW)
            self.assertEqual(b(), {})


class LaunchTimeTests(unittest.TestCase):
    def test_hour_and_weekday_come_from_the_creation_time_not_the_first_check(self):
        created = datetime(2026, 10, 11, 23, 50, 0, tzinfo=timezone.utc)       # Sunday 23:50
        seen = datetime(2026, 10, 12, 0, 20, 30, tzinfo=timezone.utc)          # Monday 00:20:30
        t = tr.launch_times(seen, created.timestamp() * 1000)
        self.assertEqual((t["created_at_utc"], t["created_source"]), ("2026-10-11T23:50:00Z", "pool"))
        self.assertEqual((t["created_hour_utc"], t["created_weekday"]), (23, 6))
        self.assertEqual((t["seen_hour_utc"], t["seen_weekday"]), (0, 0))
        self.assertEqual(t["seen_delay_seconds"], 30 * 60 + 30)

    def test_fallbacks_and_unknown(self):
        seen = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)            # Wednesday
        age = tr.launch_times(seen, None, None, 15)
        self.assertEqual((age["created_at_utc"], age["created_source"], age["seen_delay_seconds"]),
                         ("2026-10-14T08:45:00Z", "pool", 900))
        rc = tr.launch_times(seen, None, "2026-10-14 07:00:00")
        self.assertEqual((rc["created_source"], rc["created_hour_utc"], rc["seen_delay_seconds"]),
                         ("rugcheck", 7, 7200))
        none = tr.launch_times(seen)
        self.assertIsNone(none["created_at_utc"])
        self.assertEqual((none["seen_hour_utc"], none["seen_weekday"]), (9, 2))

    def test_old_rows_are_worked_out_from_the_older_columns(self):
        row = {"first_checked_utc": "2026-10-11 02:04:11", "pool_age_minutes": "5.358620383"}
        t = tr.row_launch_times(row)
        self.assertEqual((t["created_hour_utc"], t["created_weekday"]), (1, 6))      # 01:58:50
        self.assertEqual(tr.row_launch_times({"first_checked_utc": "2026-10-11 02:04:11"})
                         ["created_at_utc"], None)
        self.assertIsNone(tr.row_launch_times({})["seen_hour_utc"])
        saved = {"created_at_utc": "2026-10-11T05:00:00Z", "created_hour_utc": "5",
                 "created_weekday": "6"}
        self.assertEqual(tr.row_launch_times(saved)["created_hour_utc"], "5")


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def add(self, log, mint=MINT, pair=PAIR):
        pair = dict(pair, baseToken=dict(pair["baseToken"], address=mint))
        return log.add(Result(mint, "AAA", "Aaa", pair), None, {}, NOW, "FAIL", "x", True, "d")

    def test_new_columns_are_written(self):
        log = tr.CandidateLog(self.d, "test", backdrop=lambda: bd.parse(COINS))
        self.assertTrue(self.add(log))
        (row,) = rows(os.path.join(self.d, "candidates.csv"))
        self.assertEqual((row["btc_change_1h_pct"], row["btc_change_24h_pct"],
                          row["eth_change_1h_pct"], row["sol_change_1h_pct"]),
                         ("0.46", "-2.5", "1.23", ""))
        self.assertEqual((row["created_at_utc"], row["created_hour_utc"], row["created_weekday"],
                          row["seen_delay_seconds"], row["seen_hour_utc"], row["seen_weekday"]),
                         ("2026-10-11T13:00:00Z", "13", "6", "5400", "14", "6"))

    def test_empty_columns_when_the_btc_lookup_fails_and_the_row_is_still_written(self):
        def boom():
            raise RuntimeError("down")
        for source in (lambda: {}, boom, None):
            with tempfile.TemporaryDirectory() as d:
                log = tr.CandidateLog(d, "test", backdrop=source)
                self.assertTrue(self.add(log))
                (row,) = rows(os.path.join(d, "candidates.csv"))
                for c in tr.BACKDROP_COLUMNS:
                    self.assertEqual(row[c], "")
                self.assertEqual(row["created_hour_utc"], "13")

    def test_the_papertrader_backdrop_is_used_when_the_log_has_none(self):
        with mock.patch.object(PaperTrader, "backdrop", lambda: {"btc_change_1h_pct": 0.5}):
            log = tr.CandidateLog(self.d, "test")
            self.add(log)
        (row,) = rows(os.path.join(self.d, "candidates.csv"))
        self.assertEqual(row["btc_change_1h_pct"], "0.5")

    def test_unknown_creation_time_leaves_the_columns_empty(self):
        log = tr.CandidateLog(self.d, "test")
        self.add(log, pair={k: v for k, v in PAIR.items() if k != "pairCreatedAt"})
        (row,) = rows(os.path.join(self.d, "candidates.csv"))
        self.assertEqual((row["created_at_utc"], row["created_hour_utc"], row["seen_delay_seconds"]),
                         ("", "", ""))
        self.assertEqual((row["seen_hour_utc"], row["seen_weekday"]), ("14", "6"))

    def test_an_old_candidates_file_still_reads_and_is_extended(self):
        path = os.path.join(self.d, "candidates.csv")
        old_cols = [c for c in tr.CANDIDATE_COLUMNS if c not in tr.BACKDROP_COLUMNS + tr.LAUNCH_COLUMNS]
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(old_cols)
            w.writerow(["2026-10-10 10:00:00" if c == "first_checked_utc" else "OLDMINT"
                        if c == "token_address" else "" for c in old_cols])
        self.assertEqual(len(tr.CandidateLog(self.d, "test").rows()), 1)
        log = tr.CandidateLog(self.d, "test", backdrop=lambda: bd.parse(COINS))
        self.add(log)
        old, new = rows(path)
        self.assertEqual((old["token_address"], old["btc_change_1h_pct"], old["created_at_utc"]),
                         ("OLDMINT", "", ""))
        self.assertEqual(new["btc_change_1h_pct"], "0.46")
        self.assertEqual(list(new), tr.CANDIDATE_COLUMNS)

    def test_entries_get_btc_change_1h_pct_and_old_entries_stay(self):
        path = os.path.join(self.d, "entries.csv")
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time_utc", "symbol", "token_address", "price_usd"])
            w.writerow(["2026-10-01 00:00:00", "OLD", "oldmint", "1"])
        trader = PaperTrader(CFG["paper_trading"], self.d)
        result = Result(MINT, "AAA", "Aaa", PAIR)
        with mock.patch.object(PaperTrader, "backdrop", lambda: bd.parse(COINS)):
            self.assertIsNotNone(trader.buy(result, when=NOW))
        old, new = rows(path)
        self.assertEqual((old["symbol"], old["btc_change_1h_pct"]), ("OLD", ""))
        self.assertEqual(list(new), ENTRY_COLUMNS)
        self.assertEqual(new["btc_change_1h_pct"], "0.46")

    def test_a_failing_lookup_never_stops_a_buy_and_leaves_the_cell_blank(self):
        def boom():
            raise RuntimeError("down")
        for source in (boom, lambda: {}, None):
            with tempfile.TemporaryDirectory() as d, mock.patch.object(PaperTrader, "backdrop", source):
                trader = PaperTrader(CFG["paper_trading"], d)
                self.assertIsNotNone(trader.buy(Result(MINT, "AAA", "Aaa", PAIR), when=NOW))
                (row,) = rows(os.path.join(d, "entries.csv"))
                self.assertEqual(row["btc_change_1h_pct"], "")


# ---------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------

def candidate(hour, day=11, *, price="1", p1=None, l1=None, asked1=True, verdict="FAIL",
              dex="pumpswap", btc1=None, btc24=None, p24=None, l24=None, asked24=False):
    """A candidates.csv row of a token created at `hour` on 2026-10-`day` (UTC)."""
    created = datetime(2026, 10, day, hour, 10, tzinfo=timezone.utc)
    seen = created + timedelta(minutes=5)
    row = dict.fromkeys(tr.CANDIDATE_COLUMNS, "")
    row.update(first_checked_utc=seen.strftime(tr.TIME), price_usd=price, verdict=verdict,
               dex_id=dex, pool_age_minutes="5")
    if asked1:
        row.update(time_1h_utc="x", price_1h_usd="" if p1 is None else p1,
                   liquidity_1h_usd="" if l1 is None else l1)
    if asked24:
        row.update(time_24h_utc="x", price_24h_usd="" if p24 is None else p24,
                   liquidity_24h_usd="" if l24 is None else l24)
    if btc1 is not None:
        row["btc_change_1h_pct"] = btc1
    if btc24 is not None:
        row["btc_change_24h_pct"] = btc24
    return row


def prep(rows_):
    return [tre.prepare(r) for r in rows_]


class MeasureTests(unittest.TestCase):
    def test_buckets_count_missing_values_as_missing_not_zero(self):
        toks = prep([
            candidate(5, p1="1.6", l1="50000"),                 # +60%, alive
            candidate(5, p1="0.5", l1="1000"),                  # -50%, price but thin liquidity
            candidate(5, p1="1.2"),                             # price, liquidity blank: unknown
            candidate(5, p1=None),                              # asked, no pair: dead, no price
            candidate(5, asked1=False),                         # never asked: missing everywhere
        ])
        m = tre.measures(toks, 30_000)
        self.assertEqual(m["tokens"], (5, 5))
        value, n = m["alive_1h"]
        self.assertEqual((round(value), n), (33, 3))            # 1 of {alive, thin, dead}
        value, n = m["median_1h"]
        self.assertEqual((round(value, 1), n), (20.0, 3))       # +60, -50, +20 -> median +20
        value, n = m["up50"]
        self.assertEqual((round(value), n), (33, 3))            # tokens with any price
        self.assertEqual(m["alive_6h"], (None, 0))

    def test_passed_and_graduated(self):
        toks = prep([candidate(1, verdict="PASS"), candidate(1, dex="pumpfun"),
                     candidate(1, dex=""), candidate(1, dex="raydium")])
        m = tre.measures(toks, 30_000)
        self.assertEqual(m["passed"], (25.0, 4))
        self.assertEqual((round(m["graduated"][0]), m["graduated"][1]), (67, 3))   # dex "" unknown

    def test_hour_and_weekday_buckets_use_the_creation_time(self):
        toks = prep([candidate(23, day=11), candidate(0, day=12)])   # Sunday 23:10, Monday 00:10
        self.assertEqual([(t["hour"], t["weekday"]) for t in toks], [(23, 6), (0, 0)])

    def test_a_bucket_under_30_tokens_is_marked_too_few(self):
        few = prep([candidate(3, p1="1.1", l1="50000") for _ in range(29)])
        enough = prep([candidate(4, p1="1.1", l1="50000") for _ in range(30)])
        text = tre.table("hour", [("03", few), ("04", enough)], 30_000)
        row3, row4 = [ln for ln in text.splitlines() if ln.startswith(("| 03", "| 04"))]
        self.assertIn("too few to judge", row3)
        self.assertNotIn("too few to judge", row4)
        self.assertIn("(n=29)†", row3)
        self.assertIn("(n=30)", row4)
        self.assertNotIn("†", row4)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "main-1min"))

    def write(self, rel, columns, data):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    def report(self):
        return tre.build_report(self.root, 30_000)

    def test_no_files_at_all(self):
        text = self.report()
        self.assertIn("No candidate rows yet.", text)
        self.assertIn("**Not enough data:** 0 days", text)
        self.assertIn("## How to read this", text)

    def test_header_only_file(self):
        self.write("main-1min/candidates.csv", tr.CANDIDATE_COLUMNS, [])
        self.assertIn("No candidate rows yet.", self.report())

    def test_a_tiny_file_says_not_enough_data_and_too_few(self):
        self.write("main-1min/candidates.csv", tr.CANDIDATE_COLUMNS,
                   [candidate(5, p1="1.6", l1="50000"), candidate(6)])
        text = self.report()
        self.assertIn("**Not enough data:** only 0.0 days of rows so far", text)
        self.assertIn("too few to judge", text)
        self.assertIn("0 of 2 rows have this reading.", text)         # no BTC data yet
        self.assertIn("a lead to test on later days, not a rule", text)
        self.assertIn("Nothing in this report changes the bot", text)

    def test_seven_days_remove_the_not_enough_data_line(self):
        data = [candidate(5, day=11), candidate(5, day=18, price="1")]
        self.write("main-1min/candidates.csv", tr.CANDIDATE_COLUMNS, data)
        self.assertNotIn("Not enough data", self.report())

    def test_rows_without_a_creation_time_are_counted(self):
        bad = candidate(5)
        bad["pool_age_minutes"] = ""
        self.write("main-1min/candidates.csv", tr.CANDIDATE_COLUMNS, [candidate(5), bad])
        self.assertIn("1 of 2 rows have no creation time", self.report())

    def test_backdrop_bins(self):
        data = [candidate(5, btc1="-2", btc24="0.5"), candidate(5, btc1="0", btc24="3"),
                candidate(5, btc1="1.5", btc24="-4"), candidate(5, btc1="1", btc24="")]
        self.write("main-1min/candidates.csv", tr.CANDIDATE_COLUMNS, data)
        text = self.report()
        one = text.split("### Bitcoin 1 h change")[1].split("### Bitcoin 24 h change")[0]
        self.assertIn("4 of 4 rows have this reading.", one)
        rows1 = {ln.split("|")[1].strip(): ln.split("|")[2].strip() for ln in one.splitlines()
                 if ln.startswith(("| below", "| -1%", "| above"))}
        self.assertEqual(rows1, {"below -1%": "n=1", "-1% to +1%": "n=2", "above +1%": "n=1"})
        self.assertIn("3 of 4 rows have this reading.", text.split("### Bitcoin 24 h change")[1])

    def test_paper_buys_per_hour_block_attribute_sells_to_the_buy_hour(self):
        cols = ["time_utc", "action", "symbol", "token_address", "pnl_usd"]
        self.write("main-1min/candidates.csv", tr.CANDIDATE_COLUMNS, [candidate(5)])
        self.write("main-1min/b/journal.csv", cols, [
            {"time_utc": "2026-10-11 03:10:00", "action": "BUY", "token_address": "t1"},
            {"time_utc": "2026-10-11 09:10:00", "action": "BUY", "token_address": "t2"},
            {"time_utc": "2026-10-11 10:00:00", "action": "SELL", "token_address": "t1", "pnl_usd": "-2.5"},
            {"time_utc": "2026-10-11 10:30:00", "action": "SELL", "token_address": "t1", "pnl_usd": "1.0"},
            {"time_utc": "2026-10-11 11:00:00", "action": "SELL", "token_address": "zzz", "pnl_usd": "5"},
        ])
        text = self.report()
        self.assertIn("| 00-05 | 1 buys, -1.50$ (n=1)† |", text)
        self.assertIn("| 06-11 | 1 buys, +0.00$ (n=1)† |", text)
        self.assertIn("| 03 | 1 buys, -1.50$ (n=1)† |", text)
        self.assertIn("1 sell(s) had no earlier buy", text)

    def test_the_report_file_is_written_and_is_the_same_twice(self):
        self.write("main-1min/candidates.csv", tr.CANDIDATE_COLUMNS, [candidate(5)])
        path = tre.main(self.root, 30_000)
        self.assertEqual(path, os.path.join(self.root, "main-1min", "timing_report.md"))
        first = open(path).read()
        tre.main(self.root, 30_000)
        self.assertEqual(first, open(path).read())

    def test_the_report_reads_the_real_files_of_the_repository_without_error(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        text = tre.build_report(os.path.join(here, "data"), 30_000)
        self.assertIn("# Timing report", text)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, ".github", "workflows", "timing-report.yml")) as fh:
            self.text = fh.read()

    def test_schedule_runner_and_files(self):
        self.assertIn('cron: "20 0 * * *"', self.text)
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("runs-on: ubuntu-24.04", self.text)
        self.assertIn("python timing_report.py", self.text)
        self.assertIn("git add data/main-1min/timing_report.md", self.text)
        self.assertEqual(self.text.count("git add"), 1)

    def test_no_secrets_are_used(self):
        self.assertNotIn("secrets.", self.text.replace("# ", "").split("jobs:")[1])
        self.assertNotIn("API_KEY", self.text.split("jobs:")[1])


if __name__ == "__main__":
    unittest.main()
