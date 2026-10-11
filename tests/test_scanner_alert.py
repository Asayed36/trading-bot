"""Checks for the scanner alerts (screener/scanner_alert.py, scanner_alert.py,
.github/workflows/scanner-alert.yml) with a made-up GitHub and made-up feeds:
nothing is sent anywhere. Run with:  python -m unittest -v
"""

import copy
import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import HERE, load_config  # noqa: E402
from screener import repair  # noqa: E402
from screener import scanner_alert as sa  # noqa: E402
from screener.api import ApiError  # noqa: E402
from screener.demo import DemoNewsHttp  # noqa: E402
from screener.github_issues import GitHubError  # noqa: E402

CFG = load_config()
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)


class FakeGitHub:
    """The repository's issues, in memory."""

    def __init__(self):
        self.issues, self.labels, self.fail_create = [], set(), 0

    def ensure_label(self, name, *a):
        self.labels.add(name)

    def issues_with_label(self, label=sa.LABEL):
        return [dict(i) for i in self.issues
                if label in [x["name"] for x in i["labels"]]]

    def create(self, title, body, labels=None):
        if self.fail_create:
            self.fail_create -= 1
            raise GitHubError("GitHub said 502")
        n = len(self.issues) + 1
        self.issues.append({"number": n, "title": title, "body": body, "state": "open",
                            "labels": [{"name": x} for x in labels or []]})
        return n

    def issue(self, n):
        return dict(next(i for i in self.issues if i["number"] == n))

    def set_body(self, n, body):
        next(i for i in self.issues if i["number"] == n)["body"] = body

    def alerts(self):
        return [i for i in self.issues if i["title"].startswith("ALERT")]

    def titles(self):
        return [i["title"] for i in self.alerts()]


class Http(DemoNewsHttp):
    """The demo exchanges, plus announcements, CoinGecko's and DexScreener's
    answers, and feeds that can be switched off."""

    def __init__(self, markets=None, binance=(), down=(), coingecko=None, dex=None):
        super().__init__(now=NOW, markets=markets)
        self.binance, self.down = list(binance), set(down)
        self.coingecko = {"foo": 0.5, "demo": 1.25} if coingecko is None else coingecko
        self.dex = dex if dex is not None else {}

    def json(self, url, headers=None):
        if any(d in url for d in self.down):
            raise ApiError(f"could not reach {url.split('?')[0]}: down")
        if "binance.com" in url:
            self.calls.append(url)
            return {"code": "000000", "data": {"catalogs": [{"articles": [
                {"id": n, "code": f"c{n}", "title": title,
                 "releaseDate": int(when.timestamp() * 1000)}
                for n, (title, when) in enumerate(self.binance)]}]}}
        if "coingecko.com/api/v3/search" in url:
            sym = url.split("query=")[1].upper()
            hits = [{"id": sym.lower(), "symbol": sym, "market_cap_rank": 500}] \
                if sym.lower() in self.coingecko else []
            return {"coins": hits}
        if "coingecko.com/api/v3/simple/price" in url:
            cid = url.split("ids=")[1].split("&")[0]
            return {cid: {"usd": self.coingecko[cid]}} if cid in self.coingecko else {}
        if "dexscreener.com/latest/dex/search" in url:
            sym = url.split("q=")[1].upper()
            return {"pairs": [{"baseToken": {"symbol": sym}, "dexId": "raydium",
                               "chainId": "solana", "priceUsd": "0.01",
                               "liquidity": {"usd": self.dex[sym.lower()]}}]
                    if sym.lower() in self.dex else []}
        return super().json(url, headers)


def scanner(gh=None, http=None, rows=(), **kw):
    gh = gh if gh is not None else FakeGitHub()
    return sa.Scanner(CFG, http or Http(), gh, gh, news_rows=lambda: list(rows),
                      out=lambda *a: None, **kw), gh


def poll(sc, at=0, http=None, fake=None, dry_run=False):
    if http is not None:
        sc.http = sc.prices.http = http
    sc.run(polls=1, now_fn=lambda: NOW + at * MIN, fake=fake, dry_run=dry_run)


def row(symbol="FOO", minutes_ago=5, **kw):
    r = {"time_utc": (NOW - minutes_ago * MIN).strftime("%Y-%m-%d %H:%M:%S"),
         "source": "PR Newswire", "kind": "press",
         "published_utc": (NOW - (minutes_ago + 2) * MIN).strftime("%Y-%m-%d %H:%M:%S"),
         "title": f"Big bank adopts {symbol}", "url": f"https://example.com/{symbol}",
         "rule_coin": symbol.lower(), "ai_status": "ok", "ai_symbol": symbol,
         "ai_one_coin": "yes", "ai_catalyst": "yes", "ai_catalyst_kind": "partnership",
         "ai_false_match": "no", "ai_duplicate": "no", "ai_reason": "A signed partnership."}
    r.update(kw)
    return r


class ListingTests(unittest.TestCase):
    def started(self, **kw):
        sc, gh = scanner(**kw)
        poll(sc, 0)                              # the first run: only a baseline
        return sc, gh

    def test_the_first_run_only_saves_a_baseline(self):
        sc, gh = scanner(http=Http(binance=[("Binance Will List Foo (FOO)", NOW - MIN)]),
                         rows=[row()])
        poll(sc, 0)
        self.assertEqual(gh.alerts(), [])
        (memory,) = [i for i in gh.issues if sa.STATE_LABEL in [x["name"] for x in i["labels"]]]
        state = sa.unpack(sa.STATE_RE.search(memory["body"]).group(1))
        self.assertIn("Coinbase new pairs", state["markets"])
        # what was already there is not alerted later either
        poll(sc, 1)
        self.assertEqual(gh.alerts(), [])

    def test_a_new_coin_on_a_market_list_opens_an_alert_with_everything(self):
        sc, gh = self.started(http=Http(dex={"demo": 45000}))
        poll(sc, 5, Http(markets={"coinbase": ["DEMO"]}, dex={"demo": 45000}))
        (issue,) = gh.alerts()
        self.assertEqual(issue["title"], "ALERT: Coinbase lists DEMO")
        self.assertEqual([x["name"] for x in issue["labels"]], ["scanner-alert"])
        body = issue["body"]
        self.assertIn("**Coin:** DEMO", body)
        self.assertIn("**Exchange:** Coinbase", body)
        self.assertIn("**Time we saw it:** 2026-10-11 12:05 UTC", body)
        self.assertIn("announcement time:** not known", body)
        self.assertIn("**Current price:** $1.25 (CoinGecko's public API", body)
        self.assertIn("**Liquidity:** $45,000 (DexScreener", body)
        self.assertIn("not advice", body)
        self.assertIn("Most listing pops fade", body)
        self.assertIn("Nothing was traded", body)

    def test_price_and_liquidity_fall_back_or_say_unknown(self):
        sc, gh = self.started()
        poll(sc, 5, Http(markets={"upbit": ["NEWCOIN"]}, coingecko={}, dex={}))
        (issue,) = gh.alerts()
        self.assertIn("**Current price:** not available", issue["body"])
        self.assertIn("**Liquidity:** unknown", issue["body"])
        # on a DEX only: the DEX price, named as such
        sc, gh = self.started()
        poll(sc, 5, Http(markets={"upbit": ["NEWCOIN"]}, coingecko={}, dex={"newcoin": 900}))
        (issue,) = gh.alerts()
        self.assertIn("$0.01 (DexScreener, raydium pool on solana", issue["body"])

    def test_never_twice_even_after_the_memory_is_lost_or_the_issue_closed(self):
        sc, gh = self.started()
        listed = Http(markets={"coinbase": ["DEMO"]})
        poll(sc, 5, listed)
        poll(sc, 6, listed)
        self.assertEqual(len(gh.alerts()), 1)
        gh.alerts()[0]["state"] = "closed"                     # closing it changes nothing
        poll(sc, 7, listed)
        self.assertEqual(len(gh.alerts()), 1)
        # a scanner with an empty memory (the memory issue deleted): the alert
        # issues themselves remember
        gh.issues = [i for i in gh.issues if sa.STATE_LABEL not in
                     [x["name"] for x in i["labels"]]]
        fresh, _ = scanner(gh=gh, http=Http())
        poll(fresh, 8)                                         # baseline again
        poll(fresh, 9, Http(markets={"coinbase": ["DEMO", "NEXT"]}))
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists DEMO",
                                       "ALERT: Coinbase lists NEXT"])
        poll(fresh, 10, Http(markets={"coinbase": ["DEMO", "NEXT"]}))
        self.assertEqual(len(gh.alerts()), 2)

    def test_the_same_coin_on_another_exchange_is_a_new_alert(self):
        sc, gh = self.started()
        poll(sc, 5, Http(markets={"coinbase": ["DEMO"]}))
        poll(sc, 6, Http(markets={"coinbase": ["DEMO"], "okx": ["DEMO"]}))
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists DEMO", "ALERT: OKX lists DEMO"])

    def test_binance_announcements_carry_the_exchanges_own_time(self):
        sc, gh = self.started()
        http = Http(binance=[("Binance Will List Foo (FOO) with Seed Tag Applied", NOW + 3 * MIN),
                             ("Binance Will List Old (OLD)", NOW - timedelta(hours=5)),
                             ("Binance Will Delist Bar (BAR) on 2026-10-20", NOW + 3 * MIN),
                             ("Notice on Scheduled Maintenance", NOW + 3 * MIN)])
        poll(sc, 5, http)
        (issue,) = gh.alerts()
        self.assertEqual(issue["title"], "ALERT: Binance lists FOO")
        self.assertIn("announcement time:** 2026-10-11 12:03 UTC", issue["body"])
        self.assertIn("**Current price:** $0.5 (CoinGecko", issue["body"])

    def test_a_feed_github_cannot_reach_does_not_stop_the_others(self):
        sc, gh = self.started()
        poll(sc, 5, Http(markets={"coinbase": ["DEMO"]}, down=("upbit.com", "binance.com")))
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists DEMO"])
        text = "\n".join(sc.summary())
        self.assertRegex(text, r"some Upbit new markets: 1 poll\(s\) read, 1 failed")
        self.assertRegex(text, r"FAIL Binance listings: 0 poll\(s\) read, 2 failed")
        self.assertRegex(text, r"ok   Coinbase new pairs: 2 poll\(s\) read, 0 failed")

    def test_a_listing_the_news_strategy_already_opened_an_issue_for_is_skipped(self):
        sc, gh = self.started()
        gh.issues.append({"number": 900, "title": "Paper buy: DEMO passed all news checks",
                          "body": "**Source:** Coinbase new pairs\n", "state": "closed",
                          "labels": [{"name": "passed"}, {"name": "strategy: news"}]})
        poll(sc, 5, Http(markets={"coinbase": ["DEMO", "OTHER"]}))
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists OTHER"])

    def test_a_failing_github_loses_nothing(self):
        sc, gh = self.started()
        gh.fail_create = 1
        listed = Http(markets={"coinbase": ["DEMO"]})
        poll(sc, 5, listed)
        self.assertEqual(gh.alerts(), [])
        poll(sc, 6, listed)                                    # retried, once
        poll(sc, 7, listed)
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists DEMO"])


class CapTests(unittest.TestCase):
    def test_at_most_10_a_day_and_the_rest_in_one_summary(self):
        sc, gh = scanner()
        poll(sc, 0)
        coins = [f"C{i:02d}" for i in range(13)]
        poll(sc, 1, Http(markets={"coinbase": coins}))
        titles = gh.titles()
        self.assertEqual(len([t for t in titles if t.startswith("ALERT: Coinbase lists")]), 10)
        (summary,) = [i for i in gh.alerts() if i["title"].startswith("ALERT summary")]
        self.assertEqual(summary["body"].count("ALERT: Coinbase lists"), 3)
        self.assertEqual([x["name"] for x in summary["labels"]], ["scanner-alert"])
        # more later the same day: the same summary, no new issue
        poll(sc, 2, Http(markets={"coinbase": coins + ["LATE"]}))
        self.assertEqual(len(gh.alerts()), 11)
        self.assertEqual(summary and gh.issue(summary["number"])["body"].count("ALERT: Coinbase"),
                         4)
        # and what went to the summary is not alerted again
        poll(sc, 3, Http(markets={"coinbase": coins + ["LATE"]}))
        self.assertEqual(len(gh.alerts()), 11)

    def test_the_next_day_starts_again(self):
        sc, gh = scanner()
        poll(sc, 0)
        poll(sc, 1, Http(markets={"coinbase": [f"A{i}" for i in range(11)]}))
        self.assertEqual(len(gh.alerts()), 11)                 # 10 + the summary
        sc.run(polls=1, now_fn=lambda: NOW + timedelta(days=1),
               )
        sc.http = Http(markets={"coinbase": [f"A{i}" for i in range(11)] + ["NEW"]})
        sc.run(polls=1, now_fn=lambda: NOW + timedelta(days=1, minutes=1))
        self.assertIn("ALERT: Coinbase lists NEW", gh.titles())
        self.assertEqual(len(gh.alerts()), 12)


class NewsTests(unittest.TestCase):
    def test_news_the_ai_check_flagged_is_alerted(self):
        sc, gh = scanner(rows=[
            row("FOO"),
            row("EXC", kind="exchange"),                       # a listing: the listing alerts
            row("BAD", ai_false_match="yes"), row("DUP", ai_duplicate="yes"),
            row("NOPE", ai_catalyst="no"), row("MANY", ai_one_coin="no"),
            row("ERR", ai_status="skipped: no key"),
            row("OLD", minutes_ago=600)])
        sc.memory.new = False
        poll(sc, 0)
        (issue,) = gh.alerts()
        self.assertEqual(issue["title"], "ALERT: news FOO")
        self.assertEqual([x["name"] for x in issue["labels"]], ["scanner-alert"])
        for text in ("**Coin:** FOO", "**News source:** PR Newswire", "Time we saw it",
                     "news item's own time:** 2026-10-11 11:53 UTC", "**Current price:** $0.5",
                     "A signed partnership.", "https://example.com/FOO", "not advice"):
            self.assertIn(text, issue["body"])
        poll(sc, 1)
        self.assertEqual(len(gh.alerts()), 1)

    def test_it_reads_only_what_the_news_strategy_saved_no_ai_call(self):
        src = open(os.path.join(HERE, "screener", "scanner_alert.py")).read()
        for forbidden in ("anthropic", "news_ai", "api.anthropic.com", "CLAUDE_API_KEY"):
            self.assertNotIn(forbidden, src.split('"""', 2)[2])


class FakeEventTests(unittest.TestCase):
    def test_a_fake_event_goes_through_every_rule(self):
        sc, gh = scanner()
        poll(sc, 0, fake="Coinbase:TESTCOIN")                  # not held back by the baseline
        (issue,) = gh.alerts()
        self.assertEqual(issue["title"], "ALERT: Coinbase lists TESTCOIN")
        self.assertIn("THIS IS A TEST EVENT", issue["body"])
        poll(sc, 1, fake="Coinbase:TESTCOIN")                  # the same event again: no duplicate
        self.assertEqual(len(gh.alerts()), 1)
        poll(sc, 2, fake="news:TESTCOIN")
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists TESTCOIN", "ALERT: news TESTCOIN"])

    def test_a_fake_event_on_a_new_memory_does_not_alert_the_real_items_present(self):
        sc, gh = scanner(http=Http(binance=[("Binance Will List Foo (FOO)", NOW - MIN)]),
                         rows=[row()])
        poll(sc, 0, fake="Coinbase:TESTCOIN")
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists TESTCOIN"])

    def test_a_dry_run_opens_and_saves_nothing(self):
        printed = []
        gh = FakeGitHub()
        sc = sa.Scanner(CFG, Http(), gh, gh, news_rows=lambda: [], out=printed.append)
        sc.run(polls=1, now_fn=lambda: NOW, fake="Kraken:TESTCOIN", dry_run=True)
        self.assertEqual(gh.issues, [])
        self.assertTrue(any(p.startswith("WOULD OPEN: ALERT: Kraken lists TESTCOIN")
                            for p in printed))


class MemoryTests(unittest.TestCase):
    def test_big_state_is_packed_and_comes_back(self):
        import random
        rnd = random.Random(1)
        names = ["".join(rnd.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                         for _ in range(rnd.randint(2, 8))) for _ in range(6000)]
        state = {"markets": {"Coinbase new pairs": names[:2000], "Upbit new markets": names[2000:4000],
                             "OKX new markets": names[4000:]}, "alerted": {}}
        text = sa.pack(state)                  # three lists of 2,000 tickers: ~3 times what exists
        self.assertTrue(text.startswith("z:"))
        self.assertLess(len(text), sa.MAX_STATE_CHARS)
        self.assertEqual(sa.unpack(text), state)
        self.assertEqual(sa.unpack(sa.pack({"a": 1})), {"a": 1})

    def test_a_memory_too_big_for_an_issue_is_refused_not_cut(self):
        gh = FakeGitHub()
        memory = sa.Memory(gh)
        memory.state["alerted"] = {f"k{i}-{os.urandom(8).hex()}": "2026-10-11" for i in range(9000)}
        with self.assertRaises(ApiError):
            memory.save()


class IsolationTests(unittest.TestCase):
    def test_the_repair_automation_never_sees_the_alerts(self):
        sc, gh = scanner()
        poll(sc, 0)
        poll(sc, 1, Http(markets={"coinbase": ["DEMO"]}))
        every = {x["name"] for i in gh.issues for x in i["labels"]}
        self.assertEqual(every, {"scanner-alert", "scanner-alert-state"})
        mine = {repair.LABEL, repair.READY, repair.NEEDS_YOU, repair.ATTEMPTED, "passed"}
        self.assertFalse(mine & every)
        # the repair automation reads issues by its own label only (github_issues.py
        # issues_with_label with label "repair"), so it gets none of ours
        repair_view = [i for i in gh.issues
                       if repair.LABEL in [x["name"] for x in i["labels"]]]
        self.assertEqual(repair_view, [])
        self.assertEqual(repair.problem_key(gh.alerts()[0]), None)

    def test_closing_alerts_changes_nothing(self):
        sc, gh = scanner()
        poll(sc, 0)
        poll(sc, 1, Http(markets={"coinbase": ["DEMO"]}))
        for issue in gh.issues:
            issue["state"] = "closed"                          # even the memory issue
        poll(sc, 2, Http(markets={"coinbase": ["DEMO", "NEXT"]}))
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists DEMO", "ALERT: Coinbase lists NEXT"])

    def test_the_workflow_uses_only_the_github_token(self):
        text = open(os.path.join(HERE, ".github", "workflows", "scanner-alert.yml")).read()
        self.assertNotIn("secrets.", text)
        self.assertEqual(re.findall(r"^  (\w+): (\w+)", text.split("permissions:")[1], re.M)[:2],
                         [("contents", "read"), ("issues", "write")])
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", text)
        self.assertIn("cancel-in-progress: false", text)

    def test_no_existing_setting_is_touched(self):
        # the sources it reads are read from config.toml, never written
        before = copy.deepcopy(CFG)
        sc, gh = scanner()
        poll(sc, 0)
        self.assertEqual(CFG, before)
        self.assertEqual(json.dumps(CFG, sort_keys=True, default=str),
                         json.dumps(before, sort_keys=True, default=str))


if __name__ == "__main__":
    unittest.main()
