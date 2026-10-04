"""Checks for the "momentum" paper strategy (screener/momentum.py,
screener/pumpfeed.py, momentum_bot.py), with made-up pump.fun events.
Run with:  python -m unittest -v
"""

import asyncio
import base64
import csv
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compare  # noqa: E402
import momentum_bot  # noqa: E402
from screener import pumpfeed as pf  # noqa: E402
from screener.momentum import MomentumEngine, window_metrics  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402

CFG = load_config()
M = CFG["momentum"]
# The real feed sends ~44 messages a second, so a 10 s silence means it's
# down. These tests send few events, so the feed's own tests use the real
# limit and the others a very long one.
QUIET = dict(CFG, momentum=dict(M, feed_stale_seconds=10**6))
T0 = 1_800_000_000.0
SOL_USD = 200.0
BASE = 3e-8                                   # SOL per token at the start


def key(n):
    return bytes([n % 256]) * 31 + bytes([n // 256 + 1])


MINT, CREATOR = key(1), key(2)
MINT58, CREATOR58 = pf.b58encode(MINT), pf.b58encode(CREATOR)


def data_line(raw):
    return "Program data: " + base64.b64encode(raw).decode()


def trade(price, wallet, is_buy=True, sol=1.0, mint=MINT, progress=10.0):
    vtok = 10**15
    real = int(pf.CURVE_TOKENS * (1 - progress / 100))
    raw = (pf.TRADE_EVENT + mint + int(sol * 1e9).to_bytes(8, "little")
           + (10**9).to_bytes(8, "little") + bytes([1 if is_buy else 0]) + wallet
           + (1).to_bytes(8, "little")
           + int(price * 1e18).to_bytes(8, "little") + vtok.to_bytes(8, "little")
           + (0).to_bytes(8, "little") + real.to_bytes(8, "little") + bytes(64))
    return data_line(raw)


def create(mint=MINT, creator=CREATOR, name="Frog", symbol="FROG"):
    raw = pf.CREATE_EVENT
    for text in (name, symbol, "https://x"):
        raw += len(text.encode()).to_bytes(4, "little") + text.encode()
    return data_line(raw + mint + bytes(32) + creator + bytes(40))


def complete(mint=MINT):
    return data_line(pf.COMPLETE_EVENT + bytes(32) + mint + bytes(40))


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.e = self.engine()

    def tearDown(self):
        self.tmp.cleanup()

    def engine(self, cfg=QUIET):
        e = MomentumEngine(cfg, self.d, clock=lambda: T0)
        e.set_sol_price(SOL_USD)
        e.connected(T0 - 1000)
        return e

    def feed(self, t, *lines, e=None):
        (e or self.e).on_logs(list(lines), False, t)

    def launch(self, t=T0, e=None, **kw):
        self.feed(t, create(**kw), e=e)

    def pump(self, start, rise, seconds=60, n=20, mint=MINT, wallets=None, e=None):
        """n buys from different wallets over `seconds` at BASE, the last one
        lifting the price by `rise` (0.5 = +50%): the signal (if any) comes
        at the last trade, at start + seconds."""
        for i in range(n):
            price = BASE * (1 + rise) if i == n - 1 else BASE
            wallet = (wallets or [key(100 + j) for j in range(n)])[i]
            self.feed(start + (i + 1) * seconds / n, trade(price, wallet, mint=mint), e=e)
        return start + seconds

    def path(self, *parts):
        return os.path.join(self.d, "momentum", *parts)

    def buys(self, variant):
        return [r for r in rows(self.path(variant, "journal.csv")) if r["action"] == "BUY"]


class DecodeTests(unittest.TestCase):
    def test_events(self):
        events = pf.decode(["Program log: Instruction: Buy", create(),
                            trade(BASE, key(9), is_buy=False, sol=2.5, progress=42),
                            complete(), "Program data: bm9wZQ=="])
        c, tr, done = events
        self.assertEqual((c["kind"], c["mint"], c["creator"], c["symbol"], c["name"]),
                         ("create", MINT58, CREATOR58, "FROG", "Frog"))
        self.assertEqual((tr["kind"], tr["mint"], tr["is_buy"], tr["sol"], tr["user"]),
                         ("trade", MINT58, False, 2.5, pf.b58encode(key(9))))
        self.assertAlmostEqual(tr["price_sol"], BASE)
        self.assertAlmostEqual(tr["progress_pct"], 42, places=1)
        self.assertEqual((done["kind"], done["mint"]), ("complete", MINT58))

    def test_only_a_read_only_subscription(self):
        self.assertEqual(json.loads(pf.subscribe_request())["method"], "logsSubscribe")
        with self.assertRaises(ValueError):
            pf.subscribe_request("sendTransaction")

    def test_window_metrics(self):
        trades = [(0, 1.0, True, 2.0, "a"), (10, 1.2, True, 1.0, "b"), (20, 0.9, False, 0.5, "c"),
                  (30, 1.5, True, 1.0, "a")]
        m = window_metrics(trades, 30, 60)
        self.assertEqual((m["buys"], m["sells"], m["unique_buyers"]), (3, 1, 2))
        self.assertEqual((m["rise_pct"], m["net_sol"], m["top_wallet_buy_pct"]), (66.7, 3.5, 75.0))
        self.assertEqual(window_metrics(trades, 30, 15)["buys"], 1)   # only the last 15 s


class SignalTests(Base):
    def test_signal_fills_at_the_first_trade_5_seconds_later(self):
        self.launch()
        end = self.pump(T0 + 60, 0.4)                     # +40% over a minute
        self.assertEqual(self.buys("30pct-2min"), [])     # not yet: waiting for the fill
        self.e.set_jupiter(MINT58, {"jupiter_organic_score": 12.5,
                                    "jupiter_organic_label": "low"}, end)
        self.feed(end + 2, trade(BASE * 1.41, key(300)))  # too soon after the signal
        self.assertEqual(self.buys("30pct-2min"), [])
        self.feed(end + 6, trade(BASE * 1.45, key(301)))  # the fill
        (buy,) = self.buys("30pct-2min")
        self.assertIn("momentum +", buy["reason"])
        self.assertAlmostEqual(float(buy["price_usd"]) / (BASE * 1.45 * SOL_USD), 1, places=6)
        (entry,) = rows(self.path("30pct-2min", "entries.csv"))
        self.assertEqual(entry["variant"], "30pct-2min")
        self.assertEqual(entry["jupiter_organic_score"], "12.5")
        self.assertGreaterEqual(float(entry["seconds_after_signal"]), 5)
        self.assertEqual(entry["unique_buyers"], "20")
        # +40% isn't enough for the other two variants.
        self.assertEqual(self.buys("50pct-3min") + self.buys("100pct-5min"), [])

    def test_launch_bot_costs(self):
        self.launch()
        end = self.pump(T0 + 60, 0.4)
        self.feed(end + 6, trade(BASE * 1.4, key(301)))
        pos = self.e.traders["30pct-2min"].position(MINT58)
        lp = CFG["launch"]["paper_trading"]
        slow = next(s for s in CFG["launch"]["speeds"] if s["name"] == M["costs_like_speed"])
        self.assertEqual(pos["cost_usd"], lp["buy_amount_usd"] + slow["priority_fee_sol"] * SOL_USD)
        kept = (1 - (lp["bot_fee_pct"] + lp["platform_fee_pct"]) / 100) * \
            (1 - slow["extra_slippage_pct"] / 100)
        self.assertAlmostEqual(pos["tokens"] / (5 * kept / (BASE * 1.4 * SOL_USD)), 1, places=6)

    def failed(self, variant="30pct-2min"):
        return [r["failed"] for r in rows(self.path("near_misses.csv")) if r["variant"] == variant]

    def test_each_rule(self):
        cases = {
            "buys": dict(n=10),
            "unique buyers": dict(wallets=[key(100 + i % 8) for i in range(20)]),
            "one wallet's share": dict(wallets=[key(100)] * 7 + [key(101 + i) for i in range(13)]),
        }
        for rule, kw in cases.items():
            with self.subTest(rule):
                self.setUp()
                self.launch()
                self.pump(T0 + 60, 0.4, **kw)
                self.assertEqual(self.buys("30pct-2min"), [])
                self.assertIn(rule, self.failed()[0])

    def test_buys_vs_sells_and_net_sol(self):
        self.launch()
        t = self.pump(T0 + 60, 0.2, n=16)
        for i in range(12):                              # 16 buys vs 12 sells
            self.feed(t + i, trade(BASE, key(400 + i), is_buy=False, sol=0.2))
        self.feed(t + 13, trade(BASE * 1.6, key(500)))
        self.assertEqual(self.buys("30pct-2min"), [])
        self.assertIn("buys vs sells", self.failed()[0])

    def test_creator_sold(self):
        self.launch()
        self.feed(T0 + 30, trade(BASE, CREATOR, is_buy=False, sol=0.1))
        self.pump(T0 + 60, 0.4)
        self.assertEqual(self.buys("30pct-2min"), [])
        self.assertIn("creator sold", self.failed()[0])

    def test_age_window(self):
        self.launch()
        self.pump(T0 + 1, 0.4, seconds=50)               # all under a minute old
        self.assertEqual(self.failed(), [])               # not even evaluated
        self.setUp()
        self.launch()
        self.pump(T0 + 600, 0.4)                          # over 10 minutes old
        self.assertEqual(self.buys("30pct-2min"), [])

    def test_curve_progress_and_graduation(self):
        self.launch()
        for i in range(20):
            price = BASE * (1 + 0.02 * (i + 1))
            self.feed(T0 + 60 + i * 3, trade(price, key(100 + i), progress=85))
        self.assertIn("on the curve", self.failed()[0])
        self.setUp()
        self.launch()
        self.feed(T0 + 50, complete())
        self.pump(T0 + 60, 0.4)
        self.assertIn("on the curve", self.failed()[0])

    def test_copycat_and_dead_creator(self):
        other = key(50)
        self.launch(T0 - 86400, mint=other, name="Frog", symbol="FRG")
        self.launch()
        self.pump(T0 + 60, 0.4)
        self.assertIn("copycat name", self.failed()[0])
        self.setUp()
        self.launch(T0 - 7200, mint=other, name="Toad", symbol="TOAD")   # never graduated
        self.launch()
        self.pump(T0 + 60, 0.4)
        self.assertIn("creator has a dead token", self.failed()[0])

    def test_no_buys_while_the_feed_is_down_or_was_down_in_the_window(self):
        self.e = self.engine(CFG)
        self.launch()
        for s in range(0, 30, 5):
            self.feed(T0 + s)                             # the feed's steady messages
        self.feed(T0 + 30, trade(BASE, key(99)))
        self.e.disconnected(T0 + 40)
        self.e.connected(T0 + 55)                         # back, but the window has a hole
        self.pump(T0 + 60, 0.4)
        self.assertEqual(self.buys("30pct-2min"), [])
        self.assertIn("feed was down in the window", self.failed()[0])
        # A signal whose fill comes after the feed went quiet: no buy.
        self.setUp()
        self.launch()
        end = self.pump(T0 + 60, 0.4)
        self.e.c = dict(self.e.c, feed_stale_seconds=10)   # the real limit from here on
        self.feed(end + 20, trade(BASE * 1.4, key(301)))  # after 20 s with nothing
        self.assertEqual(self.buys("30pct-2min"), [])

    def test_hourly_cap_and_max_open(self):
        cfg = dict(QUIET, momentum=dict(QUIET["momentum"], max_buys_per_hour=2))
        e = self.engine(cfg)
        for n in range(3):
            mint = key(10 + n)
            self.launch(T0 + n * 100, e=e, mint=mint, name=f"T{n}", symbol=f"T{n}",
                        creator=key(30 + n))
            end = self.pump(T0 + n * 100 + 60, 0.4, mint=mint, e=e)
            self.feed(end + 6, trade(BASE * 1.4, key(301), mint=mint), e=e)
        self.assertEqual(len(self.buys("30pct-2min")), 2)
        self.assertIn("hourly cap", self.failed()[0])

    def test_near_misses_once_per_launch_and_variant(self):
        self.launch()
        self.pump(T0 + 60, 0.25)                         # +25%: close to +30%
        rows_ = rows(self.path("near_misses.csv"))
        self.assertEqual([r["variant"] for r in rows_], ["30pct-2min"])
        self.assertEqual(rows_[0]["failed"], "rise")
        self.pump(T0 + 100, 0.26)
        self.assertEqual(len(rows(self.path("near_misses.csv"))), 1)


class ExitTests(Base):
    def bought(self):
        self.launch()
        end = self.pump(T0 + 60, 0.4)
        self.feed(end + 6, trade(BASE * 1.4, key(301)))
        return end + 6

    def test_take_profit_at_2x_and_stop_loss(self):
        t = self.bought()
        self.feed(t + 10, trade(BASE * 2.9, key(302)))   # more than 2x the entry
        self.feed(t + 20, trade(BASE * 0.9, key(303), is_buy=False))   # -36% from entry
        sells = [r for r in rows(self.path("30pct-2min", "journal.csv")) if r["action"] == "SELL"]
        self.assertIn("take profit", sells[0]["reason"])
        self.assertIn("stop loss", sells[1]["reason"])
        self.assertIsNone(self.e.traders["30pct-2min"].position(MINT58))

    def test_time_stop_with_dexscreener_after_the_trades_stop(self):
        t = self.bought()
        self.assertEqual(self.e.needs_external(t + 30), [])
        self.assertEqual(self.e.needs_external(t + 61), [MINT58])     # no trade for 60 s
        self.e.set_external_prices({MINT58: BASE * 1.4 * SOL_USD}, t + 62)
        self.e.tick(t + 31 * 60)
        sells = [r for r in rows(self.path("30pct-2min", "journal.csv")) if r["action"] == "SELL"]
        self.assertIn("time stop", sells[0]["reason"])

    def test_positions_survive_a_restart(self):
        self.bought()
        self.e.save()
        e = self.engine()
        self.assertIn(MINT58, e.launches)
        self.assertEqual(e.needs_external(T0 + 999), [MINT58])        # priced from DexScreener


class FakeWs:
    def __init__(self, messages, then=None):
        self.messages, self.then, self.sent = list(messages), then, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        if self.messages:
            await asyncio.sleep(0)
            return self.messages.pop(0)
        if self.then:
            raise self.then
        await asyncio.sleep(3600)


class Api:
    def pairs_for_tokens(self, mints):
        return [{"baseToken": {"address": "So11111111111111111111111111111111111111112"},
                 "quoteToken": {"symbol": "USDC"}, "priceUsd": "200", "liquidity": {"usd": 1e6}}]


class RunnerTests(unittest.TestCase):
    def test_reads_the_feed_reconnects_and_saves_health(self):
        note = json.dumps({"jsonrpc": "2.0", "method": "logsNotification", "params": {
            "result": {"context": {"slot": 1}, "value": {"err": None, "logs": [create()]}}}})
        conns = []

        def connect(url, **kw):
            conns.append(FakeWs([note], then=OSError("reset") if not conns else None))
            return conns[-1]

        with tempfile.TemporaryDirectory() as d:
            r = momentum_bot.Runner(CFG, d, connect=connect, api=Api(), jupiter=False)
            with self.assertLogs("momentum_bot", "INFO") as logs:
                asyncio.run(asyncio.wait_for(r.main(stop_after=3), 10))
            with open(os.path.join(d, "momentum", "health.json")) as fh:
                health = json.load(fh)
        self.assertEqual(conns[0].sent[0]["method"], "logsSubscribe")
        self.assertGreaterEqual(len(conns), 2)
        self.assertIn("feed disconnected", "\n".join(logs.output))
        self.assertIn("last_ok", health)
        self.assertEqual(r.engine.sol_usd, 200.0)

    def test_restarts_itself_on_new_code(self):
        class Watcher:
            files = []

            def changed(self):
                return ["screener/momentum.py"]

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(momentum_bot, "CODE_CHECK_SECONDS", 0.01):
            r = momentum_bot.Runner(CFG, d, watcher=Watcher(),
                                    connect=lambda url, **kw: FakeWs([]), api=Api(),
                                    jupiter=False)
            started = time.time()
            with self.assertLogs("momentum_bot", "INFO") as logs:
                asyncio.run(asyncio.wait_for(r.main(), 10))
        self.assertLess(time.time() - started, 5)
        text = "\n".join(logs.output)
        self.assertIn("automatic restart: new code from the hourly push in screener/momentum.py",
                      text)
        self.assertIn("stopped; everything saved; systemd starts the new code", text)


class DeployTests(unittest.TestCase):
    def test_service_push_and_comparison(self):
        with open(os.path.join(HERE, "deploy", "momentum-bot.service")) as fh:
            unit = fh.read()
        for text in ("Restart=always", "User=bot", "momentum_bot.py", "ReadWritePaths="):
            self.assertIn(text, unit)
        with open(os.path.join(HERE, "deploy", "push_results.sh")) as fh:
            self.assertIn("data/momentum", fh.read())
        with tempfile.TemporaryDirectory() as d:
            cfg = dict(CFG, files={"data_folder": d})
            with mock.patch.object(compare, "load_config", lambda: cfg), \
                    mock.patch.dict(os.environ, {"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""}), \
                    mock.patch("sys.argv", ["compare.py", "--date", "2026-10-04"]), \
                    mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
                compare.main()
        header = next(line for line in out.getvalue().splitlines() if line.startswith("| | main"))
        for v in M["variants"]:
            self.assertIn(f"momentum {v['name']}", header)
        self.assertIn("| momentum: server |", out.getvalue())


if __name__ == "__main__":
    unittest.main()
