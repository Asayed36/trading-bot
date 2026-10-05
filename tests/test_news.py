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
from screener.news import (NewsHttp, NewsStrategy, check_candidate,  # noqa: E402
                           check_sources, coin_info, company_name, duplicate_keys,
                           find_coins, fund_coins, is_english, listing_tickers, parse_binance,
                           parse_bybit, parse_edgar, parse_feed, parse_html, parse_markets,
                           parse_okx, ticker_coins, why)

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

            def text(self, url, headers=None):
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
            def text(self, url, headers=None):
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
            def text(self, url, headers=None):
                if "globenewswire" in url:
                    raise ApiError("globenewswire answered with error 404")
                return super().text(url)

        _, _, bought, lines = self.go(Broken(now=NOW))
        self.assertEqual(len(bought), 1)
        self.assertTrue(any(l.strip().startswith("FAIL  GlobeNewswire") for l in lines))
        self.assertEqual(self.state()["sources"]["GlobeNewswire"]["ok"], False)

    def test_crypto_news_naming_no_coin_is_saved(self):
        http = DemoNewsHttp(now=NOW, items=[
            ("press", "Acme Raises $20M for Its Blockchain Payments Platform",
             "The tokenization startup will hire 50 engineers.", 5),
            ("press", "Acme Opens a Factory", "jobs", 5)])
        _, plan, bought, lines = self.go(http)
        self.assertEqual((plan["candidates"], bought), ([], []))
        rows_ = rows(os.path.join(self.folder, "unmatched.csv"))
        self.assertEqual([(r["source"], r["title"]) for r in rows_],
                         [("PR Newswire",
                           "Acme Raises $20M for Its Blockchain Payments Platform")])
        self.assertEqual(rows_[0]["url"], "https://example.com/demo-news/0")
        self.assertEqual(rows_[0]["published_utc"], "2026-09-24 13:25:00")
        self.assertTrue(any("Crypto news naming no coin" in line for line in lines))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "candidates.csv")))

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
        self.assertIn("| Source | PR Newswire |", body)
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


class NewFormatTests(unittest.TestCase):
    def test_okx_and_bybit(self):
        (it,) = parse_okx({"code": "0", "data": [{"details": [
            {"title": "OKX will launch GRVT/USD for spot trading", "url": "https://okx/1",
             "pTime": "1790254800000"}]}]})
        self.assertEqual((it["title"], it["url"]), ("OKX will launch GRVT/USD for spot trading",
                                                    "https://okx/1"))
        self.assertEqual(it["published"].tzinfo, timezone.utc)
        (it,) = parse_bybit({"retCode": 0, "result": {"list": [
            {"title": "New Listing: XYZ/USDT", "url": "https://bybit/1",
             "publishTime": 1790254800000}]}})
        self.assertEqual(it["url"], "https://bybit/1")
        with self.assertRaises(ApiError):
            parse_okx({"code": "0", "data": []})

    def test_market_lists(self):
        self.assertEqual(parse_markets("coinbase", [
            {"base_currency": "SKY", "status": "online"},
            {"base_currency": "OLD", "status": "delisted"}]), {"SKY": ""})
        self.assertEqual(parse_markets("upbit", [
            {"market": "KRW-BERA", "english_name": "Berachain"},
            {"market": "BTC-BERA", "english_name": "Berachain"}]), {"BERA": "Berachain"})
        self.assertEqual(parse_markets("okx", {"data": [{"baseCcy": "GRVT"}]}), {"GRVT": ""})
        with self.assertRaises(ApiError):
            parse_markets("upbit", [])

    def test_blog_pages_without_a_feed(self):
        ripple = ('<a href="/insights/the-swell-2026-lineup-is-here/">The Swell 2026 Lineup is '
                  'Here</a><a href="/insights/the-swell-2026-lineup-is-here/">01 The Swell 2026 '
                  'Lineup is Here September 29, 2026</a><a href="/insights/">Insights</a>')
        (it,) = parse_html(ripple, "https://ripple.com/insights/",
                           "^/insights/[a-z0-9-]{8,}/?$")
        self.assertEqual(it["title"], "The Swell 2026 Lineup is Here")
        self.assertEqual(it["url"], "https://ripple.com/insights/the-swell-2026-lineup-is-here/")
        self.assertEqual(it["published"], datetime(2026, 9, 29, tzinfo=timezone.utc))
        avax = ('<a href="/about/blog/uaes-identity-system-upgrades">Enterprises 9.14.2026 / '
                'By Avalanche / 7 Minute Read UAE&#39;s Identity System Upgrades to Avalanche'
                '</a><a href="/about/blog/uaes-identity-system-upgrades">Read More</a>')
        (it,) = parse_html(avax, "https://www.avax.network/about/blog",
                           "^/about/blog/[a-z0-9-]{8,}$")
        self.assertEqual(it["title"], "UAE's Identity System Upgrades to Avalanche")
        self.assertEqual(it["published"], datetime(2026, 9, 14, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ApiError, "no posts"):
            parse_html("<html></html>", "https://x/", "^/blog/")

    def test_edgar_keeps_fund_filings(self):
        feed = ('<feed xmlns="http://www.w3.org/2005/Atom">'
                '<entry><title>S-1/A - Canary PEPE ETF (0002109686) (Filer)</title>'
                '<link href="https://sec/1"/><id>a1</id><updated>2026-10-02T17:12:55-04:00'
                '</updated></entry><entry><title>S-1 - BioStem Technologies, Inc. (0001658678) '
                '(Filer)</title><link href="https://sec/2"/><id>a2</id></entry>'
                '<entry><title>S-1 - Grayscale Demo Network Trust (0002000000) (Filer)</title>'
                '<link href="https://sec/3"/><id>a3</id></entry></feed>')
        items = parse_edgar(parse_feed(feed))
        self.assertEqual([i["title"] for i in items],
                         ["S-1/A amendment filed: Canary PEPE ETF",
                          "S-1 filed: Grayscale Demo Network Trust"])

    def test_feeds_without_a_charset_are_utf8(self):
        class Resp:
            status_code = 200
            headers = {"content-type": "text/xml"}
            content = "Stellar\u2019s".encode("utf-8")
            text = content.decode("latin-1")

        http = NewsHttp()
        http._get = lambda url, headers=None: Resp()
        self.assertEqual(http.text("https://stellar.org/blog/rss.xml"), "Stellar\u2019s")


class BetterMatchingTests(unittest.TestCase):
    def test_tickers_in_listing_headlines(self):
        self.assertEqual(listing_tickers("WOJAK is available for trading!"), ["WOJAK"])
        self.assertEqual(listing_tickers("WOJAK, OUSD and CT are available for trading!"),
                         ["WOJAK", "OUSD", "CT"])
        self.assertEqual(listing_tickers("OKX will launch GRVT/USD for spot trading"), ["GRVT"])
        self.assertEqual(listing_tickers("OKX to list CARDS/USDT (Collector Crypt) for spot "
                                         "trading"), ["CARDS"])
        self.assertEqual(listing_tickers("Binance Will List Hyperliquid (HYPE)"), ["HYPE"])
        self.assertEqual(listing_tickers("Binance Futures Will Launch USD\u24c8-Margined "
                                         "CTUSDT Perpetual Contract (2026-10-01)"), [])

    def test_ticker_picks_the_coin_named_or_the_biggest(self):
        small = {"id": "ct-small", "symbol": "CT", "name": "Cat Token", "market_cap": 1e5}
        big = {"id": "concrete", "symbol": "CT", "name": "Concrete", "market_cap": 9e7}
        by_symbol = {"CT": [small, big]}
        self.assertEqual(ticker_coins("CT is available for trading!", ["CT"], by_symbol), [big])
        self.assertEqual(ticker_coins("Cat Token (CT) is available for trading!", ["CT"],
                                      by_symbol), [small])

    def test_company_named_after_a_coin(self):
        bnb = {"id": "binancecoin", "symbol": "BNB", "name": "BNB", "market_cap": 1e11}
        text = ("BNB Plus Corp. Announces Strategic Shift to Institutional Technology "
                "Infrastructure for Blockchain and AI. The company builds on BNB Chain.")
        self.assertEqual(company_name("BNB", text), "BNB Plus Corp.")
        self.assertEqual(find_coins(text, [bnb], C), [])
        self.assertEqual(find_coins("Visa selects BNB Chain", [bnb], C), [bnb])
        # with its ticker, the coin is named after all
        self.assertEqual(find_coins(text + " It holds 100,000 BNB ($BNB).", [bnb], C), [bnb])
        # the coin's own company still counts
        self.assertIsNone(company_name("Quant", "Quant Network Ltd selected by Visa"))
        self.assertEqual([c["id"] for c in find_coins("Solana Company Inc. buys more SOL",
                                                      COINS + [{**BY_ID["bitcoin"],
                                                                "id": "solana", "symbol": "SOL",
                                                                "name": "Solana"}], C)], [])

    def test_translations_are_duplicates(self):
        gnw = "https://www.globenewswire.com/news-release/2026/10/02/3373842/0/{}/virtune"
        en = {"title": "Virtune AB has completed the monthly rebalancing", "url": gnw.format("en"),
              "published": NOW}
        sv = {"title": "Virtune AB har genomf\u00f6rt den m\u00e5natliga rebalanseringen",
              "url": gnw.format("sv"), "published": NOW}
        self.assertTrue(is_english(en))
        self.assertFalse(is_english(sv))
        self.assertTrue(set(duplicate_keys(en, PRESS)) & set(duplicate_keys(sv, PRESS)))
        prn = "https://www.prnewswire.com/news-releases/er-{}.html"
        de = {"title": "E&R Engineering er\u00f6ffnet neues Werk in Malaysia",
              "url": prn.format("302001"), "published": NOW}
        en2 = {"title": "E&R Engineering to Launch New Malaysia Plant",
               "url": prn.format("302002"), "published": NOW}
        other = dict(en2, published=NOW + timedelta(minutes=1))
        self.assertTrue(set(duplicate_keys(de, PRESS)) & set(duplicate_keys(en2, PRESS)))
        self.assertFalse(set(duplicate_keys(de, PRESS)) & set(duplicate_keys(other, PRESS)))

    def test_fund_names(self):
        pepe = {"id": "pepe", "symbol": "PEPE", "name": "Pepe", "market_cap": 2e9}
        self.assertEqual(fund_coins("Canary PEPE ETF", [pepe] + COINS, C), [pepe])
        self.assertEqual([c["id"] for c in fund_coins("GRAYSCALE DEMO NETWORK TRUST",
                                                      COINS, C)], ["demo-network"])
        self.assertEqual(fund_coins("Acme Biotech Fund", COINS, C), [])


def sources(*names):
    """Only these sources, all read here (even those the server reads)."""
    picked = [{k: v for k, v in s.items() if k != "runs_on"}
              for s in C["sources"] if s["name"] in names]
    return dict(CFG, news=dict(C, sources=picked))


class NewSourceFlowTests(Base):
    def test_a_new_coinbase_pair_is_a_listing(self):
        cfg = sources("Coinbase new pairs")
        _, plan, bought, lines = self.go(DemoNewsHttp(now=NOW), cfg=cfg)
        self.assertEqual((plan["candidates"], bought), ([], []))      # first read: list saved
        self.assertTrue(any("first read" in line for line in lines))
        self.assertEqual(self.state()["markets"]["Coinbase new pairs"], ["BTC"])
        later = NOW + timedelta(minutes=15)
        _, plan, bought, lines = self.go(DemoNewsHttp(now=later, markets={"coinbase": ["DEMO"]}),
                                         now=later, cfg=cfg)
        (cand,) = plan["candidates"]
        self.assertEqual(cand["item"]["title"], "Coinbase lists (DEMO) for trading")
        self.assertEqual(cand["item"]["url"], "https://exchange.coinbase.com/trade/DEMO-USD")
        self.assertEqual([p["symbol"] for p in bought], ["DEMO"])
        self.assertEqual(self.state()["markets"]["Coinbase new pairs"], ["BTC", "DEMO"])
        self.assertTrue(self.state()["sources"]["Coinbase new pairs"]["newest"])

    def test_a_ticker_outside_the_top_coins_uses_the_full_list(self):
        cfg = sources("Upbit new markets")
        self.go(DemoNewsHttp(now=NOW, coins=DEMO_COINS[:1]), cfg=cfg)   # baseline
        later = NOW + timedelta(minutes=15)

        class Pages(DemoNewsHttp):        # DEMO isn't on the top-coins pages
            def json(self, url, headers=None):
                if "&page=" in url:
                    return [c for c in DEMO_COINS if c["id"] != "demo-network"]
                return super().json(url, headers)

        http = Pages(now=later, markets={"upbit": ["DEMO"]})
        _, plan, bought, _ = self.go(http, now=later, cfg=cfg)
        self.assertTrue(any("/coins/list" in u for u in http.calls))
        self.assertTrue(any("ids=demo-network" in u for u in http.calls))
        self.assertEqual([p["symbol"] for p in bought], ["DEMO"])

    def test_no_full_list_call_without_listings(self):
        http = DemoNewsHttp(now=NOW)
        self.go(http)
        self.assertFalse([u for u in http.calls if "/coins/list" in u])

    def test_disabled_sources_are_not_read(self):
        http = DemoNewsHttp(now=NOW)
        self.go(http)
        self.assertFalse([u for u in http.calls if "bybit" in u])
        self.assertNotIn("Bybit listings", self.state()["sources"])
        self.assertEqual(self.state()["sources"]["SEC EDGAR fund filings"]["filings"], 1)

    def test_sec_press_releases_must_mention_crypto(self):
        cfg = sources("SEC press releases")
        http = DemoNewsHttp(now=NOW)

        class Sec(DemoNewsHttp):
            def text(self, url, headers=None):
                self.headers = headers
                return ("<rss><channel>"
                        "<item><title>SEC Charges Adviser With Fraud</title><link>https://s/1"
                        f"</link><pubDate>{NOW:%a, %d %b %Y %H:%M:%S} GMT</pubDate></item>"
                        "</channel></rss>")

        http = Sec(now=NOW)
        _, plan, _, lines = self.go(http, cfg=cfg)
        self.assertTrue(any("1 not about crypto" in line for line in lines))
        self.assertEqual(http.headers["User-Agent"], "trading-bot-news")

    def test_day_only_dates(self):
        cfg = sources("Chainlink press releases")
        cfg["news"]["sources"] = [dict(cfg["news"]["sources"][0], coin="demo-network")]
        day = NOW.replace(hour=0, minute=0)

        class Day(DemoNewsHttp):
            def text(self, url, headers=None):
                rows = "".join(
                    f"<item><title>Visa Selects Demo Network {n}</title><link>https://c/{n}</link>"
                    f"<pubDate>{d:%a, %d %b %Y} 00:00:00 GMT</pubDate></item>"
                    for n, d in self.posts)
                return f"<rss><channel>{rows}</channel></rss>"

        http = Day(now=NOW)
        http.posts = [(1, day - timedelta(days=5))]
        self.go(http, cfg=cfg)
        http.posts.append((2, day))
        later = NOW + timedelta(minutes=15)
        _, plan, _, _ = self.go(http, now=later, cfg=cfg)
        (cand,) = plan["candidates"]          # today's post: "first seen just now"
        self.assertEqual(cand["item"]["url"], "https://c/2")
        self.assertIsNone(cand["item"]["published"])

    def test_translation_checked_once_in_english(self):
        items = [("press", "Visa Selects Demo Network f\u00fcr seine Blockchain", "", 10),
                 ("press", "Visa Selects Demo Network for Its Blockchain", "JPMorgan", 10)]
        _, plan, bought, lines = self.go(DemoNewsHttp(now=NOW, items=items))
        self.assertEqual([c["item"]["title"] for c in plan["candidates"]],
                         ["Visa Selects Demo Network for Its Blockchain"])
        self.assertTrue(any("1 duplicate(s)" in line for line in lines))


class CheckSourcesTests(unittest.TestCase):
    def test_reads_every_source_and_saves_nothing(self):
        lines = []
        failing = check_sources(CFG, DemoNewsHttp(now=NOW), lines.append, now=NOW)
        self.assertEqual(failing, 0)
        text = "\n".join(lines)
        self.assertIn("ok    Coinbase new pairs (server): 1 coins listed", text)
        self.assertIn("off   Bybit listings: Bybit blocks", text)
        self.assertIn("ok    SEC EDGAR fund filings: 0 item(s), 1 filing(s) in all", text)
        self.assertIn("ok    Ripple insights: 1 item(s)", text)

        class Broken(DemoNewsHttp):
            def text(self, url, headers=None):
                raise ApiError("down")

        self.assertGreater(check_sources(CFG, Broken(now=NOW), lambda *a: None, now=NOW), 10)
        lines = []
        check_sources(CFG, DemoNewsHttp(now=NOW), lines.append, now=NOW, runs_on="server")
        self.assertEqual(len([line for line in lines if not line.startswith(" ")]), 5)


if __name__ == "__main__":
    unittest.main()
