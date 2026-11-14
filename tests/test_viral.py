"""Checks for the "viral trigger" paper experiment (screener/viral.py, run inside the launch
recorder by launch_record_bot.py): the name memory, the watchlist, the flags, the liquidity
checks, v1's buys and exits, the files and the reports. Fake time and fake answers only:
nothing here touches the network or a wallet."""

import asyncio
import copy
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launch_bot  # noqa: E402
import launch_record_bot as lrb  # noqa: E402
from screener import pumpfeed as pf  # noqa: E402
from screener import viral as vr  # noqa: E402
from screener.launch_record import LaunchRecorder  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402
from tests.test_launch_record import create_line, key  # noqa: E402

CFG = load_config()
T0 = 1_800_000_000          # 2027-01-15 08:00:00 UTC
DAY = 86400
MIN = 60


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def pair(mint, liquidity=60_000, price="0.001", dex="pumpswap"):
    return {"baseToken": {"address": mint, "symbol": "X"}, "pairAddress": f"POOL-{mint}",
            "dexId": dex, "priceUsd": price, "liquidity": {"usd": liquidity},
            "pairCreatedAt": (T0 - DAY) * 1000}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name
        self.now = [T0]

    def viral(self, cfg=None, history=True):
        """A Viral at T0. history=True: its name memory counts as 2 days old (the
        first-of-name rule is known); False: it has just started."""
        v = vr.Viral(cfg or CFG, self.d, lambda: self.now[0])
        if history:
            v.memory.since = T0 - 2 * DAY
        return v

    def folder(self, *parts):
        return os.path.join(self.d, "viral", *parts)

    def flags(self):
        out = []
        for name in sorted(os.listdir(self.folder())):
            if name.startswith("flags-"):
                out += rows(self.folder(name))
        return {r["token_address"]: r for r in out}


class NormalizeTests(unittest.TestCase):
    def test_symbol_key(self):
        self.assertEqual(vr.symbol_key("$Trump "), "trump")
        self.assertEqual(vr.symbol_key("TRUMP"), "trump")
        self.assertEqual(vr.symbol_key("Tr-U_mp!"), "trump")
        self.assertEqual(vr.symbol_key("ＴＲＵＭＰ"), "trump")           # full-width letters
        self.assertEqual(vr.symbol_key("🚀"), "")

    def test_words(self):
        self.assertEqual(vr.words("Donald Trump's Cat"), ["donald", "trump", "s", "cat"])
        self.assertEqual(vr.words("snake_case-name"), ["snake", "case", "name"])


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.w = vr.Watchlist(CFG["viral"]["watchlist"])

    def name(self, name, symbol="ZZZ"):
        entry = self.w.match(name, symbol)
        return entry and entry["name"]

    def test_symbol_and_name_matches(self):
        self.assertEqual(self.name("whatever", "$TRUMP"), "Donald Trump")
        self.assertEqual(self.name("Trump Cat"), "Donald Trump")
        self.assertEqual(self.name("Donald Trump Coin"), "Donald Trump")
        self.assertEqual(self.name("baby elon"), "Elon Musk")
        self.assertEqual(self.name("Mr Beast token"), "MrBeast")
        self.assertEqual(self.name("x", "MRBEAST"), "MrBeast")
        self.assertEqual(self.w.match("Tesla Dog", "TDOG")["category"], "brand")

    def test_no_match_inside_another_word(self):
        self.assertIsNone(self.name("Strumpet"))
        self.assertIsNone(self.name("Trumpet", "TRUMPET"))
        self.assertIsNone(self.name("Elongated Muskrat", "LONG"))
        self.assertIsNone(self.name("Just Frog", "FROG"))

    def test_a_term_needs_three_letters(self):
        with self.assertRaises(ValueError):
            vr.Watchlist([{"name": "CZ", "category": "crypto", "terms": ["cz"]}])

    def test_the_configured_watchlist(self):
        entries = CFG["viral"]["watchlist"]
        self.assertTrue(45 <= len(entries) <= 55, len(entries))
        self.assertEqual({e["category"] for e in entries},
                         {"politician", "celebrity", "crypto", "brand"})
        self.assertEqual(len({e["name"] for e in entries}), len(entries))


class NameMemoryTests(unittest.TestCase):
    def memory(self, since=T0 - 2 * DAY):
        return vr.NameMemory(30 * MIN, 24 * 3600, 10, since)

    def test_previous_30_minutes_and_first_of_name(self):
        m = self.memory()
        self.assertEqual(m.observe("frog", "a", "FROG", "Frog", T0)[:2], (0, "yes"))
        self.assertEqual(m.observe("frog", "b", "FROG", "Frog", T0 + 10 * MIN)[:2], (1, "no"))
        self.assertEqual(m.observe("frog", "c", "FROG", "Frog", T0 + 35 * MIN)[:2], (1, "no"))
        # 25 hours later: the earlier ones are more than 24 h ago
        self.assertEqual(m.observe("frog", "d", "FROG", "Frog", T0 + 25 * 3600)[:2], (0, "yes"))

    def test_unknown_while_the_memory_is_young(self):
        m = self.memory(since=T0 - 3600)
        self.assertEqual(m.observe("frog", "a", "FROG", "Frog", T0)[1], "unknown")
        self.assertEqual(m.observe("frog", "b", "FROG", "Frog", T0 + 60)[1], "no")

    def test_the_tenth_follower_within_30_minutes_makes_a_burst_once(self):
        m = self.memory()
        m.observe("frog", "first", "FROG", "Frog", T0)
        bursts = [m.observe("frog", f"f{i}", "FROG", "Frog", T0 + i * MIN)[2] for i in range(1, 13)]
        self.assertEqual([b is not None for b in bursts], [False] * 9 + [True, False, False])
        self.assertEqual(bursts[9]["mint"], "first")

    def test_followers_after_30_minutes_do_not_count(self):
        m = self.memory()
        m.observe("frog", "first", "FROG", "Frog", T0)
        for i in range(9):
            m.observe("frog", f"f{i}", "FROG", "Frog", T0 + i * MIN)
        self.assertIsNone(m.observe("frog", "late", "FROG", "Frog", T0 + 31 * MIN)[2])

    def test_a_token_that_is_not_first_starts_no_window(self):
        m = self.memory()
        m.observe("frog", "a", "FROG", "Frog", T0)
        for i in range(1, 12):
            _, _, burst, _ = m.observe("frog", f"b{i}", "FROG", "Frog", T0 + i * 60)
        self.assertEqual(set(m.firsts), {"frog"})
        self.assertEqual(m.firsts["frog"]["mint"], "a")

    def test_state_round_trip(self):
        m = self.memory()
        m.observe("frog", "a", "FROG", "Frog", T0)
        again = self.memory(since=T0)
        again.load(json.loads(json.dumps(m.to_state())), T0 + 60)
        self.assertEqual(again.since, T0 - 2 * DAY)
        self.assertEqual(again.observe("frog", "b", "FROG", "Frog", T0 + 60)[:2], (1, "no"))


class RecordingTests(Base):
    def test_every_launch_gets_a_row(self):
        v = self.viral()
        v.on_launch("m1", "Frog", "FROG", T0)
        v.on_launch("m2", "Frog again", "$frog", T0 + 60)
        v.on_launch("m3", "Trump Cat", "TCAT", T0 + 120)
        v.save(T0 + 130)
        got = rows(self.folder("launches-2027-01-15.csv"))
        self.assertEqual(list(got[0]), vr.LAUNCH_COLUMNS)
        self.assertEqual([(r["token_address"], r["symbol_key"], r["same_symbol_prev_30m"],
                           r["first_of_name_24h"], r["watchlist_entry"], r["watchlist_category"])
                          for r in got],
                         [("m1", "frog", "0", "yes", "", ""), ("m2", "frog", "1", "no", "", ""),
                          ("m3", "tcat", "0", "yes", "Donald Trump", "politician")])

    def test_a_watchlist_match_is_flagged_at_once(self):
        v = self.viral()
        v.on_launch("m3", "Trump Cat", "TCAT", T0)
        v.save(T0 + 1)
        f = self.flags()["m3"]
        self.assertEqual((f["by_watchlist"], f["watchlist_entry"], f["by_name_burst"]),
                         ("yes", "Donald Trump", "no"))
        self.assertEqual(f["flagged_utc"], "2027-01-15T08:00:00Z")
        self.assertEqual(f["watch_until_utc"], "2027-01-16T08:00:00Z")

    def test_a_name_burst_flags_the_first_token_at_the_tenth_follower(self):
        v = self.viral()
        v.on_launch("first", "Frog", "FROG", T0)
        for i in range(1, 10):
            v.on_launch(f"f{i}", "Frog", "FROG", T0 + i * MIN)
        v.save(T0 + 10 * MIN)
        self.assertNotIn("first", self.flags())                      # only 9 followers so far
        v.on_launch("f10", "Frog", "FROG", T0 + 12 * MIN)
        v.on_launch("f11", "Frog", "FROG", T0 + 13 * MIN)
        v.save(T0 + 14 * MIN)
        flags = self.flags()
        self.assertEqual(set(flags), {"first"})                      # never the copies
        f = flags["first"]
        self.assertEqual((f["by_name_burst"], f["name_burst_utc"], f["created_utc"]),
                         ("yes", "2027-01-15T08:12:00Z", "2027-01-15T08:00:00Z"))
        self.assertEqual(f["same_symbol_followers_30m"], "11")       # updated as they come

    def test_no_burst_while_first_of_name_is_unknown(self):
        v = self.viral(history=False)
        v.on_launch("first", "Frog", "FROG", T0)
        for i in range(1, 12):
            v.on_launch(f"f{i}", "Frog", "FROG", T0 + i * MIN)
        v.save(T0 + 13 * MIN)
        self.assertEqual(self.flags(), {})
        self.assertEqual(rows(self.folder("launches-2027-01-15.csv"))[0]["first_of_name_24h"],
                         "unknown")

    def test_an_error_never_escapes(self):
        v = self.viral()
        v.memory.observe = None                                      # broken on purpose
        with self.assertLogs("viral", level="ERROR"):
            v.on_launch("m1", "Frog", "FROG", T0)                    # logged, not raised

    def test_a_symbol_with_no_letters_is_recorded_without_a_burst(self):
        v = self.viral()
        v.on_launch("m1", "🚀", "🚀", T0)
        v.save(T0 + 1)
        r = rows(self.folder("launches-2027-01-15.csv"))[0]
        self.assertEqual((r["symbol_key"], r["first_of_name_24h"]), ("", "unknown"))


class CheckTests(Base):
    def flagged(self, mint="m1"):
        v = self.viral()
        v.on_launch(mint, "Trump Cat", "TCAT", T0)
        return v

    def trader(self, v):
        return v.traders["v1"]

    def test_only_flagged_tokens_are_checked(self):
        v = self.viral()
        v.on_launch("plain", "Frog", "FROG", T0)
        self.assertEqual(v.to_check(T0 + 60), [])
        v.on_launch("m1", "Trump Cat", "TCAT", T0 + 1)
        self.assertEqual(v.to_check(T0 + 60), ["m1"])

    def test_below_the_liquidity_nothing_is_bought(self):
        v = self.flagged()
        v.apply([pair("m1", liquidity=49_999)], T0 + 60)
        v.apply([pair("m1", liquidity=None)], T0 + 120)
        v.save(T0 + 121)
        f = self.flags()["m1"]
        self.assertEqual((f["checks"], f["max_liquidity_usd"], f["reached_liquidity_utc"],
                          f["bought_utc"]), ("2", "49999", "", ""))
        self.assertEqual(self.trader(v).open_positions, [])

    def test_at_the_liquidity_v1_buys_ten_dollars_with_slippage_once(self):
        v = self.flagged()
        v.apply([pair("m1", liquidity=50_000, price="0.002")], T0 + 60)
        pos = self.trader(v).open_positions[0]
        self.assertAlmostEqual(pos["entry_price"], 0.002 * 1.015)
        self.assertEqual(pos["cost_usd"], 10)
        v.apply([pair("m1", liquidity=80_000, price="0.002")], T0 + 120)
        v.save(T0 + 121)
        journal = rows(self.folder("v1", "journal.csv"))
        self.assertEqual([r["action"] for r in journal], ["BUY"])
        self.assertIn("viral flag and enough liquidity", journal[0]["reason"])
        entries = rows(self.folder("v1", "entries.csv"))
        self.assertEqual(entries[0]["buy_slippage_pct"], "1.5")
        f = self.flags()["m1"]
        self.assertEqual((f["reached_liquidity_utc"], f["bought_utc"], f["bought_by"]),
                         ("2027-01-15T08:01:00Z", "2027-01-15T08:01:00Z", "v1"))
        self.assertNotIn("m1", [r["token_address"] for r in v._watched(T0 + 180)])

    def test_the_watch_ends_after_watch_hours(self):
        v = self.flagged()
        self.assertEqual(v.to_check(T0 + 23 * 3600), ["m1"])
        self.assertEqual(v.to_check(T0 + 24 * 3600 + 1), [])
        v.apply([pair("m1", liquidity=500_000)], T0 + 24 * 3600 + 1)
        self.assertEqual(self.trader(v).open_positions, [])

    def test_the_watched_list_is_capped_newest_first(self):
        cfg = copy.deepcopy(CFG)
        cfg["viral"]["max_watched"] = 2
        v = self.viral(cfg)
        for i in range(4):
            v.on_launch(f"m{i}", "Trump Cat", "TCAT", T0 + i)
        self.assertEqual(v.to_check(T0 + 10), ["m3", "m2"])

    def test_stop_loss_at_minus_25(self):
        v = self.flagged()
        v.apply([pair("m1", price="1.0")], T0 + 60)                   # entry 1.015
        v.apply([pair("m1", price="0.77")], T0 + 120)                 # -24.1%
        self.assertEqual(len(self.trader(v).open_positions), 1)
        v.apply([pair("m1", price="0.75")], T0 + 180)                 # -26.1%
        self.assertEqual(self.trader(v).open_positions, [])
        sell = [r for r in rows(self.folder("v1", "journal.csv")) if r["action"] == "SELL"]
        self.assertIn("stop loss", sell[0]["reason"])

    def test_everything_sold_after_60_minutes_with_the_costs(self):
        v = self.flagged()
        v.apply([pair("m1", price="1.0")], T0 + 60)
        v.apply([pair("m1", price="3.0")], T0 + 60 + 59 * MIN)       # no take profit
        self.assertEqual(len(self.trader(v).open_positions), 1)
        v.apply([pair("m1", price="1.0")], T0 + 60 + 60 * MIN)
        self.assertEqual(self.trader(v).open_positions, [])
        sell = [r for r in rows(self.folder("v1", "journal.csv")) if r["action"] == "SELL"][0]
        self.assertIn("time exit", sell["reason"])
        self.assertAlmostEqual(float(sell["pnl_usd"]), 10 * (1 / 1.015 - 1) - 0.30, places=2)

    def test_an_open_position_is_checked_with_the_flags(self):
        v = self.flagged()
        v.apply([pair("m1")], T0 + 60)
        v.on_launch("m2", "Elon Dog", "EDOG", T0 + 70)
        self.assertEqual(v.to_check(T0 + 120), ["m1", "m2"])

    def test_a_failed_check_changes_nothing_but_the_counter(self):
        v = self.flagged()
        with self.assertLogs("viral", level="WARNING"):
            v.check_failed(T0 + 60, RuntimeError("502"))
        v.save(T0 + 61)
        with open(self.folder("health.json")) as fh:
            health = json.load(fh)
        self.assertEqual(health["last_hour"]["check_errors"], 1)
        self.assertEqual(self.flags()["m1"]["checks"], "0")

    def test_the_start_time_is_recorded_once(self):
        self.now[0] = T0 + 0.7
        v = self.viral()
        v.save(T0 + 1)
        with open(self.folder("v1", "positions.json")) as fh:
            self.assertEqual(json.load(fh)["started_utc"], "2027-01-15T08:00:00+00:00")
        self.now[0] = T0 + DAY
        self.viral().save(T0 + DAY)
        with open(self.folder("v1", "positions.json")) as fh:
            self.assertEqual(json.load(fh)["started_utc"], "2027-01-15T08:00:00+00:00")

    def test_a_restart_keeps_the_flags_and_the_name_memory(self):
        v = self.flagged()
        v.on_launch("f0", "Frog", "FROG", T0 + 5)
        v.save(T0 + 10)
        v.save_state(T0 + 10)
        self.now[0] = T0 + 3600
        again = vr.Viral(CFG, self.d, lambda: self.now[0])
        self.assertEqual(again.to_check(T0 + 3600), ["m1"])
        self.assertEqual(again.memory.observe("frog", "f1", "FROG", "Frog", T0 + 3600)[1], "no")
        self.assertEqual(again.memory.since, v.memory.since)


class RunnerTests(Base):
    def runner(self, api):
        cfg = copy.deepcopy(CFG)
        return lrb.RecordRunner(cfg, self.d, clock=lambda: self.now[0], viral_api=api)

    def test_the_recorder_feeds_the_viral_rows_and_recording_is_unchanged(self):
        def run(with_viral):
            with tempfile.TemporaryDirectory() as d:
                cfg = copy.deepcopy(CFG)
                cfg["launch_record"]["sample_pct"] = 100.0
                rec = LaunchRecorder(cfg, d, clock=lambda: T0)
                seen = []
                if with_viral:
                    rec.on_launch = lambda *a: seen.append(a)
                rec.connected(T0 - 1, "test")
                rec.on_logs([create_line(key(1), key(2), T0 - 1, "Trump Cat", "TCAT")], False, T0, 1)
                rec.on_logs([create_line(key(3), key(2), T0, "Frog", "FROG")], False, T0 + 1, 1)
                rec.finish_all()
                rec.flush(T0 + 2)
                health = rec.health(T0 + 2)
                out = {n: open(os.path.join(d, "launch-record", n)).read()
                       for n in os.listdir(os.path.join(d, "launch-record")) if n.endswith(".csv")}
                return out, health["days"], seen
        plain, plain_days, _ = run(False)
        hooked, hooked_days, seen = run(True)
        self.assertEqual(plain, hooked)
        self.assertEqual(plain_days, hooked_days)
        self.assertEqual([(a[1], a[2]) for a in seen], [("Trump Cat", "TCAT"), ("Frog", "FROG")])

    def test_a_broken_hook_never_stops_the_recording(self):
        rec = LaunchRecorder(CFG, self.d, clock=lambda: T0)

        def boom(*a):
            raise RuntimeError("boom")
        rec.on_launch = boom
        rec.on_logs([create_line(key(1), key(2), T0)], False, T0, 1)
        self.assertEqual(len(rec.launches), 1)

    def test_a_viral_step_checks_buys_and_saves(self):
        class Api:
            asked = []

            def pairs_for_tokens(self, addresses):
                self.asked.append(list(addresses))
                return [pair(a) for a in addresses]
        api = Api()
        runner = self.runner(api)
        runner.viral.memory.since = T0 - 2 * DAY
        runner.recorder.on_logs([create_line(key(1), key(2), T0, "Elon Cat", "ECAT")], False, T0, 1)
        self.now[0] = T0 + 60
        asyncio.run(runner.viral_step())
        mint = pf.b58encode(key(1))
        self.assertEqual(api.asked, [[mint]])
        self.assertEqual(runner.viral.traders["v1"].open_positions[0]["address"], mint)
        self.assertEqual(len(rows(self.folder("v1", "journal.csv"))), 1)
        self.assertTrue(rows(self.folder("launches-2027-01-15.csv")))

    def test_a_failing_dexscreener_is_counted_and_nothing_else_happens(self):
        class Down:
            def pairs_for_tokens(self, addresses):
                raise RuntimeError("answered with error 502")
        runner = self.runner(Down())
        runner.recorder.on_logs([create_line(key(1), key(2), T0, "Elon Cat", "ECAT")], False, T0, 1)
        self.now[0] = T0 + 60
        with self.assertLogs("viral", level="WARNING"):
            asyncio.run(runner.viral_step())
        with open(self.folder("health.json")) as fh:
            self.assertEqual(json.load(fh)["last_hour"]["check_errors"], 1)
        self.assertEqual(rows(self.folder("v1", "journal.csv")), [])

    def test_no_flag_no_request(self):
        class Never:
            def pairs_for_tokens(self, addresses):
                raise AssertionError("asked")
        runner = self.runner(Never())
        runner.recorder.on_logs([create_line(key(1), key(2), T0, "Frog", "FROG")], False, T0, 1)
        asyncio.run(runner.viral_step())                              # no AssertionError

    def test_turned_off_there_is_no_viral_and_no_folder(self):
        cfg = copy.deepcopy(CFG)
        cfg["viral"]["enabled"] = False
        runner = lrb.RecordRunner(cfg, self.d)
        self.assertIsNone(runner.viral)
        self.assertFalse(os.path.exists(self.folder()))


class ReportTests(Base):
    def make_results(self):
        v = self.viral()
        v.on_launch("w1", "Trump Cat", "TCAT", T0)                    # watchlist, reaches, bought
        v.on_launch("w2", "Elon Dog", "EDOG", T0 + 1)                 # watchlist, never reaches
        v.on_launch("first", "Frog", "FROG", T0 + 2)                  # a burst, reaches, bought
        for i in range(1, 11):
            v.on_launch(f"f{i}", "Frog", "FROG", T0 + 2 + i * MIN)
        v.apply([pair("w1"), pair("w2", liquidity=10_000), pair("first")], T0 + 20 * MIN)
        v.save(T0 + 20 * MIN)

    def test_viral_lines(self):
        from screener.compare import viral_lines
        self.make_results()
        (line, _) = viral_lines(self.folder(), "2027-01-15")
        self.assertIn("2027-01-15: name_burst 1 (reached the liquidity 1, bought 1); "
                      "watchlist_match 2 (reached the liquidity 1, bought 1); bought in all 2", line)
        self.assertIn("since the start: name_burst 1", line)
        self.assertEqual(viral_lines(os.path.join(self.d, "nothing"), "2027-01-15")[0],
                         "**Viral flags:** none recorded yet.")

    def test_the_daily_comparison_has_a_v1_column_and_the_lines(self):
        import io
        from unittest import mock
        import compare
        self.make_results()
        cfg = dict(CFG, files={"data_folder": self.d})
        with mock.patch.object(compare, "load_config", lambda: cfg), \
                mock.patch.dict(os.environ, {"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""}), \
                mock.patch("sys.argv", ["compare.py", "--date", "2027-01-15"]), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(compare.main(), 0)
        text = out.getvalue()
        header = next(x for x in text.splitlines() if x.startswith("| | main"))
        self.assertTrue(header.rstrip().endswith("| viral v1 |"), header)
        self.assertIn("| viral v1 | 0 |", text)                       # in the checklist
        self.assertIn("**Viral flags**", text)
        self.assertIn("| viral: server |", text)

    def test_the_health_row(self):
        from screener.health import INFO, OK, WARN, add_viral
        rows_ = []

        def add(name, status, detail, problem=None):
            rows_.append((name, status, detail))
        add_viral(add, self.d, CFG, datetime.fromtimestamp(T0, timezone.utc))
        self.assertEqual(rows_[-1][1], INFO)
        self.make_results()
        now = datetime.fromtimestamp(T0 + 25 * MIN, timezone.utc)
        add_viral(add, self.d, CFG, now)
        name, status, detail = rows_[-1]
        self.assertEqual((name, status), ("viral: server", OK))
        self.assertIn("2 by watchlist_match", detail)
        self.assertIn("1 flagged by name_burst", detail)
        self.assertIn("v1: 2 open", detail)
        add_viral(add, self.d, CFG, datetime.fromtimestamp(T0 + 5 * 3600, timezone.utc))
        self.assertEqual(rows_[-1][1], WARN)                          # nothing pushed for 5 h


class SetupTests(unittest.TestCase):
    def test_the_fixed_numbers(self):
        c = CFG["viral"]
        self.assertEqual((c["burst_window_minutes"], c["first_of_name_hours"], c["min_followers"],
                          c["min_liquidity_usd"], c["buy_amount_usd"], c["buy_slippage_pct"],
                          c["round_trip_cost_pct"]), (30, 24, 10, 50_000, 10, 1.5, 3))
        (v1,) = c["versions"]
        self.assertEqual((v1["name"], v1["stop_loss_pct"], v1["max_hold_minutes"],
                          v1.get("take_profit_pct"), v1.get("trailing_stop_pct")),
                         ("v1", 25, 60, None, None))
        liquid = {v["name"]: v for v in CFG["liquid"]["versions"]}
        self.assertEqual((liquid["l6"]["stop_loss_pct"], liquid["l6"]["max_hold_minutes"]),
                         (v1["stop_loss_pct"], v1["max_hold_minutes"]))
        self.assertEqual((CFG["liquid"]["buy_slippage_pct"], CFG["liquid"]["round_trip_cost_pct"]),
                         (c["buy_slippage_pct"], c["round_trip_cost_pct"]))

    def test_files_are_pushed_and_the_state_stays(self):
        for path in ("data/viral/launches-2027-01-15.csv", "data/viral/flags-2027-01-15.csv",
                     "data/viral/health.json", "data/viral/v1/journal.csv",
                     "data/viral/v1/positions.json", "data/viral/v1/entries.csv"):
            self.assertNotEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                               cwd=HERE).returncode, 0, path)
        for path in ("data/viral/state.json", "data/viral/v1/positions.json.tmp"):
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                            cwd=HERE).returncode, 0, path)
        with open(os.path.join(HERE, "deploy", "push_results.sh")) as fh:
            self.assertIn("data/viral)", fh.read())

    def test_the_service_restarts_when_the_section_changes(self):
        self.assertIn("viral", launch_bot.CONFIG_SECTIONS)

    def test_no_wallet_words(self):
        with open(os.path.join(HERE, "screener", "viral.py")) as fh:
            source = fh.read().lower()
        for word in ("private_key", "keypair", "sign_transaction", "sendtransaction"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
