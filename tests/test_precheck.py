"""Checks for the scanner alerts' Pre-check (screener/precheck.py and its place in
screener/scanner_alert.py), with made-up exchange answers: nothing is downloaded.
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
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener import precheck as pc  # noqa: E402
from screener import scanner_alert as sa  # noqa: E402
from screener.api import ApiError  # noqa: E402
from screener.github_issues import GitHubError  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402
from tests.test_scanner_alert import NOW, FakeGitHub, Http  # noqa: E402

CFG = load_config()
T = CFG["scanner_alert"]["precheck"]
MIN = timedelta(minutes=1)


class Routes:
    """An HTTP stand-in: the first route whose text is in the URL answers (a value, or an
    exception to raise). Records every URL asked."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def json(self, url, headers=None):
        self.calls.append(url)
        for text, answer in self.routes:
            if text in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer(url) if callable(answer) else copy.deepcopy(answer)
        raise ApiError(f"no route for {url}")


def okx(spot=(), swap=(), futures=(), margin=(), down=()):
    def lst(ids, state="live"):
        return {"code": "0", "data": [{"instId": i, "state": state} for i in ids]}
    r = []
    for kind, ids in (("SPOT", spot), ("SWAP", swap), ("FUTURES", futures), ("MARGIN", margin)):
        r.append((f"instType={kind}", ApiError("boom") if kind in down else lst(ids)))
    return r


# ---------------------------------------------------------------------
# 2. Spot or not
# ---------------------------------------------------------------------

class SpotTests(unittest.TestCase):
    def spot(self, venue, routes, coin="FOO"):
        return pc.VENUES[venue](Routes(routes)).spot(coin)

    def test_okx_spot_is_yes_with_the_pairs(self):
        r = self.spot("OKX", okx(spot=["FOO-USDT", "FOO-BTC", "FOOD-USDT"], swap=["FOO-USDT-SWAP"]))
        self.assertEqual(r["status"], "yes")
        self.assertEqual(r["text"], "SPOT: yes (pairs: FOO-USDT, FOO-BTC)")        # FOOD is another coin

    def test_okx_derivatives_only_is_not_spot(self):
        r = self.spot("OKX", okx(swap=["FOO-USDT-SWAP"], futures=["FOO-USD-261225"]))
        self.assertEqual(r["status"], "no")
        self.assertEqual(r["text"], "NOT SPOT: derivatives only (perpetual/futures): "
                                    "FOO-USDT-SWAP, FOO-USD-261225")

    def test_okx_margin_only_and_nothing_at_all(self):
        self.assertIn("NOT SPOT: margin market only: FOO-USDT", self.spot("OKX", okx(margin=["FOO-USDT"]))["text"])
        r = self.spot("OKX", okx())
        self.assertEqual(r["status"], "no")
        self.assertIn("not in OKX's SPOT, SWAP, FUTURES or MARGIN lists", r["text"])

    def test_okx_a_state_that_is_not_live_does_not_count(self):
        routes = [("instType=SPOT", {"code": "0", "data": [{"instId": "FOO-USDT", "state": "suspend"}]})] \
            + okx()[1:]
        self.assertEqual(self.spot("OKX", routes)["status"], "no")

    def test_okx_a_list_that_cannot_be_read_is_unknown_never_a_guess(self):
        with self.assertRaises(pc.LookupFailed):                       # the SPOT list itself failing
            self.spot("OKX", okx(down=("SPOT",)))
        r = self.spot("OKX", okx(down=("SWAP",)))                       # only a derivatives list failing
        self.assertEqual(r["status"], "unknown")
        self.assertIn("SPOT: unknown", r["text"])
        r = self.spot("OKX", okx(swap=["FOO-USDT-SWAP"], down=("FUTURES",)))
        self.assertEqual(r["status"], "no")                             # a derivative was found: still not spot

    def test_the_other_exchanges_lists(self):
        binance = self.spot("Binance", [("ticker/price", [{"symbol": "FOOUSDT", "price": "1"},
                                                          {"symbol": "FOOBTC", "price": "1"},
                                                          {"symbol": "FOODUSDT", "price": "1"}])])
        self.assertEqual(binance["text"], "SPOT: yes (pairs: FOOUSDT, FOOBTC)")
        coinbase = self.spot("Coinbase", [("/products", [
            {"id": "FOO-USD", "base_currency": "FOO", "quote_currency": "USD", "status": "online"},
            {"id": "FOO-EUR", "base_currency": "FOO", "quote_currency": "EUR", "status": "offline"}])])
        self.assertEqual(coinbase["text"], "SPOT: yes (pairs: FOO-USD)")
        upbit = self.spot("Upbit", [("market/all", [{"market": "KRW-FOO"}, {"market": "BTC-FOO"},
                                                    {"market": "KRW-BAR"}])])
        self.assertEqual(upbit["text"], "SPOT: yes (pairs: KRW-FOO, BTC-FOO)")
        kraken = self.spot("Kraken", [("AssetPairs", {"error": [], "result": {
            "FOOUSD": {"altname": "FOOUSD", "wsname": "FOO/USD", "status": "online"},
            "XXBTZUSD": {"altname": "XBTUSD", "wsname": "XBT/USD", "status": "online"}}})])
        self.assertEqual(kraken["text"], "SPOT: yes (pairs: FOOUSD)")
        self.assertEqual(self.spot("Kraken", [("AssetPairs", {"error": [], "result": {
            "XXBTZUSD": {"altname": "XBTUSD", "wsname": "XBT/USD"}}})], "BTC")["status"], "yes")   # XBT = BTC
        none = self.spot("Binance", [("ticker/price", [])])
        self.assertEqual(none["status"], "no")
        self.assertTrue(none["text"].startswith("NOT SPOT"))

    def test_the_best_pair_is_a_usdt_like_quote(self):
        pairs = [pc.pair("FOOBTC", "FOO", "BTC"), pc.pair("FOOUSDC", "FOO", "USDC"),
                 pc.pair("FOOUSDT", "FOO", "USDT")]
        self.assertEqual(pc.best_pair(pairs)["id"], "FOOUSDT")
        self.assertEqual(pc.best_pair(pairs[:2])["id"], "FOOUSDC")
        self.assertIsNone(pc.best_pair([]))


class TickerTests(unittest.TestCase):
    def test_each_exchanges_ticker(self):
        b = pc.Binance(Routes([("ticker/24hr?symbol=FOOUSDT", {"lastPrice": "2.5", "priceChangePercent": "12.5",
                                                               "quoteVolume": "345000.5"})]))
        self.assertEqual(b.ticker(pc.pair("FOOUSDT", "FOO", "USDT")),
                         {"last": 2.5, "change_pct": 12.5, "volume_quote": 345000.5, "quote": "USDT"})
        c = pc.Coinbase(Routes([("FOO-USD/stats", {"open": "2", "last": "3", "volume": "1000"})]))
        t = c.ticker(pc.pair("FOO-USD", "FOO", "USD"))
        self.assertEqual((t["last"], t["change_pct"], t["volume_quote"]), (3.0, 50.0, 3000.0))
        o = pc.Okx(Routes([("market/ticker?instId=FOO-USDT", {"code": "0", "data": [
            {"last": "1.2", "open24h": "1.0", "volCcy24h": "777000"}]})]))
        t = o.ticker(pc.pair("FOO-USDT", "FOO", "USDT"))
        self.assertEqual((t["last"], round(t["change_pct"], 6), t["volume_quote"]), (1.2, 20.0, 777000.0))
        k = pc.Kraken(Routes([("Ticker?pair=FOOUSD", {"error": [], "result": {"FOOUSD": {
            "c": ["10", "1"], "o": "8", "v": ["5", "100"], "p": ["9", "9.5"]}}})]))
        t = k.ticker(pc.pair("FOOUSD", "FOO", "USD"))
        self.assertEqual((t["last"], t["change_pct"], t["volume_quote"]), (10.0, 25.0, 950.0))
        self.assertIn("today's 00:00 UTC open", t["note"])

    def test_upbit_krw_is_converted_to_usdt_and_a_btc_pair_has_no_usdt_figure(self):
        u = pc.Upbit(Routes([("ticker?markets=KRW-USDT", [{"trade_price": 1400}]),
                             ("ticker?markets=KRW-FOO", [{"trade_price": 2800, "signed_change_rate": 0.1,
                                                          "acc_trade_price_24h": 1_400_000_000}])]))
        t = u.ticker(pc.pair("KRW-FOO", "FOO", "KRW"))
        self.assertEqual((t["last"], round(t["change_pct"], 6), t["volume_quote"], t["quote"]),
                         (2.0, 10.0, 1_000_000.0, "USDT"))
        f = pc.evaluate({"spot": "yes", "clash_count": 1, "move_pct": 0.0, "change_24h_pct": 1.0,
                         "volume_usdt": None, "volume_note": "the best pair is quoted in BTC, not USDT",
                         "stable": False}, T)
        self.assertEqual(f[1], "FAIL")
        self.assertIn("24h volume: unverified (the best pair is quoted in BTC, not USDT)", f[2])

    def test_the_price_at_the_announcement(self):
        when = datetime(2026, 10, 11, 12, 0, 30, tzinfo=timezone.utc)
        ms = int(when.timestamp() * 1000)
        p = pc.pair("FOOUSDT", "FOO", "USDT")
        near = pc.Binance(Routes([("klines", [[ms - 30_000, "1.5", "1", "1", "1", "1"]])]))
        self.assertEqual(near.price_at(p, when), 1.5)
        later = pc.Binance(Routes([("klines", [[ms + 3_600_000, "9", "9", "9", "9", "1"]])]))
        self.assertIsNone(later.price_at(p, when))                       # the pair began trading hours later
        self.assertIsNone(pc.Binance(Routes([("klines", [])])).price_at(p, when))
        o = pc.Okx(Routes([("history-candles", {"data": [[str(ms - 20_000), "0.5", "1", "1", "1"]]})]))
        self.assertEqual(o.price_at(pc.pair("FOO-USDT", "FOO", "USDT"), when), 0.5)
        k = pc.Kraken(Routes([("OHLC", {"error": [], "result": {"FOOUSD": [[int(when.timestamp()) - 10, "7"]],
                                                                  "last": 1}})]))
        self.assertEqual(k.price_at(pc.pair("FOOUSD", "FOO", "USD"), when), 7.0)
        with self.assertRaises(pc.LookupFailed):
            pc.Coinbase(Routes([])).price_at(p, when)


# ---------------------------------------------------------------------
# 3. Ticker clash, within the CoinGecko budget
# ---------------------------------------------------------------------

def coins(symbol, n):
    return [{"id": f"{symbol.lower()}-{i}", "symbol": symbol.lower(), "name": f"{symbol} Coin {i}"}
            for i in range(n)]


class ClashTests(unittest.TestCase):
    def pre(self, routes, state=None):
        return pc.Precheck(CFG, Routes(routes), state if state is not None else {}), NOW

    def test_one_coin_two_calls_counted(self):
        pre, now = self.pre([("coins/list", coins("FOO", 1) + coins("BAR", 3)),
                             ("coins/markets", [{"name": "Foo Network", "market_cap": 5_000_000}])])
        r = pre.clash("FOO", now)
        self.assertEqual((r["count"], r["coins"]), (1, [("Foo Network", 5_000_000.0)]))
        self.assertEqual(pre.state["coingecko"], {"month": "2026-10", "calls": 2})
        self.assertEqual(len(pre.http.calls), 2)
        pre.clash("FOO", now)                                              # the coin list is kept for the run
        self.assertEqual(len(pre.http.calls), 3)

    def test_several_coins_show_at_most_three_biggest_and_the_count(self):
        rows = [{"name": f"Coin {i}", "market_cap": 1000 * (5 - i)} for i in range(5)]
        pre, now = self.pre([("coins/list", coins("ONE", 7)), ("coins/markets", rows)])
        r = pre.clash("ONE", now)
        self.assertEqual(r["count"], 7)
        self.assertEqual([n for n, _ in r["coins"]], ["Coin 0", "Coin 1", "Coin 2"])
        self.assertIn("order=market_cap_desc", pre.http.calls[1])

    def test_not_in_coingecko_costs_one_call(self):
        pre, now = self.pre([("coins/list", coins("BAR", 2))])
        r = pre.clash("FOO", now)
        self.assertEqual((r["count"], r["coins"]), (0, []))
        self.assertEqual(pre.state["coingecko"]["calls"], 1)

    def test_market_caps_failing_still_names_the_coins(self):
        pre, now = self.pre([("coins/list", coins("ONE", 2)), ("coins/markets", ApiError("429"))])
        r = pre.clash("ONE", now)
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["coins"][0], ("ONE Coin 0", None))
        self.assertIn("lookup failed", r["note"])

    def test_the_budget_used_up_is_said_and_no_call_is_made(self):
        pre, now = self.pre([("coins/list", coins("FOO", 1))],
                            {"coingecko": {"month": "2026-10", "calls": T["coingecko_monthly_calls"]}})
        with self.assertRaises(pc.LookupFailed) as ctx:
            pre.clash("FOO", now)
        self.assertIn("budget for 2026-10 is used up", str(ctx.exception))
        self.assertEqual(pre.http.calls, [])
        # a new month starts again
        pre2, _ = self.pre([("coins/list", coins("FOO", 1)), ("coins/markets", [])],
                           {"coingecko": {"month": "2026-09", "calls": 999}})
        pre2.clash("FOO", now)
        self.assertEqual(pre2.state["coingecko"], {"month": "2026-10", "calls": 2})

    def test_the_key_the_repo_already_uses_is_sent_when_there_is_one(self):
        seen = []

        class Http2(Routes):
            def json(self, url, headers=None):
                seen.append(headers)
                return super().json(url, headers)
        pre = pc.Precheck(CFG, Http2([("coins/list", [])]), {}, cg_key="K")
        pre.clash("FOO", NOW)
        self.assertEqual(seen, [{"x-cg-demo-api-key": "K"}])


# ---------------------------------------------------------------------
# 5. The thresholds and the verdict
# ---------------------------------------------------------------------

GOOD = {"spot": "yes", "spot_text": "SPOT: yes (pairs: FOO-USD)", "clash_count": 1, "move_pct": 3.0,
        "change_24h_pct": 12.0, "volume_usdt": 250_000.0, "stable": False, "stable_note": "ok"}


class ThresholdTests(unittest.TestCase):
    def verdict(self, **changes):
        facts = dict(GOOD, **changes)
        return pc.evaluate(facts, T)

    def test_all_good_passes(self):
        checks, verdict, line = self.verdict()
        self.assertEqual((verdict, line), ("PASS", "PASSES the basic checks"))
        self.assertEqual([c[1] for c in checks], ["pass"] * 6)

    def test_the_limits_come_from_the_config_and_are_strict(self):
        self.assertEqual((T["max_move_since_announcement_pct"], T["max_change_24h_pct"],
                          T["min_volume_24h_usdt"]), (15, 40, 100000))
        self.assertEqual(self.verdict(move_pct=14.99)[1], "PASS")
        self.assertEqual(self.verdict(move_pct=15.0)[1], "FAIL")           # "less than 15%"
        self.assertEqual(self.verdict(change_24h_pct=39.9)[1], "PASS")
        self.assertEqual(self.verdict(change_24h_pct=40.0)[1], "FAIL")
        self.assertEqual(self.verdict(volume_usdt=100_000.0)[1], "PASS")   # "at least 100,000"
        self.assertEqual(self.verdict(volume_usdt=99_999.0)[1], "FAIL")
        tight = dict(T, max_move_since_announcement_pct=2)
        self.assertEqual(pc.evaluate(GOOD, tight)[1], "FAIL")               # changing the config changes it
        self.assertEqual(self.verdict(change_24h_pct=-50.0)[1], "PASS")     # falling is not "up"

    def test_the_thresholds_are_not_in_the_code(self):
        with open(os.path.join(HERE, "screener", "precheck.py")) as fh:
            code = fh.read().split('"""', 2)[2]
        for literal in ("100000", "100_000", "= 40", "= 15", "< 40", "< 15"):
            self.assertNotIn(literal, code)

    def test_every_failing_reason_is_named(self):
        _, verdict, line = self.verdict(spot="no", spot_text="NOT SPOT: derivatives only (perpetual/futures)",
                                        clash_count=3, move_pct=20.0, change_24h_pct=55.0,
                                        volume_usdt=10.0, stable=True, stable_note="USDT is a stablecoin ticker")
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(line.startswith("FAILS: "))
        for reason_ in ("spot: NOT SPOT: derivatives only", "not a ticker clash: 3 different coins share this ticker",
                        "move since the announcement: +20.0%", "24h change: +55.0%", "24h volume: 10 USDT",
                        "not a stablecoin or wrapped/staked token: USDT is a stablecoin ticker"):
            self.assertIn(reason_, line)

    def test_an_unknown_part_is_never_a_pass(self):
        _, verdict, line = self.verdict(spot="unknown", spot_text="lookup failed: boom")
        self.assertEqual(verdict, "FAIL")
        self.assertIn("spot: unverified (lookup failed: boom)", line)
        _, verdict, line = self.verdict(clash_count=None, clash_note="lookup failed: the scanner's CoinGecko budget "
                                                                       "for 2026-10 is used up")
        self.assertIn("not a ticker clash: unverified (lookup failed: the scanner's CoinGecko budget", line)

    def test_a_ticker_not_on_coingecko_still_passes_that_check(self):
        checks, verdict, _ = self.verdict(clash_count=0)
        self.assertEqual(verdict, "PASS")
        self.assertEqual(checks[1][2], "not on CoinGecko yet")

    def test_stablecoins_and_wrapped_tokens(self):
        self.assertTrue(pc.stable_or_wrapped("USDC", [], T)[0])
        self.assertTrue(pc.stable_or_wrapped("WBTC", ["Wrapped Bitcoin"], T)[0])
        self.assertTrue(pc.stable_or_wrapped("STETH", ["Lido Staked Ether"], T)[0])
        self.assertFalse(pc.stable_or_wrapped("FOO", ["Foo Network"], T)[0])
        self.assertFalse(pc.stable_or_wrapped("FOO", ["Wrappedness Coin"], T)[0])      # whole words only


# ---------------------------------------------------------------------
# The whole pre-check, inside the scanner
# ---------------------------------------------------------------------

def coinbase_world(change=10.0, volume=200_000.0, extra=()):
    """A Coinbase listing of DEMO (already in the demo market list) with healthy numbers."""
    open_ = 1.0
    return [("coins/list", [{"id": "demo-network", "symbol": "demo", "name": "Demo Network"}]),
            ("coins/markets", [{"id": "demo-network", "name": "Demo Network", "market_cap": 12_345_678}]),
            ("products/DEMO-USD/stats", {"open": str(open_), "last": str(open_ * (1 + change / 100)),
                                         "volume": str(volume)}), *extra]


class World(Http):
    """The scanner tests' feeds plus the exchanges' and CoinGecko's answers for the pre-check."""

    def __init__(self, routes=(), **kw):
        super().__init__(**kw)
        self.routes = list(routes)
        self.exchange_calls = []

    def json(self, url, headers=None):
        for text, answer in self.routes:
            if text in url:
                self.exchange_calls.append(url)
                if isinstance(answer, Exception):
                    raise answer
                return answer(url) if callable(answer) else copy.deepcopy(answer)
        return super().json(url, headers)


class FakeClaude:
    def __init__(self, **answer):
        self.answer = dict({"coin_name": "Demo Network", "coin_symbol": "DEMO", "about_one_coin": True,
                            "positive_catalyst": True, "catalyst_kind": "listing", "false_match": False,
                            "duplicate": False, "reason": "A genuine spot listing."}, **answer)
        self.requests = []
        self.messages = self

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.answer))],
                               usage=SimpleNamespace(input_tokens=500, output_tokens=60))


class GitHubLog(FakeGitHub):
    """Remembers what was known when each issue was created and each body set."""

    def __init__(self, world=None):
        super().__init__()
        self.world, self.created_at, self.bodies = world, [], {}

    def create(self, title, body, labels=None):
        n = super().create(title, body, labels)
        self.created_at.append((title, len(self.world.exchange_calls) if self.world else 0, body))
        return n

    def set_body(self, n, body):
        self.bodies.setdefault(n, []).append(body)
        super().set_body(n, body)


def scanner(world, gh=None, **kw):
    gh = gh or GitHubLog(world)
    sc = sa.Scanner(CFG, world, gh, gh, news_rows=lambda: [], out=lambda *a: None, **kw)
    return sc, gh


def alert_on(sc, gh, world, coins=("DEMO",), at=5):
    sc.run(polls=1, now_fn=lambda: NOW)                                         # the baseline
    sc.http = sc.prices.http = world
    if sc.pre is not None:
        sc.pre.http = world
    sc.run(polls=1, now_fn=lambda: NOW + at * MIN)


class PipelineTests(unittest.TestCase):
    def listed(self, routes, **kw):
        base = World(markets={}, routes=routes)
        sc, gh = scanner(base, **kw)
        world = World(routes=routes, markets={"coinbase": ["DEMO"]})
        gh.world = world
        alert_on(sc, gh, world)
        return sc, gh, world

    def test_a_passing_listing_gets_the_whole_section(self):
        sc, gh, _ = self.listed(coinbase_world(), ai_client=FakeClaude())
        (issue,) = gh.alerts()
        body = issue["body"]
        self.assertEqual(body.split("\n")[0], "@Asayed36")
        self.assertIn("### Pre-check (information, not advice)", body)
        self.assertIn("1. **What it is:** Demo Network (DEMO) on Coinbase.", body)
        self.assertIn("no announcement text: the coin appeared in the exchange's public market list", body)
        self.assertIn("2. **Spot or not:** SPOT: yes (pairs: DEMO-USD)", body)
        self.assertIn("3. **Ticker on CoinGecko:** 1 coin(s) use DEMO: Demo Network (market cap $12,345,678).", body)
        self.assertIn("**Price on Coinbase (DEMO-USD):** last 1.1 USD, 24h change +10.0%, 24h volume 220,000 USDT.", body)
        self.assertIn("Price at detection 1.1 USD", body)
        self.assertIn("since detection", body)
        self.assertIn("**PASSES the basic checks** (information, not advice)", body)
        self.assertIn("6. **AI second opinion (Claude Haiku 4.5, it decides nothing):** YES: a real new listing", body)
        self.assertEqual(body.count("Pre-check"), 1)
        self.assertNotIn("Looking things up", body)

    def test_a_failing_listing_names_each_reason(self):
        _, gh, _ = self.listed(coinbase_world(change=55.0, volume=1000.0,
                                              extra=[("coins/list", [{"id": "a", "symbol": "demo", "name": "A"},
                                                                     {"id": "b", "symbol": "demo", "name": "B"}])]))
        body = gh.alerts()[0]["body"]
        self.assertIn("**FAILS: ", body)
        self.assertIn("24h change: +55.0% (limit +40%)", body)
        self.assertIn("24h volume: 1,550 USDT (at least 100,000)", body)

    def test_the_alert_goes_out_first_with_the_pre_check_still_to_come(self):
        sc, gh, world = self.listed(coinbase_world())
        (title, calls_then, body_then), = [c for c in gh.created_at if c[0].startswith("ALERT")]
        self.assertEqual(calls_then, 0)                         # no exchange or CoinGecko lookup had begun
        self.assertIn("Looking things up", body_then)
        self.assertEqual(body_then.split("\n")[0], "@Asayed36")
        self.assertGreater(len(world.exchange_calls), 0)        # ... and they happened right after

    def test_several_alerts_are_all_out_before_any_lookup(self):
        base = World(routes=coinbase_world())
        sc, gh = scanner(base)
        world = World(routes=coinbase_world(), markets={"coinbase": ["DEMO", "OTHER"]})
        gh.world = world
        alert_on(sc, gh, world)
        self.assertEqual(len(gh.alerts()), 2)
        self.assertEqual([c[1] for c in gh.created_at if c[0].startswith("ALERT")], [0, 0])

    def test_a_failing_lookup_never_stops_the_alert(self):
        # (only the exchange's stats and CoinGecko's list are cut, not the feed that makes the alert)
        down = [("products/DEMO-USD/stats", ApiError("stats down")),
                ("coins/list", ApiError("coin list down"))]
        sc, gh, _ = self.listed(down)
        (issue,) = gh.alerts()
        self.assertEqual(issue["body"].split("\n")[0], "@Asayed36")
        self.assertIn("lookup failed: ", issue["body"])
        self.assertIn("coin list down", issue["body"])
        self.assertIn("stats down", issue["body"])
        self.assertIn("**FAILS: ", issue["body"])
        self.assertIn("6. **AI second opinion (Claude Haiku 4.5, it decides nothing):** not checked", issue["body"])
        self.assertIn(issue["number"], gh.assigned)            # assigned as before

    def test_even_a_crash_in_the_pre_check_leaves_the_alert_and_says_so(self):
        base = World(routes=coinbase_world())
        sc, gh = scanner(base)
        sc.pre.run = lambda alert, now: (_ for _ in ()).throw(RuntimeError("boom"))
        world = World(routes=coinbase_world(), markets={"coinbase": ["DEMO"]})
        gh.world = world
        alert_on(sc, gh, world)
        (issue,) = gh.alerts()
        self.assertIn("lookup failed: boom", issue["body"])
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists DEMO"])

    def test_a_failing_edit_leaves_the_alert_as_sent(self):
        base = World(routes=coinbase_world())
        sc, gh = scanner(base)
        gh.set_body = lambda n, b: (_ for _ in ()).throw(GitHubError("502"))
        world = World(routes=coinbase_world(), markets={"coinbase": ["DEMO"]})
        gh.world = world
        alert_on(sc, gh, world)
        self.assertEqual(len(gh.alerts()), 1)
        self.assertTrue(any("could not fill the pre-check into #" in n for n in sc.notes))

    def test_news_alerts_and_the_over_the_cap_summary_get_no_pre_check(self):
        from tests.test_scanner_alert import row
        base = World(routes=coinbase_world())
        sc, gh = scanner(base)
        sc.news_rows = lambda: [row("FOO")]
        sc.memory.new = False
        sc.run(polls=1, now_fn=lambda: NOW)
        news = next(i for i in gh.alerts() if i["title"] == "ALERT: news FOO")
        self.assertNotIn("Pre-check", news["body"])
        world = World(routes=coinbase_world(), markets={"coinbase": [f"C{i:02d}" for i in range(12)]})
        gh.world = world
        sc.http = sc.prices.http = sc.pre.http = world
        sc.run(polls=1, now_fn=lambda: NOW + 2 * MIN)
        listings = [i for i in gh.alerts() if i["title"].startswith("ALERT: Coinbase lists")]
        summary = next(i for i in gh.alerts() if i["title"].startswith("ALERT summary"))
        self.assertEqual(len(listings), 9)                       # 10 a day in all, one of them the news alert
        self.assertTrue(all("Pre-check (information" in i["body"] for i in listings))
        self.assertNotIn("Pre-check", summary["body"])
        self.assertEqual(summary["body"].split("\n")[0], "@Asayed36")

    def test_detection_dedup_cap_mention_and_assignment_are_untouched(self):
        sc, gh, world = self.listed(coinbase_world())
        self.assertEqual(gh.titles(), ["ALERT: Coinbase lists DEMO"])
        self.assertEqual(gh.assigned, {gh.alerts()[0]["number"]: "Asayed36"})
        sc.run(polls=1, now_fn=lambda: NOW + 9 * MIN)                      # the same coin again: nothing
        self.assertEqual(len(gh.alerts()), 1)
        self.assertEqual([i["labels"] for i in gh.alerts()], [[{"name": "scanner-alert"}]])

    def test_a_dry_run_prints_the_section_and_writes_nothing(self):
        printed = []
        world = World(routes=coinbase_world())
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scanner", "alert_checks.csv")
            sc = sa.Scanner(CFG, world, None, None, news_rows=lambda: [], out=printed.append, checks_path=path)
            sc.run(polls=1, now_fn=lambda: NOW, fake="Coinbase:DEMO", dry_run=True)
            self.assertFalse(os.path.exists(path))
        text = "\n".join(printed)
        self.assertIn("WOULD OPEN: ALERT: Coinbase lists DEMO\n@Asayed36\n", text)
        self.assertIn("### Pre-check (information, not advice)", text)

    def test_the_pre_check_can_be_turned_off_in_the_config(self):
        cfg = copy.deepcopy(CFG)
        cfg["scanner_alert"]["precheck"]["enabled"] = False
        base = World(routes=coinbase_world())
        gh = GitHubLog(base)
        sc = sa.Scanner(cfg, base, gh, gh, news_rows=lambda: [], out=lambda *a: None)
        world = World(routes=coinbase_world(), markets={"coinbase": ["DEMO"]})
        gh.world = world
        alert_on(sc, gh, world)
        self.assertNotIn("Pre-check", gh.alerts()[0]["body"])
        self.assertEqual(world.exchange_calls, [])


class AnnouncementTests(unittest.TestCase):
    """A Binance announcement: the exchange's own time, so the move since it is measured."""

    def run_for(self, then, now_price):
        ms = int((NOW + 3 * MIN).timestamp() * 1000)
        routes = [("coins/list", [{"id": "foo", "symbol": "foo", "name": "Foo"}]),
                  ("coins/markets", [{"name": "Foo", "market_cap": 1_000_000}]),
                  ("ticker/price", [{"symbol": "FOOUSDT", "price": "1"}]),
                  ("ticker/24hr", {"lastPrice": str(now_price), "priceChangePercent": "5", "quoteVolume": "900000"}),
                  ("klines", [] if then is None else [[ms, str(then), "1", "1", "1", "1"]])]
        world = World(routes=routes, binance=[("Binance Will List Foo (FOO) with Seed Tag", NOW + 3 * MIN)])
        gh = GitHubLog(world)
        sc = sa.Scanner(CFG, world, gh, gh, news_rows=lambda: [], out=lambda *a: None)
        sc.run(polls=1, now_fn=lambda: NOW)
        world.binance = [("Binance Will List Foo (FOO) with Seed Tag", NOW + 3 * MIN)]
        sc.http = sc.prices.http = sc.pre.http = world
        # a new announcement after the baseline
        world.binance = [("Binance Will List Foo (FOO) with Seed Tag", NOW + 3 * MIN),
                         ("Binance Will List Foo2 (FOO) soon", NOW + 3 * MIN)]
        world.binance = [("Binance Will List Foo (FOO) with Seed Tag", NOW + 3 * MIN)]
        sc.memory.state["alerted"].clear()
        sc.run(polls=1, now_fn=lambda: NOW + 4 * MIN)
        return gh

    def test_the_move_since_the_announcement_is_measured_from_the_exchanges_price_then(self):
        gh = self.run_for(then=1.0, now_price=1.1)
        body = gh.alerts()[0]["body"]
        self.assertIn("announcement time:** 2026-10-11 12:03 UTC", body)
        self.assertIn("Price at the announcement 1: +10.0% since.", body)
        self.assertIn("PASSES the basic checks", body)
        gh = self.run_for(then=1.0, now_price=1.2)
        self.assertIn("move since the announcement: +20.0% (limit +15%)", gh.alerts()[0]["body"])

    def test_a_pair_with_no_trades_at_the_announcement_is_not_a_failure(self):
        gh = self.run_for(then=None, now_price=1.0)
        body = gh.alerts()[0]["body"]
        self.assertIn("the pair had no trades yet at the announcement", body)
        self.assertIn("PASSES the basic checks", body)


class AiTests(unittest.TestCase):
    def run_alert(self, **kw):
        world = World(routes=coinbase_world(), markets={})
        gh = GitHubLog(world)
        sc = sa.Scanner(CFG, world, gh, gh, news_rows=lambda: [], out=lambda *a: None, **kw)
        world2 = World(routes=coinbase_world(), markets={"coinbase": ["DEMO"]})
        gh.world = world2
        alert_on(sc, gh, world2)
        return sc, gh

    def test_no_key_means_not_checked(self):
        _, gh = self.run_alert()
        self.assertIn("not checked (no CLAUDE_API_KEY secret)", gh.alerts()[0]["body"])

    def test_the_answer_is_short_and_decides_nothing(self):
        for answer, text in ((dict(), "YES: a real new listing of a real project"),
                             (dict(catalyst_kind="other", positive_catalyst=False, reason="A perpetual contract."),
                              "NO: something else")):
            client = FakeClaude(**answer)
            sc, gh = self.run_alert(ai_client=client)
            body = gh.alerts()[0]["body"]
            self.assertIn(text, body)
            self.assertIn("**PASSES the basic checks**", body)        # the verdict does not depend on the AI
            prompt = client.requests[0]["messages"][0]["content"]
            self.assertIn("Facts from the exchange's public lists: spot: SPOT: yes", prompt)

    def test_the_existing_daily_limit_is_used(self):
        client = FakeClaude()
        limit = min(CFG["news"]["ai"]["daily_limit"], T["ai_daily_limit"])
        sc, gh = self.run_alert(ai_client=client)
        self.assertEqual(sc.memory.state["precheck"]["ai"]["limit"], limit)
        self.assertEqual(sc.memory.state["precheck"]["ai"]["calls"], 1)
        sc.memory.state["precheck"]["ai"]["calls"] = limit
        client2 = FakeClaude()
        sc2, gh2 = self.run_alert(ai_client=client2)
        sc2.memory.state["precheck"]["ai"]["calls"] = limit
        r = sc2.pre.run(sa.Alert(kind="listing", exchange="Coinbase", coin="DEMO", coin_id=None,
                                 source="Coinbase new pairs", title="x", url="", text="", seen=NOW.isoformat(),
                                 announced=None, how="a new pair in its public market list",
                                 key="listing|coinbase|DEMO", test=False, reason=""), NOW)
        self.assertEqual(r["ai"], f"not checked (daily limit of {limit} AI checks reached)")


# ---------------------------------------------------------------------
# The CSV and the follow-ups
# ---------------------------------------------------------------------

class CsvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "scanner", "alert_checks.csv")

    def rows(self):
        with open(self.path, newline="") as fh:
            return list(csv.DictReader(fh))

    def alert(self, routes=None, coins=("DEMO",), clock=None, **kw):
        routes = routes or coinbase_world()
        world = World(routes=routes)
        gh = GitHubLog(world)
        sc = sa.Scanner(CFG, world, gh, gh, news_rows=lambda: [], out=lambda *a: None,
                        checks_path=self.path, ai_client=FakeClaude(), **kw)
        w2 = World(routes=routes, markets={"coinbase": list(coins)})
        gh.world = w2
        alert_on(sc, gh, w2)
        return sc, gh, w2

    def test_one_row_per_alert_with_every_check(self):
        self.alert(coins=("DEMO", "OTHER"), routes=coinbase_world() + [("products/OTHER-USD/stats", ApiError("x"))])
        rows = self.rows()
        self.assertEqual(list(rows[0]), pc.COLUMNS)
        self.assertEqual([r["ticker"] for r in rows], ["DEMO", "OTHER"])
        r = rows[0]
        self.assertEqual((r["feed"], r["exchange"], r["name"], r["spot"], r["pair"], r["clash_count"]),
                         ("Coinbase new pairs", "Coinbase", "Demo Network", "yes", "DEMO-USD", "1"))
        self.assertEqual((r["price_at_detection"], r["exchange_change_24h_pct"], r["volume_24h_usdt"]), ("1.1", "10", "220000"))
        self.assertEqual((r["check_spot"], r["check_clash"], r["check_move"], r["check_24h"], r["check_volume"],
                          r["check_not_stable"]), ("pass",) * 6)
        self.assertEqual((r["verdict"], r["verdict_line"]), ("PASS", "PASSES the basic checks"))
        self.assertIn("YES", r["ai_answer"])
        self.assertEqual(r["time_utc"], "2026-10-11 12:05:00")
        self.assertEqual(r["issue"], "2")                    # (#1 is the scanner's memory issue)
        o = rows[1]                                          # a lookup that failed: still a row, never blank-zero
        self.assertEqual((o["spot"], o["check_24h"], o["verdict"]), ("yes", "unknown", "FAIL"))
        self.assertEqual(o["price_at_detection"], "")

    def test_a_second_run_does_not_repeat_a_row(self):
        sc, gh, w2 = self.alert()
        sc.run(polls=1, now_fn=lambda: NOW + 9 * MIN)
        self.assertEqual(len(self.rows()), 1)

    def test_followups_at_1_6_and_24_hours_for_passes_and_fails_alike(self):
        sc, gh, w2 = self.alert(coins=("DEMO", "OTHER"),
                                routes=coinbase_world() + [
                                    ("products/OTHER-USD/stats", {"open": "1", "last": "1.5", "volume": "10"}),
                                    ("coins/list", [{"id": "d", "symbol": "demo", "name": "D"},
                                                    {"id": "o", "symbol": "other", "name": "O"}])])
        rows = self.rows()
        self.assertEqual({r["ticker"]: r["verdict"] for r in rows}, {"DEMO": "PASS", "OTHER": "FAIL"})
        prices = {"DEMO-USD": ["1.2", "1.5", "0.9"], "OTHER-USD": ["2", "3", "4"]}
        step = {"n": 0}

        def stats(url):
            pair = re.search(r"products/([A-Z]+-USD)/stats", url).group(1)
            return {"open": "1", "last": prices[pair][step["n"]], "volume": "1"}
        w2.routes = [("products/", stats)] + w2.routes
        for n, hours in enumerate((1, 6, 24)):
            step["n"] = n
            sc.run(polls=1, now_fn=lambda h=hours: NOW + 5 * MIN + timedelta(hours=h, minutes=1))
        rows = self.rows()
        by = {r["ticker"]: r for r in rows}
        self.assertEqual([by["DEMO"][f"price_{k}"] for k in ("1h", "6h", "24h")], ["1.2", "1.5", "0.9"])
        self.assertEqual([by["OTHER"][f"price_{k}"] for k in ("1h", "6h", "24h")], ["2", "3", "4"])
        self.assertEqual(by["DEMO"]["change_1h_pct"], f"{(1.2 / 1.1 - 1) * 100:.4g}")
        self.assertTrue(by["DEMO"]["time_24h"].startswith("2026-10-12 12:06"))

    def test_a_failed_followup_is_retried_and_a_missed_one_stays_blank(self):
        sc, gh, w2 = self.alert()
        w2.routes = [("products/DEMO-USD/stats", ApiError("down"))] + w2.routes
        sc.run(polls=1, now_fn=lambda: NOW + 5 * MIN + timedelta(hours=1, minutes=1))
        self.assertEqual(self.rows()[0]["price_1h"], "")                       # not zero
        w2.routes = [("products/DEMO-USD/stats", {"open": "1", "last": "2", "volume": "1"})] + w2.routes
        sc.run(polls=1, now_fn=lambda: NOW + 5 * MIN + timedelta(hours=1, minutes=5))
        self.assertEqual(self.rows()[0]["price_1h"], "2")                      # tried again within the grace time
        # a price whose grace time (30 min) has passed is not saved late
        checks = pc.AlertChecks(self.path)
        detected = datetime(2026, 10, 11, 12, 5)
        self.assertEqual([n for _, n in checks.due(detected + timedelta(hours=6, minutes=10))], ["6h"])
        self.assertEqual([n for _, n in checks.due(detected + timedelta(hours=2))], [])

    def test_the_log_is_not_touched_by_a_dry_run_or_without_a_path(self):
        world = World(routes=coinbase_world(), markets={"coinbase": ["DEMO"]})
        gh = GitHubLog(world)
        sc = sa.Scanner(CFG, world, gh, gh, news_rows=lambda: [], out=lambda *a: None)
        alert_on(sc, gh, world)
        self.assertFalse(os.path.exists(self.path))


class SafetyTests(unittest.TestCase):
    def test_it_only_reads_and_trades_nothing(self):
        with open(os.path.join(HERE, "screener", "precheck.py")) as fh:
            code = fh.read()
        for forbidden in ("requests.post", ".post(", "paper_trader", "PaperTrader", "wallet_key",
                          "private_key", "sign("):
            self.assertNotIn(forbidden, code.split('"""', 2)[2])
        self.assertNotIn("import requests", code)             # only the scanner's own read-only HTTP object

    def test_the_precheck_config_is_in_config_toml(self):
        for key in ("max_move_since_announcement_pct", "max_change_24h_pct", "min_volume_24h_usdt",
                    "stablecoin_symbols", "wrapped_words", "coingecko_monthly_calls", "ai_daily_limit"):
            self.assertIn(key, T)

    def test_the_workflow_saves_the_log_and_uses_only_existing_secrets(self):
        with open(os.path.join(HERE, ".github", "workflows", "scanner-alert.yml")) as fh:
            text = fh.read()
        self.assertIn("git add data/scanner", text)
        self.assertEqual(sorted(set(re.findall(r"secrets\.(\w+)", text))), ["CLAUDE_API_KEY", "COINGECKO_API_KEY"])
        self.assertIn("contents: write", text)
        with open(os.path.join(HERE, ".gitignore")) as fh:
            self.assertIn("!data/scanner/alert_checks.csv", fh.read())


if __name__ == "__main__":
    unittest.main()
