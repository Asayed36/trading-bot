"""Checks for the token record (screener/token_record.py): extra entries.csv
columns, candidates.csv (every token the first time it is checked, with its
price 1, 6 and 24 hours later) and the creator ledger. Recording only: the
trades must be exactly the same with and without it.
Run with:  python -m unittest -v
"""

import copy
import csv
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

import main_1min as m1  # noqa: E402
from run import load_config  # noqa: E402
from screener import token_record as tr  # noqa: E402
from screener.api import RateLimited  # noqa: E402
from screener.convergence import ConvergenceStrategy  # noqa: E402
from screener.demo import GOOD, DemoApi, demo_rpc_factory, demo_trader_history  # noqa: E402
from screener.filters import Result  # noqa: E402
from screener.paper_trader import ENTRY_COLUMNS, PaperTrader  # noqa: E402
from tests.test_convergence import TRACKED, _swap  # noqa: E402
from tests.test_main_1min import Api  # noqa: E402

CFG = running(load_config())
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
F = {}
MINT = "MintAAAA"

REPORT = {
    "creator": "CreatorX", "creatorBalance": 20, "detectedAt": "2026-10-04T09:30:15.123456789Z",
    "launchpad": {"name": "Pump.Fun", "platform": "pump_fun"},
    "token": {"supply": 1000, "mintAuthority": None, "freezeAuthority": None},
    "totalHolders": 611,
    "topHolders": [{"address": "pool", "owner": "poolowner", "pct": 40.0},
                   {"address": "a", "owner": "a", "pct": 9.0},
                   {"address": "b", "owner": "b", "pct": 6.0},
                   {"address": "c", "owner": "c", "pct": 5.0}],
    "knownAccounts": {"pool": {"type": "AMM"}},
    "insiderNetworks": [{"id": "x", "size": 4, "currentHolding": 70},
                        {"id": "y", "size": 9, "currentHolding": 110}],
    "creatorTokens": [{"mint": "old1", "marketCap": 100.0}, {"mint": "old2", "marketCap": 9000.0},
                      {"mint": "old3", "marketCap": 4999.0}],
}
PAIR = {"dexId": "pumpswap", "pairAddress": "P1", "priceUsd": "0.5", "marketCap": 250000,
        "liquidity": {"usd": 40000}, "pairCreatedAt": int((NOW - timedelta(minutes=90)).timestamp()
                                                          * 1000),
        "baseToken": {"address": MINT, "symbol": "AAA", "name": "Aaa"},
        "txns": {"m5": {"buys": 3, "sells": 1}, "h1": {"buys": 30, "sells": 20},
                 "h24": {"buys": 900, "sells": 700}},
        "volume": {"m5": 100.0, "h1": 5000.0, "h24": 90000.0},
        "priceChange": {"m5": 1.5, "h1": 20.0, "h24": 80.0}}


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class RecordFieldsTests(unittest.TestCase):
    def test_every_field_from_the_report(self):
        rec = tr.record_fields(REPORT, PAIR, F)
        self.assertEqual(rec["rc_launchpad"], "pump_fun")
        self.assertEqual(rec["rc_first_seen_utc"], "2026-10-04 09:30:15")
        self.assertEqual(rec["rc_creator"], "CreatorX")
        self.assertAlmostEqual(rec["rc_creator_pct"], 2.0)
        # the pool wallet (40%) isn't a holder: top 1 is 9%, top 10 is 9+6+5
        self.assertEqual((rec["rc_top1_pct"], rec["rc_top10_pct"]), (9.0, 20.0))
        self.assertEqual(rec["rc_total_holders"], 611)
        self.assertEqual(rec["rc_insider_largest_network"], 9)          # the bigger network
        self.assertAlmostEqual(rec["rc_insider_largest_network_pct"], 11.0)
        self.assertEqual((rec["rc_creator_tokens"], rec["rc_creator_tokens_dead"]), (3, 2))

    def test_unknown_is_blank_not_zero(self):
        report = dict(REPORT, creatorTokens=None, creatorBalance=None, totalHolders=None,
                      launchpad=None, detectedAt=None, topHolders=[])
        rec = tr.record_fields(report, PAIR, F)
        for key in ("rc_launchpad", "rc_first_seen_utc", "rc_creator_pct", "rc_top1_pct",
                    "rc_top10_pct", "rc_total_holders", "rc_creator_tokens",
                    "rc_creator_tokens_dead"):
            self.assertIsNone(rec[key], key)
        self.assertEqual(tr.record_fields(None, PAIR, F), {})
        cells = dict(zip(tr.RECORD_COLUMNS, tr.cells({}, None, NOW)))
        self.assertTrue(all(v == "" for v in cells.values()))

    def test_no_insider_network_listed_means_none_detected(self):
        rec = tr.record_fields(dict(REPORT, insiderNetworks=None), PAIR, F)
        self.assertEqual((rec["rc_insider_largest_network"],
                          rec["rc_insider_largest_network_pct"]), (0, 0.0))

    def test_cells_add_the_ages_and_dexscreener_facts(self):
        rec = tr.record_fields(REPORT, PAIR, F)
        cells = dict(zip(tr.RECORD_COLUMNS, tr.cells(rec, PAIR, NOW)))
        self.assertAlmostEqual(float(cells["token_age_hours"]), 2.5 - 0.0042, places=2)
        self.assertEqual((cells["dex_id"], cells["pool_age_minutes"], cells["market_cap_usd"],
                          cells["liquidity_usd"]), ("pumpswap", "90", "250000", "40000"))
        self.assertEqual(cells["creator_ledger_launches"], "")      # no ledger given


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "ledger.json")
        self.early = os.path.join(self.tmp.name, "early.json")
        with open(self.early, "w") as fh:
            json.dump({"dead_creators": ["Deadbeat"]}, fh)

    def test_seeded_by_earlys_dead_creators(self):
        ledger = tr.CreatorLedger(self.path, self.early)
        self.assertEqual(ledger.stats("Deadbeat"), (1, 1))
        self.assertEqual(ledger.stats("Stranger"), (0, 0))
        ledger.save()
        self.assertFalse(os.path.exists(self.path))           # nothing of ours to save yet

    def test_report_teaches_the_creators_other_tokens(self):
        ledger = tr.CreatorLedger(self.path, self.early)
        ledger.note_report(REPORT, MINT)
        self.assertEqual(ledger.stats("CreatorX", exclude=MINT), (3, 2))   # not counting MINT
        self.assertEqual(ledger.stats("CreatorX"), (4, 2))
        ledger.save()
        again = tr.CreatorLedger(self.path, self.early)
        self.assertEqual(again.stats("CreatorX"), (4, 2))

    def test_unknown_never_overwrites_known_and_it_is_capped(self):
        ledger = tr.CreatorLedger(self.path)
        ledger.note("c", "m", True)
        ledger.note("c", "m")
        self.assertEqual(ledger.stats("c"), (1, 1))
        for i in range(tr.MAX_TOKENS_PER_CREATOR + 10):
            ledger.note("c", f"m{i}", False)
        self.assertEqual(ledger.stats("c")[0], tr.MAX_TOKENS_PER_CREATOR)


class CandidateLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = tr.CandidateLog(self.tmp.name, "test")
        self.ledger = tr.CreatorLedger(os.path.join(self.tmp.name, "l.json"))

    def result(self, mint=MINT, pair=PAIR):
        return Result(mint, "AAA", "Aaa", pair)

    def add(self, mint=MINT, **kw):
        rec = tr.record_fields(REPORT, PAIR, F)
        return self.log.add(self.result(mint), REPORT, rec, NOW, "FAIL", "Liquidity: $1",
                            True, "main=failed main's checks", self.ledger, **kw)

    def test_one_row_the_first_time_only(self):
        self.assertTrue(self.add())
        self.assertFalse(self.add())
        (row,) = rows(self.log.path)
        self.assertEqual(row["first_checked_utc"], "2026-10-04 12:00:00")
        self.assertEqual((row["verdict"], row["failed_checks"], row["safety_checked"]),
                         ("FAIL", "Liquidity: $1", "yes"))
        self.assertEqual((row["buys_5m"], row["sells_1h"], row["volume_24h_usd"],
                          row["price_change_1h_pct"], row["market_cap_usd"], row["dex_id"]),
                         ("3", "20", "90000", "20", "250000", "pumpswap"))
        self.assertEqual((row["rc_launchpad"], row["rc_top10_pct"]), ("pump_fun", "20"))
        # the ledger knew nothing else about this creator but what RugCheck listed
        self.assertEqual((row["creator_ledger_launches"], row["creator_ledger_dead"]), ("3", "2"))
        self.assertEqual(row["price_1h_usd"], "")
        # a new process remembers from the file
        self.assertFalse(tr.CandidateLog(self.tmp.name, "test").add(
            self.result(), REPORT, None, NOW, "FAIL", "", True, ""))

    def test_a_token_whose_safety_was_not_checked_has_dexscreener_fields_only(self):
        self.log.add(self.result(), None, None, NOW, "FAIL", "Liquidity: $1", False, "")
        (row,) = rows(self.log.path)
        self.assertEqual((row["safety_checked"], row["rc_launchpad"], row["rc_top10_pct"],
                          row["token_age_hours"]), ("no", "", "", ""))
        self.assertEqual(row["market_cap_usd"], "250000")

    def test_prices_after_1_6_and_24_hours(self):
        self.add()
        self.assertEqual(self.log.due(NOW + timedelta(minutes=30)), {})
        self.assertEqual(self.log.due(NOW + timedelta(minutes=61)), {MINT: ["1h"]})
        later = copy.deepcopy(PAIR)
        later.update(priceUsd="0.25", marketCap=125000)
        later["liquidity"] = {"usd": 20000}
        due = self.log.due(NOW + timedelta(minutes=61))
        self.log.fill(due, [later], NOW + timedelta(minutes=61), ["pumpswap"], self.ledger)
        (row,) = rows(self.log.path)
        self.assertEqual((row["price_1h_usd"], row["market_cap_1h_usd"], row["liquidity_1h_usd"],
                          row["time_1h_utc"]), ("0.25", "125000", "20000", "2026-10-04 13:01:00"))
        self.assertEqual(self.log.due(NOW + timedelta(minutes=70)), {})        # asked once
        self.assertEqual(self.log.due(NOW + timedelta(hours=6, minutes=1)), {MINT: ["6h"]})
        self.assertEqual(self.log.due(NOW + timedelta(hours=24, minutes=1)),
                         {MINT: ["24h"]})

    def test_a_missed_checkpoint_stays_blank_and_a_gone_token_is_marked(self):
        self.add()
        # nobody looked for 3 hours: the 1-hour price is not saved late
        self.assertEqual(self.log.due(NOW + timedelta(hours=3)), {})
        due = self.log.due(NOW + timedelta(hours=6, minutes=2))
        self.log.fill(due, [], NOW + timedelta(hours=6, minutes=2), ["pumpswap"], self.ledger)
        (row,) = rows(self.log.path)
        self.assertEqual((row["price_6h_usd"], row["time_6h_utc"]), ("", "2026-10-04 18:02:00"))
        self.assertEqual(row["price_1h_usd"], "")

    def test_a_dead_market_cap_marks_the_creators_token_dead(self):
        self.add()
        dead = copy.deepcopy(PAIR)
        dead.update(priceUsd="0.001", marketCap=1200)
        due = self.log.due(NOW + timedelta(minutes=61))
        self.log.fill(due, [dead], NOW + timedelta(minutes=61), ["pumpswap"], self.ledger)
        self.assertEqual(self.ledger.stats("CreatorX"), (4, 3))

    def test_a_token_with_no_price_at_the_first_check_is_not_repriced(self):
        pair = dict(PAIR, priceUsd=None)
        self.log.add(self.result(pair=pair), None, None, NOW, "FAIL", "", False, "")
        self.assertEqual(self.log.due(NOW + timedelta(minutes=61)), {})

    def test_batched_in_30s_through_the_apis_call(self):
        api = mock.Mock()
        api.pairs_for_tokens.return_value = []
        for i in range(31):
            self.add(mint=f"M{i}")
        self.assertEqual(tr.reprice(self.log, api, NOW + timedelta(minutes=61), []), 31)
        (call,) = api.pairs_for_tokens.call_args_list
        self.assertEqual(len(call.args[0]), 31)        # PublicApi splits it into 30 + 1
        self.assertEqual(tr.reprice(self.log, api, NOW + timedelta(minutes=62), []), 0)
        self.assertEqual(api.pairs_for_tokens.call_count, 1)


class EntriesTests(unittest.TestCase):
    def test_the_old_columns_are_unchanged_and_the_new_ones_come_last(self):
        old = ["time_utc", "symbol", "token_address", "price_usd", "buys_1h", "sells_1h",
               "insider_flagged", "insider_networks", "insider_linked_wallets",
               "insider_top_holders", "price_change_5m_pct", "price_change_1h_pct"]
        self.assertEqual(ENTRY_COLUMNS[:len(old)], old)
        self.assertEqual(ENTRY_COLUMNS[-len(tr.RECORD_COLUMNS):], tr.RECORD_COLUMNS)
        self.assertEqual(ENTRY_COLUMNS[-len(tr.RECORD_COLUMNS) - 4:-len(tr.RECORD_COLUMNS)],
                         ["buys_5m", "sells_5m", "volume_5m_usd", "volume_1h_usd"])

    def test_a_buy_saves_the_new_columns_and_an_old_file_is_extended(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "entries.csv"), "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["time_utc", "symbol", "token_address", "price_usd"])
                w.writerow(["2026-10-01 00:00:00", "OLD", "oldmint", "1"])
            trader = PaperTrader(CFG["paper_trading"], d)
            trader.ledger = tr.CreatorLedger(os.path.join(d, "ledger.json"))
            trader.ledger.note("CreatorX", "prev", True)
            result = Result(MINT, "AAA", "Aaa", PAIR)
            result.record = tr.record_fields(REPORT, PAIR, F)
            trader.buy(result, when=NOW)
            old, new = rows(os.path.join(d, "entries.csv"))
            self.assertEqual((old["symbol"], old["rc_launchpad"]), ("OLD", ""))
            self.assertEqual(list(new), ENTRY_COLUMNS)
            self.assertEqual((new["rc_launchpad"], new["rc_top10_pct"], new["dex_id"],
                              new["pool_age_minutes"], new["liquidity_usd"],
                              new["creator_ledger_launches"], new["creator_ledger_dead"]),
                             ("pump_fun", "20", "pumpswap", "90", "40000", "1", "1"))

    def test_a_failing_record_never_stops_a_buy(self):
        with tempfile.TemporaryDirectory() as d:
            trader = PaperTrader(CFG["paper_trading"], d)
            result = Result(MINT, "AAA", "Aaa", PAIR)
            result.record = "not a dict"
            self.assertIsNotNone(trader.buy(result, when=NOW))
            (row,) = rows(os.path.join(d, "entries.csv"))
            self.assertEqual(row["rc_launchpad"], "")


class MainOneMinuteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def bot(self, folder=None, api=None):
        return m1.MainOneMinute(CFG, folder or self.d, api or Api())

    def path(self, name, folder=None):
        return os.path.join(folder or self.d, "main-1min", name)

    def test_every_checked_token_gets_one_row_bought_or_not(self):
        bot = self.bot()
        bot.run_once(NOW, lambda *a: None)
        got = {r["symbol"]: r for r in rows(self.path("candidates.csv"))}
        buys = {r["symbol"] for r in rows(self.path("journal.csv"))}
        self.assertTrue(buys)
        self.assertGreater(len(got), len(buys))              # the skipped ones are there
        for sym in buys:
            self.assertEqual(got[sym]["verdict"], "PASS")
            self.assertIn("main=bought", got[sym]["decisions"])
        failed = [r for r in got.values() if r["verdict"] == "FAIL"]
        self.assertTrue(failed)
        for r in failed:
            self.assertTrue(r["failed_checks"])
            self.assertIn("main=failed main's checks", r["decisions"])
        # every version's decision is there
        self.assertTrue(all(f"{v}=" in r["decisions"] for r in got.values() for v in "ABC"))
        before = len(got)
        bot.run_once(NOW + timedelta(minutes=1), lambda *a: None)
        self.assertEqual(len(rows(self.path("candidates.csv"))), before)   # first time only

    def test_later_prices_with_one_batched_call_every_few_minutes(self):
        api = Api()
        bot = self.bot(api=api)
        bot.run_once(NOW, lambda *a: None)
        n = len(rows(self.path("candidates.csv")))
        calls = []
        real = api.pairs_for_tokens
        api.pairs_for_tokens = lambda addrs: (calls.append(list(addrs)), real(addrs))[1]
        for minute in range(1, 61):
            bot.run_once(NOW + timedelta(minutes=minute), lambda *a: None)
        before = len(calls)
        calls.clear()
        bot.run_once(NOW + timedelta(minutes=61), lambda *a: None)
        done = [r for r in rows(self.path("candidates.csv")) if r["time_1h_utc"]]
        self.assertEqual(len(done), n)
        self.assertTrue(before > 0)
        # the 1-hour prices cost one batched request for all tokens (plus the
        # bot's own two requests that minute)
        self.assertLessEqual(len([c for c in calls if len(c) >= n]), 1)
        good = next(r for r in done if r["symbol"] == "GOODCAT")
        self.assertTrue(good["price_1h_usd"])

    def test_trading_is_identical_with_and_without_the_recording(self):
        def play(folder, record):
            api = Api()
            bot = self.bot(folder, api)
            with mock.patch.object(m1.MainOneMinute, "_record",
                                   m1.MainOneMinute._record if record else
                                   (lambda *a, **k: None)):
                for minute in range(0, 8):
                    api.__init__({GOOD: 1.0 + minute / 5})
                    bot.run_once(NOW + timedelta(minutes=minute), lambda *a: None)
            out = {}
            for sub in ("", "a", "b", "c"):
                for name in ("journal.csv", "positions.json"):
                    path = os.path.join(folder, "main-1min", sub, name)
                    if os.path.exists(path):
                        with open(path) as fh:
                            text = fh.read()
                        # (times of the fetch are the real clock's)
                        out[(sub, name)] = re.sub(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d[.\d+:]*",
                                                 "T", text)
            return out
        a, b = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(a.cleanup)
        self.addCleanup(b.cleanup)
        off, on = play(a.name, False), play(b.name, True)
        self.assertEqual(off, on)
        self.assertTrue(off[("", "journal.csv")].count("BUY") >= 1)
        self.assertTrue(os.path.exists(self.path("candidates.csv", b.name)))
        self.assertFalse(os.path.exists(self.path("candidates.csv", a.name)))

    def test_entries_have_the_new_columns(self):
        self.bot().run_once(NOW, lambda *a: None)
        entries = rows(self.path("entries.csv"))
        self.assertTrue(entries)
        e = entries[0]
        self.assertEqual(list(e), ENTRY_COLUMNS)
        self.assertEqual(e["dex_id"], "pumpswap")
        self.assertTrue(e["market_cap_usd"])
        self.assertTrue(e["rc_top10_pct"])
        self.assertEqual(e["rc_first_seen_utc"], "")        # the demo report has no detectedAt

    def test_a_failing_recording_never_stops_the_trading(self):
        bot = self.bot()
        with mock.patch.object(tr.CandidateLog, "add", side_effect=RuntimeError("boom")):
            bot.run_once(NOW, lambda *a: None)
        self.assertTrue(rows(self.path("journal.csv")))

    def test_dexscreener_refusing_the_later_prices_changes_nothing(self):
        api = Api()
        bot = self.bot(api=api)
        bot.run_once(NOW, lambda *a: None)
        real = api.pairs_for_tokens
        refused, inside = [], []

        def refuse(addresses):
            if inside:                      # only the later-prices call is refused
                refused.append(1)
                raise RateLimited("api.dexscreener.com kept saying 'too many requests'")
            return real(addresses)
        api.pairs_for_tokens = refuse
        original = m1.reprice

        def marked(*args, **kw):
            inside.append(1)
            try:
                return original(*args, **kw)
            finally:
                inside.clear()
        before = rows(self.path("journal.csv"))
        lines = []
        with mock.patch.object(m1, "reprice", marked):
            bot.run_once(NOW + timedelta(minutes=61), lines.append)
        self.assertTrue(refused)                       # the later-prices call was refused...
        self.assertIn("passed", lines[0])              # ...and the run went on as usual
        self.assertTrue(len(rows(self.path("journal.csv"))) >= len(before))
        self.assertFalse(any(r["time_1h_utc"] for r in rows(self.path("candidates.csv"))))


class ConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live = {}
        self.history = demo_trader_history()
        cfg = dict(CFG, convergence=dict(CFG["convergence"], helius_every_minutes=2))
        self.cfg = cfg

    def go(self, record=True):
        s = ConvergenceStrategy(self.cfg, self.tmp.name,
                                rpc_factory=demo_rpc_factory(self.history, self.live))
        lines = []
        plan = s.fetch(DemoApi())
        with mock.patch.object(ConvergenceStrategy, "_record",
                               ConvergenceStrategy._record if record else
                               (lambda *a, **k: None)):
            s.apply(plan, lines.append)
        return s, plan

    def test_converged_tokens_are_logged_once_and_the_buy_is_unchanged(self):
        from screener.demo import EARLY_GOOD
        self.go()
        self.go()
        for wallet, ago in zip(TRACKED, (15, 9, 3)):
            when = datetime.now(timezone.utc) - timedelta(minutes=ago)
            self.live.setdefault(wallet, []).append(_swap(EARLY_GOOD, "buy", 0.5, 100.0, when))
        s, plan = self.go()
        (pos,) = s.trader.open_positions
        path = os.path.join(self.tmp.name, "convergence", "candidates.csv")
        (row,) = rows(path)
        self.assertEqual((row["token_address"], row["strategy"], row["verdict"],
                          row["signal_wallets"]), (EARLY_GOOD, "convergence", "PASS", "3"))
        self.assertEqual(row["decisions"], "convergence=bought")
        self.go()                                           # the same token again: no new row
        self.assertEqual(len(rows(path)), 1)
        self.assertEqual(pos["cost_usd"], 5)
        self.assertEqual(list(rows(os.path.join(self.tmp.name, "convergence", "entries.csv"))[0]),
                         ENTRY_COLUMNS)


if __name__ == "__main__":
    unittest.main()
