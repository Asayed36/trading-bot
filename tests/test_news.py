"""Checks for the "news" paper strategy: reading feeds, naming the coin, the
rule-based checks, the candidate log, the exits and the GitHub issue.
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import load_config, run  # noqa: E402
from screener.api import ApiError  # noqa: E402
from screener.demo import (DEMO_COINS, DemoApi, DemoNewsHttp,  # noqa: E402
                           demo_news_items)
from screener.filters import FAIL  # noqa: E402
from screener.github_issues import issue_body, issue_title  # noqa: E402
from screener.news import (NewsStrategy, check_candidate, coin_info,  # noqa: E402
                           find_coins, parse_binance, parse_feed, why)

CFG = load_config()
C = CFG["news"]
NOW = datetime(2026, 9, 24, 13, 30, tzinfo=timezone.utc)
QUIET = dict(out=lambda *a: None)
COINS = [coin_info(c) for c in DEMO_COINS] + [coin_info(c) for c in (
    {"id": "quant-network", "symbol": "qnt", "name": "Quant", "current_price": 70.7,
     "market_cap": 1.0e9, "total_volume": 5.0e7,
     "price_change_percentage_1h_in_currency": 0.4, "price_change_percentage_24h_in_currency": 1.2},
    {"id": "flow", "symbol": "flow", "name": "Flow", "current_price": 0.6,
     "market_cap": 9.0e8, "total_volume": 4.0e7,
     "price_change_percentage_1h_in_currency": 0.1, "price_change_percentage_24h_in_currency": 0.5},
    {"id": "bitcoin-cash", "symbol": "bch", "name": "Bitcoin Cash", "current_price": 400.0,
     "market_cap": 8.0e9, "total_volume": 3.0e8,
     "price_change_percentage_1h_in_currency": 0.1, "price_change_percentage_24h_in_currency": 0.5},
    {"id": "usd-coin", "symbol": "usdc", "name": "USDC", "current_price": 1.0,
     "market_cap": 7.0e10, "total_volume": 9.0e9,
     "price_change_percentage_1h_in_currency": 0.0, "price_change_percentage_24h_in_currency": 0.0},
)]
BY_ID = {c["id"]: c for c in COINS}
PRESS = {"name": "PR Newswire crypto", "kind": "press"}
EXCHANGE = {"name": "Binance listings", "kind": "exchange"}
TCH = ("The Clearing House Partners with Quant to Advance the On-Chain Money Initiative",
       "The Clearing House selected Quant as the technology partner for its tokenized deposit "
       "network, backed by J.P. Morgan, Citi and Wells Fargo.")


def item(title, summary="", minutes_ago=10):
    return {"id": title, "title": title, "summary": summary, "url": "https://example.com/n",
            "published": NOW - timedelta(minutes=minutes_ago)}


def checks_for(title, summary="", source=PRESS, coins=None, minutes_ago=10, state=None):
    it = item(title, summary, minutes_ago)
    named = coins if coins is not None else find_coins(f"{title}. {summary}", COINS, C)
    return {ch.name: ch for ch in check_candidate(it, source, named, NOW, state or {}, C)}


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class FeedTests(unittest.TestCase):
    def test_rss(self):
        text = ("<rss><channel><item><title>Quant &amp; TCH</title>"
                "<description>&lt;p&gt;Selected &lt;b&gt;Quant&lt;/b&gt;&lt;/p&gt;</description>"
                "<link>https://x/1</link><guid>g1</guid>"
                "<pubDate>Wed, 24 Sep 2026 13:00:00 GMT</pubDate></item></channel></rss>")
        (it,) = parse_feed(text)
        self.assertEqual((it["id"], it["title"], it["summary"], it["url"]),
                         ("g1", "Quant & TCH", "Selected Quant", "https://x/1"))
        self.assertEqual(it["published"], datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc))

    def test_atom(self):
        text = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Hello</title>'
                '<link href="https://x/2"/><id>tag:2</id><updated>2026-09-24T13:00:00Z</updated>'
                '<summary>Body</summary></entry></feed>')
        (it,) = parse_feed(text)
        self.assertEqual((it["id"], it["url"], it["summary"]), ("tag:2", "https://x/2", "Body"))
        self.assertEqual(it["published"].hour, 13)

    def test_bad_feed_is_an_api_error(self):
        with self.assertRaises(ApiError):
            parse_feed("<html>not a feed")

    def test_common_feed_mistakes_are_repaired(self):
        text = ("<rss><channel><item><title>Q&nbsp;&amp;&nbsp;A: R&D \x01update</title>"
                "<link>https://x/3?a=1&b=2</link></item></channel></rss>")
        (it,) = parse_feed(text)
        self.assertEqual(it["title"], "Q & A: R&D update")
        self.assertEqual(it["url"], "https://x/3?a=1&b=2")

    def test_empty_feed_is_broken(self):
        # Business Wire answers a bad address with an empty feed holding the error.
        text = ("<rss><channel><title>Business Wire</title><description>RSS channel ID is "
                "not available in the request.</description></channel></rss>")
        with self.assertRaisesRegex(ApiError, "no items.*channel ID is not available"):
            parse_feed(text)
        with self.assertRaises(ApiError):
            parse_binance({"code": "000000", "data": {"catalogs": []}})

    def test_connection_errors_say_why(self):
        exc = Exception("HTTPSConnectionPool(host='www.globenewswire.com', port=443): Max "
                        "retries exceeded with url: /x (Caused by ConnectTimeoutError(<conn>, "
                        "'Connection to www.globenewswire.com timed out. (connect timeout=20)'))")
        self.assertTrue(why(exc).startswith("ConnectTimeoutError: "))
        self.assertIn("timed out", why(exc))

    def test_binance_list(self):
        data = {"code": "000000", "data": {"catalogs": [{"catalogId": 48, "articles": [
            {"id": 7, "code": "abc", "title": "Binance Will List Quant (QNT)",
             "releaseDate": 1790254800000}]}]}}
        (it,) = parse_binance(data)
        self.assertEqual(it["url"], "https://www.binance.com/en/support/announcement/abc")
        self.assertEqual(it["title"], "Binance Will List Quant (QNT)")
        self.assertEqual(it["published"].tzinfo, timezone.utc)


class CoinMatchTests(unittest.TestCase):
    def names(self, text):
        return [c["id"] for c in find_coins(text, COINS, C)]

    def test_unambiguous_and_multi_word_names(self):
        self.assertEqual(self.names(TCH[0]), ["quant-network"])      # "Quant" is listed
        self.assertEqual(self.names("Big Bank selects Demo Network"), ["demo-network"])

    def test_everyday_word_needs_ticker_or_qualifier(self):
        self.assertEqual(self.names("A new Flow for payments, on the blockchain"), [])
        self.assertEqual(self.names("Visa partners with Flow (FLOW)"), ["flow"])
        self.assertEqual(self.names("Visa partners with Flow Foundation"), ["flow"])
        self.assertEqual(self.names("flow (FLOW) lowercase"), [])    # capitals must match

    def test_bitcoin_in_passing_and_longer_names(self):
        self.assertEqual(self.names("Accepts Bitcoin; Demo Network goes live"), ["demo-network"])
        self.assertEqual(self.names("Bitcoin Cash upgrade goes live"), ["bitcoin-cash"])
        self.assertEqual(self.names("Bitcoin ETF approved"), ["bitcoin"])   # alone, it counts


class CheckTests(unittest.TestCase):
    def failed(self, checks):
        return sorted(n for n, ch in checks.items() if ch.status == FAIL)

    def test_the_quant_case_passes(self):
        checks = checks_for(*TCH)
        self.assertEqual(self.failed(checks), [])
        self.assertEqual(checks["Catalyst wording"].detail, '"Partners with"')
        self.assertEqual(checks["Named counterparty"].detail, "The Clearing House")

    def test_each_failure(self):
        cases = {
            "Fresh news": dict(title=TCH[0], summary=TCH[1], minutes_ago=200),
            "One coin": dict(title="Visa selects Demo Network and Hypecoin (HYPE2)", summary=""),
            "Not paid content": dict(title=TCH[0], summary=TCH[1] + " Sponsored."),
            "Catalyst wording": dict(title="Quant at a conference with Visa", summary=""),
            "No hype wording": dict(title="Quant explores options with Visa", summary="selected"),
            "Not bad news": dict(title="Quant hacked; Visa selects new partner", summary=""),
            "Named counterparty": dict(title="Quant launches a new product", summary=""),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                self.assertEqual(self.failed(checks_for(**kw)), [name])

    def test_size_move_and_stablecoin(self):
        small = dict(BY_ID["demo-network"], market_cap=5e6)
        moved = dict(BY_ID["demo-network"], change_1h=22.0)
        unknown = dict(BY_ID["demo-network"], change_1h=None)
        for coin, name in ((small, "Big enough"), (moved, "Not already moved"),
                           (unknown, "Not already moved"),
                           (BY_ID["usd-coin"], "Not a stablecoin")):
            with self.subTest(name):
                checks = checks_for("Visa selects Demo Network", coins=[coin])
                self.assertEqual(self.failed(checks), [name])

    def test_cooldown(self):
        state = {"last_bought": {"quant-network": (NOW - timedelta(days=1)).isoformat()}}
        self.assertEqual(self.failed(checks_for(*TCH, state=state)), ["Not bought recently"])
        state = {"last_bought": {"quant-network": (NOW - timedelta(days=4)).isoformat()}}
        self.assertEqual(self.failed(checks_for(*TCH, state=state)), [])

    def test_exchange_listing(self):
        checks = checks_for("Binance Will List Quant (QNT)", source=EXCHANGE)
        self.assertEqual(self.failed(checks), [])
        self.assertIn("Binance listings", checks["Named counterparty"].detail)
        checks = checks_for("Binance Will Delist Quant (QNT)", source=EXCHANGE)
        self.assertIn("Not bad news", self.failed(checks))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "news")

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, http=None, now=NOW, cfg=CFG):
        s = NewsStrategy(cfg, self.tmp.name, http or DemoNewsHttp(now=now))
        plan = s.fetch(now=now)
        lines = []
        bought = s.apply(plan, _details, lines.append)
        return s, plan, bought, lines

    def state(self):
        with open(os.path.join(self.folder, "positions.json")) as fh:
            return json.load(fh)


def _details(*a, **k):  # the news strategy writes its own issue details
    raise AssertionError("not used")


class FlowTests(Base):
    def test_buys_the_real_catalyst_and_logs_every_candidate(self):
        s, plan, bought, lines = self.go()
        (pos,) = bought
        self.assertEqual((pos["address"], pos["symbol"], pos["entry_price"], pos["cost_usd"]),
                         ("demo-network", "DEMO", 70.0, 10.0))
        self.assertEqual(pos["news"]["title"], demo_news_items()[0][1])
        logged = rows(os.path.join(self.folder, "candidates.csv"))
        self.assertEqual([(r["symbol"], r["verdict"]) for r in logged],
                         [("DEMO", "PASS"), ("HYPE2", "FAIL")])
        self.assertIn('No hype wording: says "Explores"', logged[1]["failed"])
        self.assertIn("Named counterparty=PASS", logged[0]["checks"])
        # the factory press release isn't about crypto: not a candidate
        self.assertTrue(any("1 not about crypto" in line for line in lines))
        # the same release on the second PR Newswire feed is checked once
        self.assertTrue(any("PR Newswire blockchain" in l and "0 new" in l for l in lines))
        entry = rows(os.path.join(self.folder, "entries.csv"))[0]
        self.assertEqual(entry["price_change_1h_pct"], "0.5")

    def test_checks_only_every_15_minutes_and_never_twice(self):
        self.go()
        _, plan, bought, _ = self.go(now=NOW + timedelta(minutes=5))
        self.assertFalse(plan["checked"])
        _, plan, bought, _ = self.go(now=NOW + timedelta(minutes=14))
        self.assertTrue(plan["checked"])               # 13 min is enough (2 min slack)
        self.assertEqual((plan["candidates"], bought), ([], []))
        self.assertEqual(len(rows(os.path.join(self.folder, "candidates.csv"))), 2)

    def test_seen_list_is_short_and_pruned(self):
        self.go()
        seen = self.state()["seen"]
        self.assertTrue(seen and all(len(k) == 12 for k in seen))
        self.go(DemoNewsHttp(now=NOW + timedelta(days=2), items=[]), now=NOW + timedelta(days=2))
        self.assertEqual(self.state()["seen"], {})

    def test_first_run_skips_the_old_backlog(self):
        http = DemoNewsHttp(now=NOW, items=[("press", "Visa Selects Demo Network",
                                             "blockchain; JPMorgan", 600)])
        _, plan, bought, lines = self.go(http)
        self.assertEqual((plan["candidates"], bought), ([], []))
        self.assertTrue(any(re.search(r"PR Newswire crypto .* 1 older than 180 min", line)
                            for line in lines))
        self.assertEqual(self.state()["seen"], {})      # old items are only counted

    def test_a_source_that_starts_working_later_skips_its_backlog(self):
        class Fixed(DemoNewsHttp):
            broken = True

            def text(self, url):
                if "businesswire" in url and self.broken:
                    raise ApiError("the feed has no items")
                if "businesswire" in url:
                    return ("<rss><channel><item><title>Visa Selects Demo Network</title>"
                            "<description>blockchain JPMorgan</description><link>https://b/1"
                            "</link><pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate></item>"
                            "</channel></rss>")
                return super().text(url)

        http = Fixed(now=NOW)
        self.go(http)
        self.assertNotIn("Business Wire", self.state()["sources_read"])
        http.broken = False
        _, plan, _, lines = self.go(http, now=NOW + timedelta(minutes=15))
        self.assertEqual(plan["candidates"], [])           # 3-day-old item: noted, not checked
        self.assertEqual(self.state()["sources"]["Business Wire"]["old"], 1)
        self.assertIn("Business Wire", self.state()["sources_read"])

    def test_undated_items_skipped_on_first_read_then_checked(self):
        class Undated(DemoNewsHttp):
            def text(self, url):
                if "prnewswire.com/rss/financial" in url:
                    return ("<rss><channel>" + "".join(
                        f"<item><title>Visa Selects Demo Network {n}</title><description>"
                        f"blockchain</description><link>https://u/{n}</link></item>"
                        for n in self.ids) + "</channel></rss>")
                return super().text(url)

        http = Undated(now=NOW, items=[])
        http.ids = [1]
        _, plan, _, lines = self.go(http)
        self.assertEqual(plan["candidates"], [])
        self.assertTrue(any("1 undated item(s)" in line for line in lines))
        http.ids = [1, 2]
        _, plan, _, _ = self.go(http, now=NOW + timedelta(minutes=15))
        self.assertEqual([c["item"]["url"] for c in plan["candidates"]], ["https://u/2"])
        # undated items are remembered for 4 days, so they're never checked twice
        _, plan, _, _ = self.go(http, now=NOW + timedelta(days=3))
        self.assertEqual(plan["candidates"], [])
        self.assertTrue(all(v.endswith("u") for v in self.state()["seen"].values()))

    def test_coingecko_down_means_retry_next_run(self):
        class Down(DemoNewsHttp):
            def json(self, url, headers=None):
                if "coingecko" in url:
                    raise ApiError("CoinGecko answered with error 503")
                return super().json(url, headers)

        _, plan, bought, lines = self.go(Down(now=NOW))
        self.assertEqual(bought, [])
        self.assertTrue(any("CoinGecko unavailable" in line for line in lines))
        _, plan, bought, _ = self.go(now=NOW + timedelta(minutes=15))
        self.assertEqual([p["symbol"] for p in bought], ["DEMO"])   # checked when it's back

    def test_one_broken_source_doesnt_stop_the_others(self):
        class Broken(DemoNewsHttp):
            def text(self, url):
                if "globenewswire" in url:
                    raise ApiError("globenewswire answered with error 404")
                return super().text(url)

        _, _, bought, lines = self.go(Broken(now=NOW))
        self.assertEqual(len(bought), 1)
        self.assertTrue(any(l.strip().startswith("FAIL  GlobeNewswire") for l in lines))
        self.assertEqual(self.state()["sources"]["GlobeNewswire"]["ok"], False)

    def test_no_coingecko_call_without_crypto_news(self):
        http = DemoNewsHttp(now=NOW, items=[("press", "Acme Opens a Factory", "jobs", 5)])
        self.go(http)
        self.assertFalse([u for u in http.calls if "coingecko" in u])

    def test_monthly_call_limit(self):
        cfg = dict(CFG, news=dict(C, coingecko_monthly_calls=1))
        _, _, bought, lines = self.go(cfg=cfg)
        self.assertEqual(bought, [])
        self.assertTrue(any("calls are used up" in line for line in lines))

    def test_project_blog_names_its_own_coin(self):
        cfg = dict(CFG, news=dict(C, sources=[
            {"name": "Demo blog", "kind": "blog", "coin": "demo-network",
             "url": "https://www.prnewswire.com/demo-blog.rss"}]))
        http = DemoNewsHttp(now=NOW, items=[("blog", "We Partner With Visa",
                                             "Our token goes live with Visa", 5)])
        _, plan, bought, _ = self.go(http, cfg=cfg)
        self.assertEqual([p["symbol"] for p in bought], ["DEMO"])


class ExitTests(Base):
    def held(self):
        s, _, bought, _ = self.go()
        return bought[0]

    def run_at(self, minutes, move):
        http = DemoNewsHttp(now=NOW + timedelta(minutes=minutes),
                            price_moves={"demo-network": move})
        s, _, _, lines = self.go(http, now=NOW + timedelta(minutes=minutes))
        return s, [l for l in lines if "SELL" in l]

    def test_half_at_plus_50_then_trailing_stop(self):
        self.held()
        s, sells = self.run_at(15, 1.6)
        self.assertEqual(len(sells), 1)
        self.assertIn("take profit", sells[0])
        self.assertEqual(s.trader.open_positions[0]["remaining_fraction"], 0.5)
        s, sells = self.run_at(30, 2.0)                # new peak
        self.assertEqual(sells, [])
        s, sells = self.run_at(45, 1.45)               # 27.5% below the peak
        self.assertIn("trailing stop", sells[0])
        self.assertFalse(s.trader.open_positions)

    def test_stop_loss_at_minus_20(self):
        self.held()
        s, sells = self.run_at(15, 0.85)
        self.assertEqual(sells, [])
        s, sells = self.run_at(30, 0.79)
        self.assertIn("stop loss: down 21%", sells[0])
        with open(s.trader.journal_path) as fh:
            sell = list(csv.DictReader(fh))[-1]
        self.assertEqual(sell["pnl_usd"], "-2.20")      # -21% minus 1% costs on $10

    def test_seven_day_limit(self):
        self.held()
        s, sells = self.run_at(6 * 24 * 60, 1.1)
        self.assertEqual(sells, [])
        s, sells = self.run_at(7 * 24 * 60 + 15, 1.1)
        self.assertIn("time limit: 7 days", sells[0])


class IssueAndRunTests(Base):
    def test_issue_for_a_news_buy(self):
        _, _, bought, _ = self.go()
        pos = bought[0]
        self.assertEqual(issue_title(pos, "news"), "PASSED (news): DEMO")
        body = issue_body(pos, C["paper_trading"], "note", "news")
        self.assertIn("<!-- screener-token: demo-network strategy: news -->", body)
        self.assertIn("**CoinGecko id:** `demo-network`", body)
        self.assertIn("| Source | PR Newswire crypto |", body)
        self.assertIn("| Take profit: sell half | $105 (+50%) |", body)
        self.assertIn("| Stop loss: sell everything left | $56 (-20%) |", body)
        self.assertIn("(7 days)", body)
        self.assertNotIn("Top 10 holders", body)
        self.assertNotIn("Liquidity", body)

    def test_full_run_includes_news(self):
        lines = []
        run(DemoApi(), CFG, self.tmp.name, out=lines.append, news_http=DemoNewsHttp())
        text = "\n".join(lines)
        self.assertIn("STEP 7: News strategy", text)
        self.assertIn("BUY  DEMO", text)
        self.assertIn("SUMMARY (news strategy)", text)

    def test_runs_without_news_http_skip_news(self):
        lines = []
        run(DemoApi(), CFG, self.tmp.name, out=lines.append)
        self.assertFalse(any("STEP 7" in line for line in lines))


class PaperOnlyTests(unittest.TestCase):
    def test_only_reads(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "screener", "news.py")
        with open(path) as fh:
            code = fh.read()
        self.assertNotRegex(code, r"requests\.(post|put|patch|delete)")
        for word in ("private_key", "keypair", "seed phrase", "sign_transaction", "api_secret"):
            self.assertNotIn(word, code.lower())

    def test_demo_data_is_not_mutated(self):
        before = copy.deepcopy(DEMO_COINS)
        DemoNewsHttp(price_moves={"demo-network": 2.0}).json("https://api.coingecko.com/x?page=1")
        self.assertEqual(DEMO_COINS, before)


if __name__ == "__main__":
    unittest.main()
