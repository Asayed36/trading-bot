"""Checks for the ticker mentions in the X posts (screener/xmentions.py) and the "Posts seen late"
reasons (screener/xposts.py), the report sections, the health row count and the daily
comparison line. Recording only: no X request, no buy or sell. Every post and DexScreener answer
here is fake. Run with:  python -m unittest -v
"""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

import xposts_bot  # noqa: E402
from run import load_config  # noqa: E402
from screener import health  # noqa: E402
from screener import xmentions as xm  # noqa: E402
from screener.api import ApiError  # noqa: E402
from screener.xposts import Watcher, XError  # noqa: E402
from screener.xposts_report import build  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = running(load_config())
POSTED = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
SEEN = POSTED + timedelta(seconds=90)
SOL_MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
EVM_TOKEN = "0x6982508145454ce325ddbe47a25d4ec3d2311933"


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def pair(chain, address, symbol, price, liquidity, cap=1e6, h1=2.5, pair_address=None,
         name=None):
    return {"chainId": chain, "pairAddress": pair_address or f"P-{address[:6]}-{liquidity}",
            "baseToken": {"address": address, "symbol": symbol, "name": name or symbol},
            "priceUsd": str(price), "liquidity": {"usd": liquidity}, "volume": {"h24": 5000},
            "marketCap": cap, "priceChange": {"h1": h1}}


class FakeDex:
    """search_pairs and pairs_on_chain like DexScreener's answers. `price` (a function of the
    call number) moves the price of every pair; `fail` makes the next calls raise."""

    def __init__(self):
        self.calls, self.fail, self.factor = [], 0, 1.0
        self.search = {
            # an ambiguous ticker: three different WIF tokens, the highest liquidity on solana
            "WIF": [pair("solana", "WifMint111", "WIF", 2.0, 900_000, cap=2e9),
                    pair("solana", "WifCopy222", "wif", 0.001, 4_000),
                    pair("bsc", "0xwifcopy3", "WIF", 0.01, 20_000),
                    pair("solana", "OtherMint", "WIFHAT", 0.5, 2_000_000)],      # not exact
            "BTC": [pair("ethereum", "0xbtc000", "BTC", 90_000, 5_000_000, cap=1.8e12)],
            "MSTR": [pair("solana", "MstrCopy1", "MSTR", 0.002, 1_500),
                     pair("base", "0xmstrcopy", "MSTR", 0.0001, 300)],
            EVM_TOKEN: [pair("ethereum", "0x6982508145454Ce325dDbE47a25d4ec3d2311933", "PEPE",
                             0.00001, 30_000_000, cap=4e9)],
        }
        self.chain = {SOL_MINT: [pair("solana", SOL_MINT, "POPCAT", 0.4, 600_000, cap=4e8)]}

    def _check(self):
        if self.fail:
            self.fail -= 1
            raise ApiError("DexScreener is down")

    def _move(self, pairs):
        out = []
        for p in pairs:
            p = json.loads(json.dumps(p))
            p["priceUsd"] = str(float(p["priceUsd"]) * self.factor)
            out.append(p)
        return out

    def search_pairs(self, query):
        self.calls.append(("search", query))
        self._check()
        return self._move(self.search.get(query, []))

    def pairs_on_chain(self, chain, addresses):
        self.calls.append(("chain", chain, tuple(addresses)))
        self._check()
        found = []
        for a in addresses:
            found += self.chain.get(a, [])
            for pairs in self.search.values():
                found += [p for p in pairs if p["chainId"] == chain
                          and p["baseToken"]["address"].lower() == a.lower()]
        return self._move(found)


def post(text, post_id="1", account="saylor", posted=POSTED, seen=SEEN):
    return [account, post_id, iso(posted), iso(seen), text]


def read(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def write_btc(folder, start, minutes, first=100_000.0, step=10.0):
    """data/market/prices-*.csv: BTC rising `step` dollars a minute from `first`."""
    os.makedirs(folder, exist_ok=True)
    files = {}
    for i in range(minutes):
        t = start + timedelta(minutes=i)
        files.setdefault(f"{t:%Y-%m-%d}", []).append(
            f"{t:%Y-%m-%d %H:%M}:00,{first + step * i:.2f},3000,140")
    for day, lines in files.items():
        with open(os.path.join(folder, f"prices-{day}.csv"), "w") as fh:
            fh.write("time_utc,btc_usd,eth_usd,sol_usd\n" + "\n".join(lines) + "\n")


class FindTests(unittest.TestCase):
    def test_cashtags_addresses_and_dollar_amounts(self):
        text = (f"Buy $wif and $PEPE, not $10M or $1.5B or $5. Mint {SOL_MINT} and "
                f"{EVM_TOKEN.upper().replace('0X', '0x')}; email a$b, price$X, $WIF again "
                "https://t.co/AbCdEf1234567890AbCdEf1234567890xy")
        found, dropped = xm.find_mentions(text)
        self.assertEqual(found, [("cashtag", "$WIF"), ("cashtag", "$PEPE"), ("solana", SOL_MINT),
                                 ("evm", EVM_TOKEN)])
        self.assertEqual(dropped, 0)

    def test_lengths_and_boundaries(self):
        self.assertEqual(xm.find_mentions("$A $AB $ABCDEFGHIJ $ABCDEFGHIJK $AB_C")[0],
                         [("cashtag", "$AB"), ("cashtag", "$ABCDEFGHIJ")])
        self.assertEqual(xm.find_mentions("$1INCH $10M $228M")[0], [])     # starts with a digit
        self.assertEqual(xm.find_mentions("A" * 32 + " " + "abc" * 12)[0], [])  # no digit: a word
        self.assertEqual(xm.find_mentions("0x" + "a" * 39 + " 0x" + "g" * 40)[0], [])

    def test_at_most_5_a_post_the_rest_dropped(self):
        found, dropped = xm.find_mentions(" ".join(f"$C{i}X" for i in range(8)))
        self.assertEqual(len(found), 5)
        self.assertEqual(dropped, 3)

    def test_reposts_are_skipped(self):
        self.assertFalse(xm.is_original("RT @someone: $WIF"))
        self.assertTrue(xm.is_original("$WIF"))


class MentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = self.tmp.name
        self.dex = FakeDex()
        self.clock = [SEEN]
        self.m = xm.Mentions(CFG, self.data, self.dex, clock=lambda: self.clock[0])
        write_btc(os.path.join(self.data, "market"), POSTED - timedelta(hours=2), 60 * 30)

    def at(self, minutes=0, seconds=0):
        self.clock[0] = POSTED + timedelta(minutes=minutes, seconds=seconds)
        self.m.tick()

    def rows(self, day="2026-11-20"):
        return read(os.path.join(self.data, "xposts", f"mentions-{day}.csv"))

    def health(self):
        with open(os.path.join(self.data, "xposts", "mentions_health.json")) as fh:
            return json.load(fh)

    def test_a_post_with_no_mentions_adds_nothing_and_asks_nothing(self):
        self.assertEqual(self.m.add_posts([post("Bitcoin is hope. $10M raised. https://t.co/x")]), 0)
        self.at(seconds=100)
        self.assertEqual(self.dex.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.data, "xposts", "mentions-2026-11-20.csv")))

    def test_an_ambiguous_ticker_takes_the_most_liquid_exact_symbol_and_counts_the_candidates(self):
        self.m.add_posts([post("$WIF to the moon")])
        self.at(seconds=100)
        (row,) = self.rows()
        self.assertEqual(self.dex.calls, [("search", "WIF")])        # looked up once
        self.assertEqual((row["status"], row["chain"], row["token_address"], row["symbol"]),
                         ("identified", "solana", "WifMint111", "WIF"))
        self.assertEqual(row["candidates"], "3")      # WIFHAT is not an exact match
        self.assertEqual(row["large"], "no")
        self.assertEqual((row["price_first_usd"], row["liquidity_first_usd"],
                          row["volume_24h_first_usd"], row["market_cap_first_usd"]),
                         ("2", "900000", "5000", "2000000000"))
        self.assertEqual(row["first_check_delay_seconds"], "100")
        self.assertEqual(row["change_1h_at_first_check_pct"], "2.5")
        # BTC +10 $ a minute: the hour before the post is 100,600 -> 101,200
        self.assertEqual(row["btc_change_1h_before_post_pct"], f"{(101200 / 100600 - 1) * 100:.3f}")

    def test_stock_tickers_are_kept_with_their_candidates(self):
        self.m.add_posts([post("$MSTR and $STRC")])
        self.at(seconds=100)
        by = {r["mention"]: r for r in self.rows()}
        self.assertEqual((by["$MSTR"]["status"], by["$MSTR"]["candidates"]), ("identified", "2"))
        self.assertEqual((by["$STRC"]["status"], by["$STRC"]["candidates"]), ("not found", "0"))

    def test_addresses_use_that_token_and_big_coins_are_large(self):
        self.m.add_posts([post(f"{SOL_MINT} {EVM_TOKEN} $BTC")])
        self.at(seconds=100)
        by = {r["mention"]: r for r in self.rows()}
        self.assertEqual((by[SOL_MINT]["symbol"], by[SOL_MINT]["chain"], by[SOL_MINT]["large"]),
                         ("POPCAT", "solana", "no"))
        self.assertEqual((by[EVM_TOKEN]["symbol"], by[EVM_TOKEN]["chain"], by[EVM_TOKEN]["large"]),
                         ("PEPE", "ethereum", "no"))     # $4 billion: under $5 billion
        self.assertEqual(by["$BTC"]["large"], "yes")
        self.assertIn(("chain", "solana", (SOL_MINT,)), self.dex.calls)
        self.assertIn(("search", EVM_TOKEN), self.dex.calls)
        self.assertTrue(xm.is_large("pepe", 6e9))

    def test_checkpoints_follow_the_post_and_late_ones_are_missed(self):
        self.m.add_posts([post("$WIF")])
        self.at(seconds=100)                                   # first check
        self.dex.factor = 1.10
        self.at(minutes=5, seconds=30)                         # 5 min: within 2 min
        self.dex.factor = 0.95
        self.at(minutes=18, seconds=10)                        # 15 min: past 15 + 3 min
        self.dex.factor = 1.20
        self.at(minutes=60, seconds=40)                        # 60 min
        self.at(minutes=1440 + 5)                              # 24 h
        (row,) = self.rows()
        self.assertEqual(row["at_5m_utc"], "2026-11-20T12:05:30Z")
        self.assertEqual(row["change_5m_pct"], "10.000")
        self.assertEqual(row["at_15m_utc"], "missed")
        self.assertEqual(row["price_15m_usd"], "")
        self.assertEqual(row["change_60m_pct"], "20.000")
        self.assertEqual(row["at_24h_utc"], "2026-11-21T12:05:00Z")
        # BTC over the same real times: first check 12:01 (101,210) .. 12:05 (101,250)
        self.assertEqual(row["btc_change_5m_pct"], f"{(101250 / 101210 - 1) * 100:.3f}")
        before = len(self.dex.calls)
        self.at(minutes=1440 + 30)
        self.assertEqual(len(self.dex.calls), before)          # finished: nothing more asked
        self.assertEqual(self.m.days, {})

    def test_nothing_is_asked_between_checkpoints(self):
        self.m.add_posts([post("$WIF")])
        self.at(seconds=100)
        for s in range(120, 300, 20):
            self.at(seconds=s)
        self.assertEqual(len(self.dex.calls), 1)
        self.at(minutes=5, seconds=10)
        self.assertEqual(len(self.dex.calls), 2)
        self.at(minutes=5, seconds=30)
        self.assertEqual(len(self.dex.calls), 2)               # 5 min done

    def test_a_post_seen_late_marks_the_early_checkpoints_missed(self):
        self.m.add_posts([post("$WIF", seen=POSTED + timedelta(minutes=40))])
        self.at(minutes=40, seconds=20)
        (row,) = self.rows()
        self.assertEqual((row["at_5m_utc"], row["at_15m_utc"], row["at_60m_utc"]),
                         ("missed", "missed", ""))
        self.assertEqual(row["first_check_delay_seconds"], str(40 * 60 + 20))

    def test_a_checkpoint_due_at_the_first_check_takes_that_answer(self):
        self.m.add_posts([post("$WIF", seen=POSTED + timedelta(minutes=5, seconds=10))])
        self.at(minutes=5, seconds=20)
        (row,) = self.rows()
        self.assertEqual(row["at_5m_utc"], "2026-11-20T12:05:20Z")
        self.assertEqual(row["change_5m_pct"], "0.000")
        self.assertEqual(len(self.dex.calls), 1)

    def test_a_failed_lookup_is_tried_again_then_given_up(self):
        self.dex.fail = 100
        self.m.add_posts([post("$WIF")])
        self.at(seconds=100)
        self.at(minutes=5)
        self.assertEqual(self.rows()[0]["status"], "pending")
        self.at(minutes=12)
        self.assertEqual(self.rows()[0]["status"], "lookup failed")
        n = len(self.dex.calls)
        self.at(minutes=13)
        self.assertEqual(len(self.dex.calls), n)
        day = self.health()["days"]["2026-11-20"]
        self.assertEqual((day["lookup_failed"], day["errors"]), (1, 3))

    def test_a_failed_checkpoint_request_is_tried_at_the_next_check(self):
        self.m.add_posts([post("$WIF")])
        self.at(seconds=100)
        self.dex.fail = 1
        self.at(minutes=5, seconds=5)
        self.assertEqual(self.rows()[0]["at_5m_utc"], "")
        self.at(minutes=5, seconds=25)
        self.assertEqual(self.rows()[0]["at_5m_utc"], "2026-11-20T12:05:25Z")

    def test_a_restart_keeps_following(self):
        self.m.add_posts([post("$WIF")])
        self.at(seconds=100)
        again = xm.Mentions(CFG, self.data, self.dex, clock=lambda: self.clock[0])
        self.clock[0] = POSTED + timedelta(minutes=5, seconds=20)
        again.tick()
        self.assertEqual(self.rows()[0]["at_5m_utc"], "2026-11-20T12:05:20Z")
        self.assertEqual(again.add_posts([post("$WIF")]), 0)  # the same post is not added twice

    def test_counts_in_the_health_file_and_the_cap(self):
        self.m.add_posts([post(" ".join(f"$C{i}X" for i in range(7)), "2"), post("hello", "3")])
        self.at(seconds=100)
        day = self.health()["days"]["2026-11-20"]
        self.assertEqual((day["posts_with_mentions"], day["mentions"], day["dropped_by_cap"],
                          day["not_found"], day["requests"]), (1, 5, 2, 5, 5))

    def test_it_never_raises_into_the_watcher(self):
        class Broken:
            def search_pairs(self, q):
                raise RuntimeError("anything")
            pairs_on_chain = search_pairs
        m = xm.Mentions(CFG, self.data, Broken(), clock=lambda: SEEN)
        m.add_posts([post("$WIF")])
        m.tick()
        self.assertEqual(m.add_posts([["bad row"]]), 0)

    def test_the_bot_hands_new_posts_over_without_any_x_request(self):
        class Watch:
            c = CFG["xposts"]

            def run_once(self, now, out):
                return [post("$WIF")]
        bot = xposts_bot.Bot(Watch(), self.data, self.m)
        bot.run_once(SEEN, lambda *_: None)
        self.assertEqual(self.rows()[0]["mention"], "$WIF")
        self.assertIsNone(xposts_bot.make_mentions(
            dict(CFG, xposts=dict(CFG["xposts"], mentions=False)), self.data))

    def test_the_check_loop_stops_when_asked(self):
        ticks, stops = [], iter([False, False, True])
        m = type("M", (), {"tick": lambda self: ticks.append(1)})()
        xposts_bot.mention_checks(m, 20, lambda: next(stops), sleep=lambda s: None)
        self.assertEqual(len(ticks), 2)


class LateTests(unittest.TestCase):
    """Why a post was seen more than 3 minutes late."""

    class Api:
        def __init__(self, posts):
            self.posts_by, self.calls = posts, []

        def lookup(self, handles):
            return {h.lower(): str(i) for i, h in enumerate(handles)}, []

        def posts(self, user_id, n, since_id=None, start_time=None):
            self.calls.append(user_id)
            got = self.posts_by.pop(user_id, [])
            if isinstance(got, Exception):
                raise got
            return got, {}

        def cost_headers(self):
            return {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def watcher(self, api, **c):
        cfg = dict(CFG, xposts=dict(CFG["xposts"], accounts=["a", "b"], **c))
        return Watcher(cfg, self.tmp.name, api, clock=lambda: POSTED)

    def late(self, day="2026-11-20"):
        path = os.path.join(self.tmp.name, "xposts", f"late-{day}.csv")
        return read(path) if os.path.exists(path) else []

    def test_a_daily_limit_then_the_backlog_is_late_for_that_reason(self):
        api = self.Api({})
        w = self.watcher(api, max_posts_per_day=5)
        w.run_once(POSTED)                                     # both accounts asked, 0 posts
        w.state["days"]["2026-11-20"]["posts_read"] = 5        # the day's limit is used
        w.run_once(POSTED + timedelta(minutes=2))              # nobody asked: limit
        nxt = datetime(2026, 11, 21, 0, 0, 30, tzinfo=timezone.utc)
        api.posts_by = {"0": [{"id": "9", "created_at": "2026-11-20T20:00:00.000Z", "text": "x"}]}
        w.run_once(nxt)
        (row,) = self.late("2026-11-21")
        self.assertEqual((row["account"], row["reason"]), ("a", "daily post limit"))
        self.assertEqual(row["minutes_late"], f"{(nxt - datetime(2026, 11, 20, 20, tzinfo=timezone.utc)).total_seconds() / 60:.1f}")
        skipped = w.state["days"]["2026-11-20"]["skipped"]
        self.assertEqual(skipped, {"a": {"daily post limit": 1}, "b": {"daily post limit": 1}})

    def test_on_time_posts_are_not_listed_and_other_is_the_default(self):
        api = self.Api({})
        w = self.watcher(api)
        w.run_once(POSTED)
        api.posts_by = {"0": [{"id": "5", "created_at": "2026-11-20T12:01:00.000Z", "text": "x"}],
                        "1": [{"id": "6", "created_at": "2026-11-20T11:50:00.000Z", "text": "y"}]}
        w.run_once(POSTED + timedelta(minutes=2))
        (row,) = self.late()
        self.assertEqual((row["account"], row["reason"]), ("b", "other"))

    def test_the_per_account_limit_and_x_errors_are_recorded(self):
        api = self.Api({"1": XError("X answered 503", 503)})
        w = self.watcher(api, max_posts_per_account_per_day=5)
        w.state.setdefault("days", {})["2026-11-20"] = {
            "posts_read": 0, "requests": 0, "user_lookups": 0, "errors": 0, "by_account": {"a": 5}}
        w.run_once(POSTED)
        self.assertEqual(w.state["days"]["2026-11-20"]["skipped"],
                         {"a": {"per-account limit": 1}, "b": {"X error or pause": 1}})
        self.assertEqual(w.state["accounts"]["b"]["held"], "X error or pause")
        api.posts_by = {"1": [{"id": "7", "created_at": "2026-11-20T11:55:00.000Z", "text": "z"}]}
        w.run_once(POSTED + timedelta(minutes=2))
        (row,) = self.late()
        self.assertEqual((row["account"], row["reason"]), ("b", "X error or pause"))
        self.assertNotIn("held", w.state["accounts"]["b"])

    def test_a_watcher_that_was_not_running(self):
        api = self.Api({})
        w = self.watcher(api)
        w.run_once(POSTED)
        later = POSTED + timedelta(minutes=30)
        api.posts_by = {"0": [{"id": "8", "created_at": "2026-11-20T12:10:00.000Z", "text": "x"}]}
        w.run_once(later)
        (row,) = self.late()
        self.assertEqual(row["reason"], "watcher not running")


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = self.tmp.name
        self.folder = os.path.join(self.data, "xposts")
        dex, clock = FakeDex(), [SEEN]
        write_btc(os.path.join(self.data, "market"), POSTED - timedelta(hours=2), 60 * 4)
        m = xm.Mentions(CFG, self.data, dex, clock=lambda: clock[0])
        m.add_posts([post("$WIF $BTC $MSTR $STRC", "1"), post(f"{SOL_MINT}", "2", account="toly")])
        for when, factor in ((SEEN + timedelta(seconds=10), 1.0),
                             (POSTED + timedelta(minutes=5, seconds=20), 1.04),
                             (POSTED + timedelta(minutes=15, seconds=20), 0.98),
                             (POSTED + timedelta(minutes=60, seconds=20), 1.10)):
            clock[0], dex.factor = when, factor
            m.tick()
        with open(os.path.join(self.folder, "posts-2026-11-20.csv"), "w") as fh:
            fh.write("account,post_id,posted_utc,seen_utc,text\n"
                     "saylor,1,2026-11-20T12:00:00Z,2026-11-20T12:01:30Z,$WIF\n"
                     "toly,2,2026-11-20T12:00:00Z,2026-11-20T12:01:30Z,mint\n"
                     "toly,3,2026-11-20T08:00:00Z,2026-11-20T09:00:00Z,late\n"
                     "toly,4,2026-11-20T07:00:00Z,2026-11-20T09:00:00Z,older\n")
        with open(os.path.join(self.folder, "late-2026-11-20.csv"), "w") as fh:
            fh.write("account,post_id,posted_utc,seen_utc,minutes_late,reason\n"
                     "toly,3,2026-11-20T08:00:00Z,2026-11-20T09:00:00Z,60.0,daily post limit\n")
        with open(os.path.join(self.folder, "state.json"), "w") as fh:
            json.dump({"days": {"2026-11-20": {"skipped": {"toly": {"daily post limit": 30}}}}}, fh)

    def test_the_report_has_the_mentions_and_the_late_posts(self):
        text = "\n".join(build(self.data, CFG["xposts"], POSTED + timedelta(hours=2)))
        self.assertIn("## Ticker mentions", text)
        self.assertIn("| @saylor | large | 1 | +4.00% / +4.00% (1)", text)      # BTC, large
        self.assertIn("| @saylor | small | 2 | +4.00% / +4.00% (2)", text)      # WIF and MSTR
        self.assertIn("| @toly | small | 1 |", text)
        self.assertIn("| $STRC | not found |", text)
        self.assertIn("| $WIF | WIF (solana) | 3 | no |", text)
        self.assertIn("## Posts seen late", text)
        self.assertIn("| @toly | 3 | 2 | 1 daily post limit, 1 not recorded | 30: 30 daily post "
                      "limit |", text)
        self.assertIn("| @saylor | 1 | 0 | – | – |", text)
        self.assertLess(text.index("## Ticker mentions"), text.index("## Posts and the launches"))

    def test_the_comparison_line(self):
        (line, _) = xm.comparison_line(self.folder, "2026-11-20")
        self.assertIn("**Ticker mentions**", line)
        self.assertIn("2026-11-20: 5 in 2 post(s), 4 identified (1 large, 2 ambiguous ticker(s)), "
                      "1 not found", line)
        self.assertEqual(xm.comparison_line(os.path.join(self.data, "none"), "2026-11-20")[0],
                         "**Ticker mentions** (recording only): none recorded yet.")

    def test_the_health_row_counts_them(self):
        with open(os.path.join(self.folder, "health.json"), "w") as fh:
            json.dump({"updated": iso(SEEN), "token": True, "last_ok": iso(SEEN),
                       "accounts_watched": ["saylor"]}, fh)
        got = []
        health.add_xposts(lambda *a: got.append(a), self.data, CFG, SEEN + timedelta(hours=1))
        self.assertIn("ticker mentions today: 5 in 2 post(s), 4 identified, 11 DexScreener "
                      "request(s), 4 followed now", got[0][2])   # 5 lookups + 2 chains x 3 checks

    def test_files_are_pushed(self):
        for path in ("data/xposts/mentions-2027-01-15.csv", "data/xposts/mentions_health.json",
                     "data/xposts/late-2027-01-15.csv"):
            self.assertNotEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                               cwd=HERE).returncode, 0, path)
        self.assertEqual(subprocess.run(["git", "check-ignore", "-q",
                                         "data/xposts/mentions-2027-01-15.csv.tmp"],
                                        cwd=HERE).returncode, 0)

    def test_recording_only(self):
        with open(os.path.join(HERE, "screener", "xmentions.py")) as fh:
            source = fh.read()
        for word in ("PaperTrader", ".buy(", ".sell(", "api.x.com", "Bearer", "wallet.",
                     "private_key", "config.toml"):
            self.assertNotIn(word, source.replace("config.toml\n", ""), word)


if __name__ == "__main__":
    unittest.main()
