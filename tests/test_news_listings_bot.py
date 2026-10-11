"""Checks for the news listings bot (news_listings_bot.py): the news
strategy's exchange listings, every minute on the server, with made-up
sources and a made-up Claude. Run with:  python -m unittest -v
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

import news_listings_bot as nl  # noqa: E402
from screener.demo import DemoClaude, DemoNewsHttp  # noqa: E402
from screener.news import FastNewsTrader, NewsStrategy  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402

CFG = running(load_config())
# Without the 1.5% buy slippage, for the tests about the exit rules.
NOSLIP = dict(CFG, news_listings=dict(
    {k: v for k, v in CFG["news_listings"].items() if k != "buy_slippage_pct"},
    fast=dict(CFG["news_listings"]["fast"], paper_trading={
        k: v for k, v in CFG["news_listings"]["fast"]["paper_trading"].items()
        if k != "buy_slippage_pct"})))
NOW = datetime(2026, 9, 24, 13, 30, tzinfo=timezone.utc)
SERVER = ["Binance listings", "Kraken blog", "Coinbase new pairs", "Upbit new markets",
          "OKX new markets"]
QUIET = dict(out=lambda *a: None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "news-listings")
        # listing_track.csv has its own tests (TrackTests): off here, so the
        # other tests count the trading's own requests
        patch = mock.patch.object(nl, "TRACK_LISTINGS", False)
        patch.start()
        self.addCleanup(patch.stop)

    def bot(self, http=None, ai=None):
        return nl.NewsListings(CFG, self.tmp.name, http or DemoNewsHttp(now=NOW), None, None,
                               ai or DemoClaude())

    def state(self):
        with open(os.path.join(self.folder, "positions.json")) as fh:
            return json.load(fh)

    def health(self):
        with open(os.path.join(self.folder, "health.json")) as fh:
            return json.load(fh)


class SplitTests(Base):
    def test_the_exchange_listings_moved_to_the_server(self):
        self.assertEqual([s["name"] for s in self.bot().strategy().sources], SERVER)
        github = [s["name"] for s in NewsStrategy(CFG, self.tmp.name).sources]
        self.assertFalse(set(SERVER) & set(github))
        self.assertIn("OKX listings", github)            # OKX's announcements stay on GitHub
        self.assertIn("PR Newswire", github)
        self.assertEqual(len(github) + len(SERVER), len(CFG["news"]["sources"]))

    def test_same_checks_costs_and_exits(self):
        c, news = nl.listings_config(CFG)["news"], CFG["news"]
        for key in ("max_age_minutes", "min_market_cap_usd", "min_volume_usd",
                    "max_change_1h_pct", "max_change_24h_pct", "cooldown_days", "catalyst_words",
                    "exchange_words", "hype_words", "bad_news_words", "institutions",
                    "unambiguous_names", "crypto_words"):
            self.assertEqual(c[key], news[key], key)
        # the same paper trading, plus its 1.5% buy slippage
        self.assertEqual(c["paper_trading"], dict(news["paper_trading"], buy_slippage_pct=1.5))
        self.assertEqual({k: v for k, v in c["ai"].items() if k != "daily_limit"},
                         {k: v for k, v in news["ai"].items() if k != "daily_limit"})
        own = CFG["news_listings"]
        self.assertEqual((c["every_minutes"], c["coingecko_monthly_calls"], c["ai"]["daily_limit"],
                          c["prices_every_minutes"]),
                         (0, own["coingecko_monthly_calls"], own["ai_daily_limit"],
                          own["prices_every_minutes"]))
        # both CoinGecko counts together stay under the free plan's 10,000
        self.assertLessEqual(news["coingecko_monthly_calls"] + own["coingecko_monthly_calls"],
                             10_000)


class RunTests(Base):
    def test_finds_a_new_pair_and_paper_buys_it(self):
        bot = self.bot()
        lines = []
        bot.run_once(NOW, lines.append)
        self.assertEqual(lines, ["13:30 5/5 source(s) ok, 0 new item(s); 0 open; P&L $+0.00"])
        self.assertEqual(sorted(self.state()["markets"]),
                         ["Coinbase new pairs", "OKX new markets", "Upbit new markets"])
        later = NOW + timedelta(minutes=1)
        bot.http.http = DemoNewsHttp(now=later, markets={"upbit": ["DEMO"]})
        lines = []
        (pos,) = bot.run_once(later, lines.append)
        self.assertEqual((pos["symbol"], pos["cost_usd"]), ("DEMO", 10.0))
        text = "\n".join(lines)
        self.assertIn("[PASS] DEMO  Upbit new markets: Upbit lists Demo (DEMO) for trading", text)
        self.assertIn("AI   yes: Demo Network (DEMO)", text)
        self.assertIn("BUY  DEMO", text)
        for name in ("journal.csv", "candidates.csv", "ai_verdicts.csv", "entries.csv"):
            self.assertTrue(os.path.exists(os.path.join(self.folder, name)), name)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "news")))  # GitHub's untouched
        self.assertNotIn("issues_to_close", self.state())
        self.assertNotIn(".tmp", " ".join(os.listdir(self.folder)))

    def test_open_positions_priced_every_15_minutes(self):
        # news (listings) alone (its fast version's own price checks are
        # tested in FastTests)
        cfg = dict(CFG, news_listings=dict(CFG["news_listings"], fast={"enabled": False}))
        bot = nl.NewsListings(cfg, self.tmp.name, DemoNewsHttp(now=NOW), None, None, DemoClaude())
        bot.run_once(NOW, **QUIET)
        bot.http.http = DemoNewsHttp(now=NOW, markets={"coinbase": ["DEMO"]})
        bot.run_once(NOW + timedelta(minutes=1), **QUIET)          # bought
        calls = []
        for minute in range(2, 33):
            bot.http.http = DemoNewsHttp(now=NOW, markets={"coinbase": ["DEMO"]})
            bot.run_once(NOW + timedelta(minutes=minute), **QUIET)
            calls += [u for u in bot.http.http.calls if "coingecko" in u]
        self.assertEqual(len(calls), 3)            # minutes 2, 17 and 32
        self.assertEqual(self.state()["coingecko"]["calls"], 2 + 3)

    def test_health_counts_requests(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        bot.run_once(NOW + timedelta(minutes=1), **QUIET)
        hour = self.health()["calls_per_hour"]["2026-09-24T13:00"]
        self.assertEqual(hour["runs"], 2)
        self.assertEqual(hour["binance.com"], 2)
        self.assertEqual(hour["exchange.coinbase.com"], 2)
        self.assertEqual(self.health()["last_ok"], (NOW + timedelta(minutes=1)).isoformat())

    def test_without_a_key_the_rules_decide(self):
        bot = nl.NewsListings(CFG, self.tmp.name, DemoNewsHttp(now=NOW), None, None, None)
        bot.run_once(NOW, **QUIET)
        bot.http.http = DemoNewsHttp(now=NOW, markets={"okx": ["DEMO"]})
        (pos,) = bot.run_once(NOW + timedelta(minutes=1), **QUIET)
        self.assertEqual(pos["symbol"], "DEMO")
        self.assertFalse(self.health()["ai_key"])


class FastTests(Base):
    """news (listings) fast: the same signals at the same moment and price,
    exits within hours, its own files; news (listings) unchanged. (Without
    the buy slippage, so the moves are from the market price: SlippageTests.)"""

    def setUp(self):
        super().setUp()
        self.fast_folder = os.path.join(self.folder, "fast")

    def bot(self, http=None, ai=None):
        return nl.NewsListings(NOSLIP, self.tmp.name, http or DemoNewsHttp(now=NOW), None,
                               None, ai or DemoClaude())

    def fast_state(self):
        with open(os.path.join(self.fast_folder, "positions.json")) as fh:
            return json.load(fh)

    def journal(self, folder):
        import csv
        with open(os.path.join(folder, "journal.csv")) as fh:
            return list(csv.DictReader(fh))

    def run_at(self, bot, minutes, moves=None, lines=None):
        bot.http.http = DemoNewsHttp(now=NOW, markets={"coinbase": ["DEMO"]},
                                     price_moves={"demo-network": moves} if moves else None)
        bot.run_once(NOW + timedelta(minutes=minutes),
                     out=(lines.append if lines is not None else lambda *a: None))
        return bot.http.http.calls

    def bought(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)                                 # the listing: both buy
        return bot

    def test_settings(self):
        fast = CFG["news_listings"]["fast"]
        self.assertTrue(fast["enabled"])
        self.assertEqual(fast["label"], "news (listings) fast")
        pt = fast["paper_trading"]
        self.assertEqual((pt["take_profit_pct"], pt["take_profit_sell_fraction"],
                          pt["trailing_stop_pct"], pt["stop_loss_pct"], pt["max_hold_hours"]),
                         (20, 0.5, 10, 10, 6))
        news = CFG["news"]["paper_trading"]
        self.assertEqual((pt["buy_amount_usd"], pt["round_trip_cost_pct"], pt["buy_slippage_pct"]),
                         (news["buy_amount_usd"], news["round_trip_cost_pct"],
                          CFG["news_listings"]["buy_slippage_pct"]))
        # news (listings) keeps the news strategy's exits (plus its buy slippage)
        self.assertEqual(nl.listings_config(CFG)["news"]["paper_trading"],
                         dict(news, buy_slippage_pct=1.5))
        self.assertEqual((news["take_profit_pct"], news["max_hold_days"]), (50, 7))

    def test_buys_the_same_signal_at_the_same_moment_and_price(self):
        self.bought()
        (main,) = self.state()["open_positions"]
        (fast,) = self.fast_state()["open_positions"]
        for key in ("address", "symbol", "entry_time", "entry_price", "cost_usd", "news"):
            self.assertEqual(main[key], fast[key], key)
        self.assertNotIn("issue_details", fast)
        for name in ("journal.csv", "entries.csv", "positions.json"):
            self.assertTrue(os.path.exists(os.path.join(self.fast_folder, name)), name)
        (row,) = self.journal(self.fast_folder)
        self.assertEqual((row["action"], row["symbol"]), ("BUY", "DEMO"))
        self.assertEqual(len(self.journal(self.folder)), 1)   # news (listings)' own journal

    def test_fast_exits_while_news_listings_holds_on(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)
        lines = []
        self.run_at(bot, 3, 1.25, lines)                    # +25%: fast sells half
        self.assertIn("(fast) take profit: up 25%", "\n".join(lines))
        (fast,) = self.fast_state()["open_positions"]
        self.assertEqual(fast["remaining_fraction"], 0.5)
        self.run_at(bot, 5, 1.30)                           # new peak +30%
        self.run_at(bot, 7, 1.20)                           # 7.7% below the peak: holds
        self.assertEqual(len(self.fast_state()["open_positions"]), 1)
        self.run_at(bot, 9, 1.16)                           # 10.8% below the peak
        self.assertEqual(self.fast_state()["open_positions"], [])
        sells = [r["reason"] for r in self.journal(self.fast_folder) if r["action"] == "SELL"]
        self.assertEqual(sells, ["take profit: up 25%", "trailing stop: down 11% from peak"])
        # news (listings) is unchanged: +16% is nothing to it
        (main,) = self.state()["open_positions"]
        self.assertEqual(main["remaining_fraction"], 1.0)

    def test_stop_loss_and_time_limit(self):
        bot = self.bought()
        self.run_at(bot, 3, 0.89)                           # -11%
        self.assertEqual(self.fast_state()["open_positions"], [])
        self.assertIn("stop loss: down 11% from entry",
                      self.journal(self.fast_folder)[-1]["reason"])
        self.assertEqual(len(self.state()["open_positions"]), 1)   # -20% for news (listings)

    def test_time_limit(self):
        bot = self.bought()
        self.run_at(bot, 6 * 60 - 1, 1.05)
        self.assertEqual(len(self.fast_state()["open_positions"]), 1)
        self.run_at(bot, 6 * 60 + 1, 1.05)                  # 6 hours after the buy
        self.assertEqual(self.fast_state()["open_positions"], [])
        self.assertEqual(self.journal(self.fast_folder)[-1]["reason"], "time limit: 6 h (+5%)")
        self.assertEqual(len(self.state()["open_positions"]), 1)

    def test_trailing_stop_only_after_half_is_sold(self):
        trader = FastNewsTrader(NOSLIP["news_listings"]["fast"]["paper_trading"], self.tmp.name)
        coin = mock.Mock(address="x", symbol="X", price=1.0, pair=None, insider=None)
        trader.buy(coin, when=NOW)
        later = NOW + timedelta(minutes=10)
        self.assertEqual(trader.update({"x": 1.18}, when=later), [])
        self.assertEqual(trader.update({"x": 1.05}, when=later), [])   # 11% below its peak
        (sell,) = trader.update({"x": 0.899}, when=later)
        self.assertEqual(sell["reason"], "stop loss: down 10% from entry")

    def test_prices_every_2_minutes_only_while_holding(self):
        idle = tempfile.TemporaryDirectory()
        self.addCleanup(idle.cleanup)
        bot = nl.NewsListings(CFG, idle.name, DemoNewsHttp(now=NOW), None, None, DemoClaude())
        calls = []
        for minute in range(0, 10):                         # nothing held: no price checks
            bot.http.http = DemoNewsHttp(now=NOW)
            bot.run_once(NOW + timedelta(minutes=minute), **QUIET)
            calls += [u for u in bot.http.http.calls if "coingecko" in u]
        self.assertEqual(calls, [])

        bot = self.bought()
        calls = []
        for minute in range(2, 13):
            calls += [u for u in self.run_at(bot, minute) if "coingecko" in u]
        # news (listings) at minute 2 (reused by fast); fast's own at 4, 6, 8, 10 and 12
        self.assertEqual(len(calls), 6)
        self.assertEqual(self.fast_state()["last_prices"],
                         (NOW + timedelta(minutes=12)).isoformat())

    def test_time_limit_closes_at_the_last_price_without_coingecko(self):
        bot = self.bought()
        self.run_at(bot, 3, 1.04)
        # CoinGecko's monthly count used up
        state = self.state()
        state["coingecko"]["calls"] = NOSLIP["news_listings"]["coingecko_monthly_calls"]
        with open(os.path.join(self.folder, "positions.json"), "w") as fh:
            json.dump(state, fh)
        lines = []
        self.run_at(bot, 6 * 60 + 2, 1.5, lines)
        self.assertEqual(self.fast_state()["open_positions"], [])
        last = self.journal(self.fast_folder)[-1]
        self.assertRegex(last["reason"], r"^time limit: 6 h \(\+4%\), closed at last known price "
                                         r"\(from \d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC\)$")
        self.assertEqual(last["price_time_utc"], last["reason"][-24:-5])   # the old price's time

    def test_turned_off(self):
        cfg = dict(CFG, news_listings=dict(CFG["news_listings"], fast={"enabled": False}))
        bot = nl.NewsListings(cfg, self.tmp.name, DemoNewsHttp(now=NOW), None, None, DemoClaude())
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)
        self.assertEqual(len(self.state()["open_positions"]), 1)
        self.assertFalse(os.path.exists(self.fast_folder))


class AuditFixTests(Base):
    """2026-10-09: 1.5% buy slippage for both listings versions, prices'
    source and fetch time, every listing's price, and a held coin's later
    listings recorded with its position (never bought again)."""

    def journal(self, folder):
        import csv
        with open(os.path.join(folder, "journal.csv")) as fh:
            return list(csv.DictReader(fh))

    def candidates(self):
        import csv
        with open(os.path.join(self.folder, "candidates.csv")) as fh:
            return list(csv.DictReader(fh))

    def bought(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        bot.http.http = DemoNewsHttp(now=NOW, markets={"coinbase": ["DEMO"]})
        bot.run_once(NOW + timedelta(minutes=1), **QUIET)
        return bot

    def test_both_versions_pay_1_5_percent_over_coingeckos_price(self):
        self.bought()
        fast_folder = os.path.join(self.folder, "fast")
        for folder in (self.folder, fast_folder):
            (buy,) = self.journal(folder)
            self.assertAlmostEqual(float(buy["price_usd"]), 70.0 * 1.015)   # DEMO is $70
            self.assertIn("paid +1.5% over the market price $70", buy["reason"])
            self.assertEqual(buy["price_source"], "CoinGecko")
            self.assertTrue(buy["price_time_utc"])
            with open(os.path.join(folder, "positions.json")) as fh:
                state = json.load(fh)
            self.assertEqual(state["buy_slippage"]["pct"], 1.5)
            self.assertEqual(state["open_positions"][0]["market_price_at_entry"], 70.0)

    def test_every_listings_price_is_recorded(self):
        self.bought()
        (row,) = self.candidates()
        self.assertEqual((row["symbol"], row["verdict"], row["price_usd"]), ("DEMO", "PASS", "70"))
        self.assertTrue(row["price_time_utc"])

    def test_a_held_coins_new_listing_is_recorded_not_bought(self):
        bot = self.bought()
        bot.http.http = DemoNewsHttp(now=NOW, markets={"coinbase": ["DEMO"], "upbit": ["DEMO"]},
                                     price_moves={"demo-network": 1.1})
        lines = []
        bot.run_once(NOW + timedelta(minutes=2), lines.append)
        self.assertIn("NOTE DEMO", "\n".join(lines))
        upbit = self.candidates()[-1]
        self.assertEqual((upbit["source"], upbit["verdict"], upbit["price_usd"]),
                         ("Upbit new markets", "FAIL", "77"))
        for folder in (self.folder, os.path.join(self.folder, "fast")):
            rows = self.journal(folder)
            self.assertEqual([r["action"] for r in rows], ["BUY", "LISTING"])   # no second buy
            self.assertIn("also listed while held: Upbit lists", rows[1]["reason"])
            self.assertIn("+8.4% since our buy", rows[1]["reason"])   # 77 vs 70 * 1.015
            self.assertEqual((rows[1]["pnl_usd"], rows[1]["price_source"]), ("0.00", "CoinGecko"))
            with open(os.path.join(folder, "positions.json")) as fh:
                state = json.load(fh)
            (pos,) = state["open_positions"]
            self.assertEqual(pos["later_listings"][0]["source"], "Upbit new markets")
            self.assertEqual(state["listings_while_held"][0]["position_entry_time"],
                             pos["entry_time"])
        # the daily comparison ignores the LISTING row
        from screener.compare import strategy_stats
        stats = strategy_stats(self.folder, 1, "2026-09-24")
        self.assertEqual((stats["buys_today"], stats["realized"], stats["open"]), (1, 0.0, 1))

    def test_the_comparison_says_from_when_slippage_applies(self):
        import io

        import compare
        self.bought()
        cfg = dict(CFG, files={"data_folder": self.tmp.name})
        with mock.patch.object(compare, "load_config", lambda: cfg), \
                mock.patch.dict(os.environ, {"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""}), \
                mock.patch("sys.argv", ["compare.py", "--date", "2026-09-24"]), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(compare.main(), 0)
        text = out.getvalue()
        self.assertRegex(text, r"\*\*Buy slippage:\*\* paper buys pay extra over the market "
                               r"price, for a person's reaction time: \+1\.5% for news \(listings\), "
                               r"news \(listings\) fast \(since \d{4}-\d\d-\d\d \d\d:\d\d UTC\)")


class CompareTests(Base):
    def test_column_next_to_news_listings(self):
        import io

        import compare
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        bot.http.http = DemoNewsHttp(now=NOW, markets={"coinbase": ["DEMO"]})
        bot.run_once(NOW + timedelta(minutes=1), **QUIET)
        cfg = dict(CFG, files={"data_folder": self.tmp.name})
        with mock.patch.object(compare, "load_config", lambda: cfg), \
                mock.patch.dict(os.environ, {"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""}), \
                mock.patch("sys.argv", ["compare.py", "--date", "2026-09-24"]), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(compare.main(), 0)
        header = next(line for line in out.getvalue().splitlines() if line.startswith("| | "))
        self.assertIn("| news (listings) | news (listings) fast |", header)


class SecretTests(unittest.TestCase):
    def test_reads_systemds_credential_first(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "claude_api_key"), "w") as fh:
                fh.write("sk-ant-test\n")
            with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": d,
                                              "CLAUDE_API_KEY": "from-env"}):
                self.assertEqual(nl.secret("claude_api_key", "CLAUDE_API_KEY"), "sk-ant-test")
            with open(os.path.join(d, "claude_api_key"), "w") as fh:
                fh.write("")                   # an empty file: no key
            with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": d}, clear=True):
                self.assertIsNone(nl.secret("claude_api_key", "CLAUDE_API_KEY"))
        with mock.patch.dict(os.environ, {"CLAUDE_API_KEY": "from-env"}, clear=True):
            self.assertEqual(nl.secret("claude_api_key", "CLAUDE_API_KEY"), "from-env")

    def test_the_ai_test_command_reads_it_too(self):
        from screener.news_ai import api_key
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "claude_api_key"), "w") as fh:
                fh.write("sk-ant-test")
            with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": d}, clear=True):
                self.assertEqual(api_key(), "sk-ant-test")


class DeployTests(unittest.TestCase):
    def read(self, *path):
        with open(os.path.join(HERE, *path)) as fh:
            return fh.read()

    def test_service(self):
        unit = self.read("deploy", "news-listings.service")
        self.assertIn("ExecStart=/home/bot/trading-bot/.venv/bin/python news_listings_bot.py",
                      unit)
        self.assertIn("LoadCredential=claude_api_key:/etc/trading-bot/claude_api_key", unit)
        self.assertNotIn("Environment=", unit)            # the key never goes in the environment
        self.assertIn("ReadWritePaths=/home/bot/trading-bot/data", unit)

    def test_pushed_hourly_and_compared(self):
        self.assertIn("data/news-listings", self.read("deploy", "push_results.sh"))
        self.assertIn('("news (listings)"', self.read("compare.py"))
        self.assertIn('fast.get("label", "news (listings) fast")', self.read("compare.py"))

    def test_restarts_on_its_own_code_only(self):
        self.assertEqual(nl.CONFIG_SECTIONS, ("news", "news_listings", "api", "files"))

    def test_only_reads(self):
        code = self.read("news_listings_bot.py")
        self.assertNotRegex(code, r"requests\.(post|put|patch|delete)")
        for word in ("private_key", "keypair", "seed phrase", "sign_transaction"):
            self.assertNotIn(word, code.lower())


if __name__ == "__main__":
    unittest.main()


class TrackTests(Base):
    """listing_track.csv: a row for every listing signal and the price 1, 5,
    15 and 60 minutes and 6 hours later. Recording only."""

    def setUp(self):
        super().setUp()
        mock.patch.object(nl, "TRACK_LISTINGS", True).start()   # undone by Base's cleanup
        # the bot stamps prices with the real clock: make it the made-up one
        self.clock = [NOW]
        for target in ("news_listings_bot.now_utc", "screener.news.now_utc"):
            mock.patch(target, lambda: self.clock[0]).start()
        self.addCleanup(mock.patch.stopall)

    def rows(self):
        import csv
        with open(os.path.join(self.folder, "listing_track.csv")) as fh:
            return list(csv.DictReader(fh))

    def run_at(self, bot, minutes, moves=None, markets=None):
        bot.http.http = DemoNewsHttp(now=NOW, markets=markets or {"coinbase": ["DEMO"]},
                                     price_moves={"demo-network": moves} if moves else None)
        self.clock[0] = NOW + timedelta(minutes=minutes, seconds=2)
        bot.run_once(NOW + timedelta(minutes=minutes), **QUIET)
        return [u for u in bot.http.http.calls if "coingecko" in u]

    def test_a_row_per_signal_with_the_detection_price(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)
        (row,) = self.rows()
        self.assertEqual((row["source"], row["coin_id"], row["symbol"], row["verdict"],
                          row["bought"]), ("Coinbase new pairs", "demo-network", "DEMO",
                                           "PASS", "yes"))
        self.assertEqual(row["detected_utc"], "2026-09-24 13:31:00")
        self.assertEqual(float(row["price_at_detection"]), 70.0)       # the market price
        self.assertEqual(row["price_time_utc"], "2026-09-24 13:31:02")
        # a market list gives no real announcement time: said so, not guessed
        self.assertEqual(row["announced_utc"], "")
        self.assertIn("not known", row["announced_basis"])
        self.assertEqual(row["delay_seconds"], "")
        self.assertEqual(row["price_1m"], "")

    def test_prices_after_1_5_15_60_minutes_and_6_hours(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)                                   # detected 13:31
        moves = {2: 1.01, 6: 1.05, 16: 1.20, 61: 0.90, 361: 0.80}
        for minute in range(2, 362):
            self.run_at(bot, minute, moves.get(minute, 1.0))
        (row,) = self.rows()
        for name, move in (("1m", 1.01), ("5m", 1.05), ("15m", 1.20), ("60m", 0.90),
                           ("6h", 0.80)):
            self.assertAlmostEqual(float(row[f"price_{name}"]), 70.0 * move, msg=name)
        self.assertEqual(row["time_1m"][11:16], "13:32")
        self.assertEqual(row["time_5m"][11:16], "13:36")
        self.assertEqual(row["time_15m"][11:16], "13:46")
        self.assertEqual(row["time_60m"][11:16], "14:31")
        self.assertEqual(row["time_6h"][11:16], "19:31")

    def test_a_signal_that_was_not_bought_is_followed_too(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)                                   # bought, so now in cooldown
        self.run_at(bot, 2, markets={"coinbase": ["DEMO"], "upbit": ["DEMO"]})
        rows = self.rows()
        self.assertEqual([(r["source"], r["verdict"], r["bought"]) for r in rows],
                         [("Coinbase new pairs", "PASS", "yes"),
                          ("Upbit new markets", "FAIL", "no")])
        self.assertTrue(rows[1]["price_at_detection"])
        for minute in range(3, 10):
            self.run_at(bot, minute, 1.1, markets={"coinbase": ["DEMO"], "upbit": ["DEMO"]})
        late = self.rows()[1]
        self.assertAlmostEqual(float(late["price_1m"]), 77.0)
        self.assertAlmostEqual(float(late["price_5m"]), 77.0)

    def test_a_missed_checkpoint_stays_blank_not_zero(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)                                   # detected 13:31
        self.run_at(bot, 30)                                  # the bot was off for 30 minutes
        row = self.rows()[0]
        for name in ("1m", "5m", "15m"):
            self.assertEqual((row[f"price_{name}"], row[f"time_{name}"]), ("", ""), name)

    def test_unmatched_listings_get_a_row_without_a_price(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1, markets={"coinbase": ["ZZZUNKNOWN"]})
        row = self.rows()[-1]
        self.assertEqual((row["coin_id"], row["price_at_detection"], row["bought"],
                          row["verdict"]), ("", "", "", ""))
        self.assertIn("no coin matched", row["note"])

    def test_the_real_announcement_time_when_the_source_gives_one(self):
        from screener.listing_track import ListingTrack
        track = ListingTrack(self.tmp.name)
        source = {"name": "Kraken blog", "kind": "exchange"}
        item = {"title": "Kraken lists X", "published": NOW - timedelta(seconds=43)}
        row = track.signal_row(NOW, source, item, [{"id": "x", "symbol": "X", "price": 2.0}],
                               True, False, NOW)
        self.assertEqual((row["announced_utc"], row["announced_basis"], row["delay_seconds"]),
                         ("2026-09-24 13:29:17", "exchange", "43"))

    def test_trading_is_identical_with_and_without_the_recording(self):
        """The same trades, prices, positions and files: only the CoinGecko
        call count differs (and listing_track.csv exists)."""
        def play(folder, on):
            with mock.patch.object(nl, "TRACK_LISTINGS", on):
                bot = nl.NewsListings(CFG, folder, DemoNewsHttp(now=NOW), None, None,
                                      DemoClaude())
                bot.run_once(NOW, **QUIET)
                for minute in range(1, 70):
                    moves = {3: 1.3, 20: 1.1, 40: 0.7}.get(minute, 1.0)
                    bot.http.http = DemoNewsHttp(
                        now=NOW, markets={"coinbase": ["DEMO"]},
                        price_moves={"demo-network": moves})
                    self.clock[0] = NOW + timedelta(minutes=minute, seconds=2)
                    bot.run_once(NOW + timedelta(minutes=minute), **QUIET)
            out = {}
            for sub in ("", "fast"):
                base = os.path.join(folder, "news-listings", sub)
                for name in ("journal.csv", "entries.csv", "candidates.csv", "positions.json"):
                    path = os.path.join(base, name)
                    if os.path.exists(path):
                        with open(path) as fh:
                            text = fh.read()
                        if name == "positions.json":
                            data = json.loads(text)
                            data.pop("coingecko", None)
                            data.pop("last_prices", None)
                            text = json.dumps(data, sort_keys=True)
                        out[(sub, name)] = text
            return out
        a, b = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(a.cleanup)
        self.addCleanup(b.cleanup)
        off, on = play(a.name, False), play(b.name, True)
        self.assertEqual(off.keys(), on.keys())
        for key in off:
            if key[1] == "positions.json":
                continue            # last_prices moves with the extra calls: compared below
            self.assertEqual(off[key], on[key], key)
        for key in off:
            if key[1] == "positions.json":
                x, y = json.loads(off[key]), json.loads(on[key])
                for field in ("open_positions", "running_total_pnl_usd", "closed_positions"):
                    self.assertEqual(x.get(field), y.get(field), (key, field))

    def test_no_extra_call_for_a_coin_the_run_already_priced(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)
        # minute 2: the 1-minute checkpoint is due AND the open position is priced
        # (first price check after the buy): one CoinGecko call serves both
        calls = self.run_at(bot, 2)
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.rows()[0]["price_1m"])

    def test_tracking_calls_stop_when_the_monthly_count_is_nearly_used(self):
        cfg = dict(CFG, news_listings=dict(CFG["news_listings"], fast={"enabled": False}))
        bot = nl.NewsListings(cfg, self.tmp.name, DemoNewsHttp(now=NOW), None, None, DemoClaude())
        bot.run_once(NOW, **QUIET)
        self.run_at(bot, 1)
        self.run_at(bot, 2)                      # the 1-minute price (and the position's)
        state = self.state()
        state["coingecko"]["calls"] = CFG["news_listings"]["coingecko_monthly_calls"] - 100
        with open(os.path.join(self.folder, "positions.json"), "w") as fh:
            json.dump(state, fh)
        bot = nl.NewsListings(cfg, self.tmp.name, DemoNewsHttp(now=NOW), None, None, DemoClaude())
        calls = self.run_at(bot, 6)              # the 5-minute price is due
        self.assertEqual(calls, [])              # 100 calls left: kept for the positions
        self.assertEqual(self.rows()[0]["price_5m"], "")
        self.assertTrue(self.rows()[0]["price_1m"])

    def test_a_failing_recording_never_stops_the_bot(self):
        bot = self.bot()
        bot.run_once(NOW, **QUIET)
        with mock.patch("news_listings_bot.ListingTrack", side_effect=RuntimeError("boom")):
            lines = []
            bot.http.http = DemoNewsHttp(now=NOW, markets={"coinbase": ["DEMO"]})
            (pos,) = bot.run_once(NOW + timedelta(minutes=1), out=lines.append)
        self.assertEqual(pos["symbol"], "DEMO")
        self.assertIn("listing track: skipped this run: boom", "\n".join(lines))
