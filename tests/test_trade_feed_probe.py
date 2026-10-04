"""Checks for the trade feed probe (trade_feed_probe.py), with a made-up
websocket and a made-up DexScreener. Run with:  python -m unittest -v
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trade_feed_probe as tp  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402

C = load_config()["trade_feed_probe"]
MINT = bytes(range(1, 33))
MINT58 = tp.b58encode(MINT)


def trade_line(mint=MINT, is_buy=True, ts=1_000, vsol=30_000_000_000, vtok=1_000_000_000_000_000):
    data = (tp.TRADE_EVENT + mint + (10**8).to_bytes(8, "little") + (10**9).to_bytes(8, "little")
            + bytes([1 if is_buy else 0]) + bytes(32) + ts.to_bytes(8, "little", signed=True)
            + vsol.to_bytes(8, "little") + vtok.to_bytes(8, "little") + bytes(40))
    return "Program data: " + base64.b64encode(data).decode()


def create_line(mint=MINT, name=b"Frog", symbol=b"FROG", uri=b"https://x"):
    data = tp.CREATE_EVENT
    for s in (name, symbol, uri):
        data += len(s).to_bytes(4, "little") + s
    return "Program data: " + base64.b64encode(data + mint + bytes(64)).decode()


def notification(logs, slot=100, err=None):
    return json.dumps({"jsonrpc": "2.0", "method": "logsNotification", "params": {
        "result": {"context": {"slot": slot}, "value": {"signature": "s", "err": err,
                                                        "logs": logs}}, "subscription": 1}})


class Clock:
    def __init__(self, now=2_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class DecodeTests(unittest.TestCase):
    def test_base58(self):
        self.assertEqual(tp.b58encode(b"hello world"), "StV1DL6CwTryKyV")
        self.assertEqual(tp.b58encode(bytes(32)), "1" * 32)

    def test_trade_and_create_events(self):
        logs = ["Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]",
                "Program log: Instruction: Buy", trade_line(), create_line(),
                "Program data: bm90IGFuIGV2ZW50", "Program data: !!!not base64"]
        trades, creates = tp.decode_events(logs)
        self.assertEqual(creates, [MINT58])
        ((mint, is_buy, ts, price),) = trades
        self.assertEqual((mint, is_buy, ts), (MINT58, True, 1_000))
        self.assertAlmostEqual(price, 30 / 1e9)               # 30 SOL / 1e9 tokens
        self.assertEqual(tp.decode_events([trade_line(is_buy=False)])[0][0][1], False)

    def test_only_a_read_only_subscription(self):
        msg = json.loads(tp.subscribe_request())
        self.assertEqual(msg["method"], "logsSubscribe")
        self.assertEqual(msg["params"][0], {"mentions": [tp.PUMP_PROGRAM]})
        for method in ("sendTransaction", "requestAirdrop", "simulateTransaction"):
            with self.assertRaises(ValueError):
                tp.subscribe_request(method)


class StatsTests(unittest.TestCase):
    def probe(self, clock):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return tp.Probe(C, 120, self.tmp.name, clock=clock, get=lambda *a, **k: None)

    def test_counts_bandwidth_gaps_delay_and_per_second(self):
        clock = Clock()
        p = self.probe(clock)
        for second in range(10):
            clock.now += 1
            for _ in range(second % 3):                   # 0, 1 or 2 trades a second
                p.handle(notification([trade_line(ts=int(clock.now) - 2)], slot=100 + second))
        clock.now += 12                                   # a 12-second silent gap
        p.handle(notification([trade_line(is_buy=False, ts=int(clock.now) - 1)], slot=200))
        p.handle(notification([trade_line()], err={"InstructionError": [0, 1]}))   # failed tx
        clock.now += 1.5
        p.stats.roll_seconds(clock.now)
        s = p.stats.summary(clock.now)
        self.assertEqual(s["trades"]["total"], 10)
        self.assertEqual((s["trades"]["buys"], s["trades"]["sells"]), (9, 1))
        self.assertEqual(s["trades"]["failed_transactions"], 1)
        self.assertEqual(s["trades"]["per_second_max"], 2)
        self.assertEqual(s["connection"]["silent_gaps"], {"10-30 s": 1})
        self.assertEqual(s["connection"]["slot_jumps_over_limit"], 1)
        self.assertEqual(s["feed_delay_seconds"]["median"], 2.0)
        self.assertGreater(s["bandwidth"]["bytes"], 11 * 300)     # every message counted
        self.assertEqual(s["bandwidth"]["messages"], 11)

    def test_the_summary_keeps_no_trade_data(self):
        clock = Clock()
        p = self.probe(clock)
        p.handle(notification([create_line(), trade_line()]))
        clock.now += 61
        p.save()
        with open(p.path) as fh:
            text = fh.read()
        self.assertNotIn(MINT58, text)                     # no token addresses
        self.assertNotIn("signature", text)
        self.assertEqual(os.listdir(self.tmp.name), ["summary.json"])

    def test_never_more_than_2_hours(self):
        self.assertEqual(self.probe(Clock()).minutes, 120)
        self.tmp.cleanup()
        p = tp.Probe(C, 500, self.tmp.name, clock=Clock())
        self.assertEqual(p.minutes, 120)
        self.assertEqual(p.left(), 7200)
        with open(os.path.join(HERE, "deploy", "trade-feed-probe.service")) as fh:
            unit = fh.read()
        self.assertIn("--minutes 120", unit)
        self.assertIn("Restart=no", unit)
        self.assertIn("RuntimeMaxSec=7500", unit)
        self.assertNotIn("[Install]", unit)                # never starts by itself


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


class DexSamplerTests(unittest.TestCase):
    def test_listing_delay_and_price_lag(self):
        stats = tp.Stats(C, Clock())
        answers = []
        sampler = tp.DexSampler(C, stats, get=lambda *a, **k: answers.pop(0))
        sampler.on_create(MINT58, 1000.0)
        answers.append(Resp([]))                              # not listed yet
        sampler.check(1010.0)
        pair = {"baseToken": {"address": MINT58}, "quoteToken": {"symbol": "SOL"},
                "priceNative": "0.0000000300"}
        answers.append(Resp([pair]))
        sampler.check(1025.0)
        self.assertEqual(stats.listing_delays, [25.0])
        sampler.on_trade(MINT58, 3.0e-8, 1030.0)             # matches DexScreener
        sampler.on_trade(MINT58, 4.0e-8, 1040.0)             # newer, not yet on DexScreener
        answers.append(Resp([pair]))
        sampler.check(1045.0)
        self.assertEqual(stats.price_lags, [15.0])           # its price is from 15 s ago
        answers.append(Resp(None, 429))
        sampler.check(1055.0)
        self.assertEqual((stats.dex_requests, stats.dex_errors), (4, 1))

    def test_one_launch_a_minute_and_a_limit(self):
        stats = tp.Stats(C, Clock())
        sampler = tp.DexSampler(C, stats, get=lambda *a, **k: Resp([]))
        sampler.on_create("A", 0.0)
        sampler.on_create("B", 30.0)                          # too soon after A
        sampler.on_create("C", 61.0)
        self.assertEqual(sorted(sampler.waiting), ["A", "C"])
        sampler.check(650.0)                                  # A waited over 600 s
        self.assertEqual(stats.never_listed, 1)
        self.assertEqual(list(sampler.waiting), ["C"])


class FakeWs:
    def __init__(self, messages, then=None):
        self.messages, self.then, self.sent = list(messages), then, []
        self.response = type("R", (), {"headers": {"Sec-WebSocket-Extensions":
                                                   "permessage-deflate"}})()

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


class RunTests(unittest.TestCase):
    def test_reconnects_and_stops_by_itself(self):
        connections = []

        def connect(url, **kw):
            ws = FakeWs([notification([trade_line()])] * 3,
                        then=OSError("connection reset") if not connections else None)
            connections.append(ws)
            return ws

        with tempfile.TemporaryDirectory() as d:
            p = tp.Probe(C, 120, d, connect=connect, get=lambda *a, **k: Resp([]))
            p.deadline = time.time() + 4                      # a short run
            started = time.time()
            with self.assertLogs("trade_feed_probe", "INFO") as logs:
                summary = asyncio.run(p.main())
            took = time.time() - started
            with open(os.path.join(d, "summary.json")) as fh:
                saved = json.load(fh)
        self.assertLess(took, 12)                             # stopped by itself
        self.assertTrue(saved["finished"])
        self.assertEqual(len(connections), 2)
        self.assertEqual(connections[0].sent[0]["method"], "logsSubscribe")
        self.assertEqual(summary["trades"]["total"], 6)
        self.assertEqual(summary["connection"]["disconnects"], 1)
        self.assertEqual(summary["connection"]["recent_disconnects"][0]["reason"],
                         "connection reset")
        self.assertTrue(summary["bandwidth"]["compression_negotiated"])
        self.assertIn("feed disconnected", "\n".join(logs.output))
        self.assertIn("trades:", tp.report(summary))


if __name__ == "__main__":
    unittest.main()
