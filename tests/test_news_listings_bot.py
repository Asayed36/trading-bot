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
from screener.news import NewsStrategy  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402

CFG = running(load_config())
NOW = datetime(2026, 9, 24, 13, 30, tzinfo=timezone.utc)
SERVER = ["Binance listings", "Kraken blog", "Coinbase new pairs", "Upbit new markets",
          "OKX new markets"]
QUIET = dict(out=lambda *a: None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "news-listings")

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
        for key in ("paper_trading", "max_age_minutes", "min_market_cap_usd", "min_volume_usd",
                    "max_change_1h_pct", "max_change_24h_pct", "cooldown_days", "catalyst_words",
                    "exchange_words", "hype_words", "bad_news_words", "institutions",
                    "unambiguous_names", "crypto_words"):
            self.assertEqual(c[key], news[key], key)
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
        bot = self.bot()
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

    def test_restarts_on_its_own_code_only(self):
        self.assertEqual(nl.CONFIG_SECTIONS, ("news", "news_listings", "api", "files"))

    def test_only_reads(self):
        code = self.read("news_listings_bot.py")
        self.assertNotRegex(code, r"requests\.(post|put|patch|delete)")
        for word in ("private_key", "keypair", "seed phrase", "sign_transaction"):
            self.assertNotIn(word, code.lower())


if __name__ == "__main__":
    unittest.main()
