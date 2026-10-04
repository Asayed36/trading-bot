"""Measures the free Solana public RPC as a live feed of pump.fun trades.

    python trade_feed_probe.py              <- measure for 2 hours (the most allowed)
    python trade_feed_probe.py --minutes 5  <- a short try

Research only, for the planned "momentum on launches" strategy: it doesn't
trade, and it keeps no trade data. It only counts, in memory, and writes a
summary of the numbers to data/trade-feed-probe/summary.json (every 5
minutes, and at the end). It stops by itself after --minutes (120 at most).

What it measures:
  - trades per second (pump.fun bonding-curve trades, from the program's
    TradeEvent in each transaction's logs) and notifications per second;
  - bandwidth: the bytes of every message received (uncompressed, which is
    also what Helius would bill at 20 credits per MB);
  - disconnects (and how long each one lasted), and silent gaps: no message
    for silent_gap_seconds or more while connected; after watchdog_seconds
    of silence it reconnects (counted too);
  - feed delay: when a trade arrived here minus its on-chain time;
  - DexScreener: how long after a launch (seen here) DexScreener lists it,
    and how far behind DexScreener's price is (it is matched with the
    price after each recent trade of that token, which is kept in memory for
    a few sampled tokens only);
  - its own load: CPU time and memory.

READ-ONLY. The only thing it ever asks the RPC for is "logsSubscribe" (a
read-only subscription to public logs), and DexScreener's public token API.
No wallet, no keys, nothing is signed or sent.
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import resource
import signal
import sys
import time
from collections import Counter, deque
from datetime import datetime, timezone

import requests
import websockets

from screener.settings import HERE, load_config

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
# Anchor event discriminators: sha256("event:<Name>")[:8].
TRADE_EVENT = bytes.fromhex("bddb7fd34ee661ee")
CREATE_EVENT = bytes.fromhex("1b72a94ddeeb6376")
ALLOWED_METHODS = {"logsSubscribe"}
MAX_MINUTES = 120
DEXSCREENER = "https://api.dexscreener.com/tokens/v1/solana/"
HEADERS = {"User-Agent": "memecoin-screener/1.0 (read-only research)"}
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

log = logging.getLogger("trade_feed_probe")


def subscribe_request(method="logsSubscribe", request_id=1):
    """The one subscription message, refusing anything that isn't read-only."""
    if method not in ALLOWED_METHODS:
        raise ValueError(f"{method} is not an allowed read-only request")
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                       "params": [{"mentions": [PUMP_PROGRAM]}, {"commitment": "confirmed"}]})


def b58encode(raw):
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def decode_events(logs):
    """(trades, creates) from one transaction's log lines. A trade is
    (mint, is_buy, on-chain unix time, price in SOL per token); a create
    is a mint."""
    trades, creates = [], []
    for line in logs or []:
        if not line.startswith("Program data: "):
            continue
        try:
            data = base64.b64decode(line[14:], validate=False)
        except ValueError:
            continue
        if data[:8] == TRADE_EVENT and len(data) >= 113:
            mint = b58encode(data[8:40])
            is_buy = data[56] == 1
            ts = int.from_bytes(data[89:97], "little", signed=True)
            vsol = int.from_bytes(data[97:105], "little")
            vtok = int.from_bytes(data[105:113], "little")
            price = (vsol / 1e9) / (vtok / 1e6) if vtok else None
            trades.append((mint, is_buy, ts, price))
        elif data[:8] == CREATE_EVENT:
            # name, symbol, uri (u32 length + bytes each), then the mint.
            pos = 8
            try:
                for _ in range(3):
                    pos += 4 + int.from_bytes(data[pos:pos + 4], "little")
                if len(data) >= pos + 32:
                    creates.append(b58encode(data[pos:pos + 32]))
            except (IndexError, ValueError):
                pass
    return trades, creates


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def _round(value, digits=1):
    return None if value is None else round(value, digits)


class Stats:
    """Counts only: nothing per trade is kept beyond the current second."""

    def __init__(self, cfg, clock=time.time):
        self.c, self.clock = cfg, clock
        self.started = clock()
        self.messages = self.notifications = self.trades = self.buys = self.creates = 0
        self.failed_txs = 0
        self.bytes = 0
        self.per_second = Counter()          # unix second -> trades (the current second)
        self.second_counts = []              # trades in each finished second
        self._next = int(self.started) + 1   # the next second to finish
        self.busiest_minute = 0
        self.minute = (None, 0)
        self.delays = deque(maxlen=20_000)   # receive time - on-chain time, seconds
        self.disconnects = []                # {"at", "reason", "down_seconds"}
        self.gaps = Counter()                # silent gaps by length bucket
        self.longest_gap = 0.0
        self.watchdog_reconnects = 0
        self.slot_jumps = 0
        self.last_slot = None
        self.compression = None
        self.listing_delays = []             # seconds from launch until DexScreener lists it
        self.never_listed = 0
        self.price_lags = []                 # seconds DexScreener's price is behind
        self.price_unmatched = 0
        self.dex_requests = self.dex_errors = 0

    def on_message(self, raw, now):
        self.messages += 1
        self.bytes += len(raw.encode() if isinstance(raw, str) else raw)

    def on_notification(self, slot, trades, creates, failed, now):
        self.notifications += 1
        if failed:
            self.failed_txs += 1
            return
        if slot is not None:
            if self.last_slot is not None and slot - self.last_slot > self.c["slot_jump"]:
                self.slot_jumps += 1
            self.last_slot = max(slot, self.last_slot or 0)
        sec = int(now)
        for _, is_buy, ts, _ in trades:
            self.trades += 1
            self.buys += is_buy
            self.per_second[sec] += 1
            if ts > 0:
                self.delays.append(now - ts)
        self.creates += len(creates)
        minute = sec // 60
        if self.minute[0] != minute:
            self.minute = (minute, 0)
        self.minute = (minute, self.minute[1] + len(trades))
        self.busiest_minute = max(self.busiest_minute, self.minute[1])

    def roll_seconds(self, now):
        """Move finished seconds into the per-second list (zeros included)."""
        current = int(now)
        while self._next < current:
            self.second_counts.append(self.per_second.pop(self._next, 0))
            self._next += 1
        for sec in [s for s in self.per_second if s < self._next]:
            self.per_second.pop(sec)

    def on_gap(self, seconds):
        self.longest_gap = max(self.longest_gap, seconds)
        for limit, name in ((10, "5-10 s"), (30, "10-30 s"), (60, "30-60 s")):
            if seconds < limit:
                self.gaps[name] += 1
                return
        self.gaps["60 s or more"] += 1

    def summary(self, now, finished=False):
        hours = max((now - self.started) / 3600, 1e-9)
        mb = self.bytes / 1e6
        down = sum(d.get("down_seconds", 0) for d in self.disconnects)
        delays = list(self.delays)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return {
            "finished": finished,
            "started_utc": datetime.fromtimestamp(self.started, timezone.utc).isoformat(),
            "updated_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "minutes_measured": round((now - self.started) / 60, 1),
            "feed": self.c["ws_url"],
            "trades": {
                "total": self.trades, "buys": self.buys, "sells": self.trades - self.buys,
                "per_second_average": round(self.trades / (hours * 3600), 2),
                "per_second_median": percentile(self.second_counts, 50),
                "per_second_p95": percentile(self.second_counts, 95),
                "per_second_max": max(self.second_counts, default=None),
                "busiest_minute": self.busiest_minute,
                "launches_seen": self.creates,
                "notifications": self.notifications,
                "failed_transactions": self.failed_txs,
            },
            "bandwidth": {
                "messages": self.messages,
                "bytes": self.bytes,
                "megabytes": round(mb, 2),
                "megabytes_per_hour": round(mb / hours, 1),
                "gigabytes_per_day_projected": round(mb / hours * 24 / 1000, 2),
                "average_message_bytes": round(self.bytes / self.messages) if self.messages
                else None,
                "helius_credits_per_month_projected": round(mb / hours * 24 * 30 * 20),
                "compression_negotiated": self.compression,
            },
            "connection": {
                "disconnects": len(self.disconnects),
                "watchdog_reconnects": self.watchdog_reconnects,
                "seconds_disconnected": round(down, 1),
                "recent_disconnects": self.disconnects[-10:],
                "silent_gaps": dict(self.gaps),
                "longest_silent_gap_seconds": round(self.longest_gap, 1),
                "slot_jumps_over_limit": self.slot_jumps,
            },
            "feed_delay_seconds": {
                "median": _round(percentile(delays, 50)), "p95": _round(percentile(delays, 95)),
                "max": _round(max(delays, default=None)), "samples": len(delays),
                "note": "receive time minus on-chain time (whole seconds on chain)",
            },
            "dexscreener": {
                "launches_sampled": len(self.listing_delays) + self.never_listed,
                "listing_delay_seconds_median": percentile(self.listing_delays, 50),
                "listing_delay_seconds_p95": percentile(self.listing_delays, 95),
                "not_listed_within_limit": self.never_listed,
                "price_lag_seconds_median": percentile(self.price_lags, 50),
                "price_lag_seconds_p95": percentile(self.price_lags, 95),
                "price_checks": len(self.price_lags), "price_unmatched": self.price_unmatched,
                "requests": self.dex_requests, "errors": self.dex_errors,
            },
            "own_load": {
                "cpu_seconds": round(usage.ru_utime + usage.ru_stime, 1),
                "cpu_percent_of_one_core": round(100 * (usage.ru_utime + usage.ru_stime)
                                                 / max(now - self.started, 1e-9), 1),
                "max_memory_mb": round(usage.ru_maxrss / 1024, 1),
            },
        }


class DexSampler:
    """A few launches seen on the feed, checked on DexScreener every
    check_seconds: when they're first listed, and how far behind its price is
    (against the prices after this token's trades, kept for these tokens only)."""

    def __init__(self, cfg, stats, get=requests.get):
        self.c, self.stats, self.get = cfg, stats, get
        self.waiting = {}         # mint -> time seen (not listed yet)
        self.listed = {}          # mint -> time listed (for price checks)
        self.prices = {}          # mint -> deque of (receive time, price in SOL)
        self.last_sample = float("-inf")

    def on_create(self, mint, now):
        if (now - self.last_sample >= self.c["sample_every_seconds"]
                and len(self.waiting) < self.c["max_sampled"]):
            self.waiting[mint] = now
            self.prices[mint] = deque(maxlen=500)
            self.last_sample = now

    def on_trade(self, mint, price, now):
        if mint in self.prices and price:
            self.prices[mint].append((now, price))

    def check(self, now):
        """One DexScreener request for every sampled token (at most 30)."""
        mints = list(self.waiting) + list(self.listed)
        mints = mints[:30]
        if not mints:
            return
        self.stats.dex_requests += 1
        try:
            resp = self.get(DEXSCREENER + ",".join(mints), headers=HEADERS, timeout=15)
            pairs = resp.json() if resp.status_code == 200 else None
        except (requests.RequestException, ValueError):
            pairs = None
        if not isinstance(pairs, list):
            self.stats.dex_errors += 1
            return
        found = {}               # mint -> its pair quoted in SOL (the bonding curve)
        for p in pairs:
            mint = (p.get("baseToken") or {}).get("address")
            if mint in self.prices and (p.get("quoteToken") or {}).get("symbol") in ("SOL",
                                                                                   "WSOL"):
                found.setdefault(mint, p)
        for mint, seen in list(self.waiting.items()):
            if mint in found:
                self.stats.listing_delays.append(round(now - seen, 1))
                self.listed[mint] = now
                del self.waiting[mint]
            elif now - seen > self.c["listing_limit_seconds"]:
                self.stats.never_listed += 1
                del self.waiting[mint]
                self.prices.pop(mint, None)
        for mint, since in list(self.listed.items()):
            pair = found.get(mint)
            try:
                dex_price = float(pair["priceNative"]) if pair else None
            except (TypeError, KeyError, ValueError):
                dex_price = None
            history = self.prices.get(mint) or ()
            if dex_price and history:
                lag = self.price_lag(history, dex_price, now)
                if lag is None:
                    self.stats.price_unmatched += 1
                else:
                    self.stats.price_lags.append(lag)
            if now - since > self.c["price_follow_seconds"]:
                del self.listed[mint]
                self.prices.pop(mint, None)

    def price_lag(self, history, dex_price, now):
        """Seconds since the trade whose price matches DexScreener's (within
        price_match_pct), newest first; None if none matches."""
        tolerance = self.c["price_match_pct"] / 100
        for at, price in reversed(history):
            if abs(price - dex_price) <= tolerance * price:
                return round(now - at, 1)
        return None


class Probe:
    def __init__(self, cfg, minutes, out_folder, clock=time.time, connect=websockets.connect,
                 get=requests.get):
        self.c = cfg
        self.minutes = min(max(float(minutes), 0.1), MAX_MINUTES)
        self.deadline = clock() + self.minutes * 60
        self.clock, self.connect = clock, connect
        self.stats = Stats(cfg, clock)
        self.dex = DexSampler(cfg, self.stats, get)
        self.path = os.path.join(out_folder, "summary.json")
        self.last_message = clock()
        self.stop = asyncio.Event()

    def left(self):
        return self.deadline - self.clock()

    def save(self, finished=False):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.stats.summary(self.clock(), finished), fh, indent=2)
        os.replace(tmp, self.path)

    def handle(self, raw):
        now = self.clock()
        if self.last_message and now - self.last_message >= self.c["silent_gap_seconds"]:
            self.stats.on_gap(now - self.last_message)
        self.last_message = now
        self.stats.on_message(raw, now)
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("method") != "logsNotification":
            if "error" in msg:
                log.warning("RPC says: %s", str(msg["error"])[:200])
            return
        result = (msg.get("params") or {}).get("result") or {}
        value = result.get("value") or {}
        trades, creates = decode_events(value.get("logs"))
        slot = (result.get("context") or {}).get("slot")
        self.stats.on_notification(slot, trades, creates, value.get("err") is not None, now)
        for mint in creates:
            self.dex.on_create(mint, now)
        for mint, _, _, price in trades:
            self.dex.on_trade(mint, price, now)

    async def feed(self):
        pause = 2
        while not self.stop.is_set():
            down_since = None
            try:
                async with self.connect(self.c["ws_url"], ping_interval=20, ping_timeout=20,
                                        max_size=2**22, open_timeout=20) as ws:
                    response = getattr(ws, "response", None)
                    headers = getattr(response, "headers", None) or {}
                    self.stats.compression = "permessage-deflate" in str(
                        headers.get("Sec-WebSocket-Extensions", ""))
                    await ws.send(subscribe_request())
                    log.info("connected to %s; subscribed to pump.fun's logs", self.c["ws_url"])
                    pause = 2
                    self.last_message = self.clock()
                    while not self.stop.is_set():
                        try:
                            raw = await asyncio.wait_for(
                                ws.recv(), min(self.c["watchdog_seconds"], max(self.left(), 0.1)))
                        except asyncio.TimeoutError:
                            if self.left() <= 0:
                                break
                            self.stats.watchdog_reconnects += 1
                            log.warning("no message for %ss: reconnecting",
                                        self.c["watchdog_seconds"])
                            self.stats.on_gap(self.clock() - self.last_message)
                            raise ConnectionError("silent")
                        self.handle(raw)
            except (OSError, ConnectionError, asyncio.TimeoutError,
                    websockets.WebSocketException) as exc:
                if self.stop.is_set():
                    break
                down_since = self.clock()
                log.warning("feed disconnected (%s); retrying in %ss", str(exc)[:120], pause)
                self.stats.disconnects.append({
                    "at": datetime.fromtimestamp(down_since, timezone.utc).strftime("%H:%M:%S"),
                    "reason": str(exc)[:120] or type(exc).__name__})
            if self.stop.is_set() or self.left() <= 0:
                break
            try:
                await asyncio.wait_for(self.stop.wait(), pause)
            except asyncio.TimeoutError:
                pass
            pause = min(pause * 2, 30)
            if down_since is not None and self.stats.disconnects:
                self.stats.disconnects[-1]["down_seconds"] = round(self.clock() - down_since, 1)

    async def clock_loop(self):
        last_dex = last_save = last_status = self.clock()
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), 1)
                return
            except asyncio.TimeoutError:
                pass
            now = self.clock()
            self.stats.roll_seconds(now)
            if now - last_dex >= self.c["check_seconds"]:
                await asyncio.to_thread(self.dex.check, now)
                last_dex = now
            if now - last_save >= 300:
                self.save()
                last_save = now
            if now - last_status >= 600:
                s = self.stats.summary(now)
                log.info("%.0f min: %s trades (%s/s), %s MB, %s disconnect(s), longest gap %ss",
                         s["minutes_measured"], s["trades"]["total"],
                         s["trades"]["per_second_average"], s["bandwidth"]["megabytes"],
                         s["connection"]["disconnects"],
                         s["connection"]["longest_silent_gap_seconds"])
                last_status = now
            if self.left() <= 0:
                self.stop.set()

    async def main(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except NotImplementedError:
                pass
        tasks = [asyncio.create_task(self.feed()), asyncio.create_task(self.clock_loop())]
        try:
            # The hard stop: never longer than the deadline (plus a moment to close).
            await asyncio.wait_for(self.stop.wait(), max(self.left(), 0) + 5)
        except asyncio.TimeoutError:
            pass
        self.stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.stats.roll_seconds(self.clock())
        self.save(finished=True)
        return self.stats.summary(self.clock(), finished=True)


def report(s):
    t, b, c, d, x = (s["trades"], s["bandwidth"], s["connection"], s["feed_delay_seconds"],
                     s["dexscreener"])
    return "\n".join([
        f"Trade feed probe: {s['minutes_measured']} min on {s['feed']}",
        f"  trades: {t['total']} ({t['buys']} buys, {t['sells']} sells); per second: average "
        f"{t['per_second_average']}, median {t['per_second_median']}, 95% {t['per_second_p95']}, "
        f"max {t['per_second_max']}; busiest minute {t['busiest_minute']}; launches "
        f"{t['launches_seen']}",
        f"  bandwidth: {b['megabytes']} MB ({b['megabytes_per_hour']} MB/h, about "
        f"{b['gigabytes_per_day_projected']} GB/day); {b['average_message_bytes']} bytes a "
        f"message; on Helius about {b['helius_credits_per_month_projected']:,} credits/month",
        f"  connection: {c['disconnects']} disconnect(s) ({c['seconds_disconnected']} s down), "
        f"{c['watchdog_reconnects']} silent reconnect(s); silent gaps {c['silent_gaps']}, "
        f"longest {c['longest_silent_gap_seconds']} s",
        f"  feed delay: median {d['median']} s, 95% {d['p95']} s",
        f"  DexScreener: lists a launch after median {x['listing_delay_seconds_median']} s "
        f"(95% {x['listing_delay_seconds_p95']} s; {x['not_listed_within_limit']} not within "
        f"the limit); its price is median {x['price_lag_seconds_median']} s behind "
        f"(95% {x['price_lag_seconds_p95']} s)",
        f"  own load: {s['own_load']['cpu_percent_of_one_core']}% of one CPU core, "
        f"{s['own_load']['max_memory_mb']} MB memory",
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=MAX_MINUTES,
                        help=f"how long to measure (at most {MAX_MINUTES})")
    parser.add_argument("--out", default=None,
                        help="folder for summary.json (default data/trade-feed-probe)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config()["trade_feed_probe"]
    folder = args.out or os.path.join(HERE, "data", "trade-feed-probe")
    probe = Probe(cfg, args.minutes, folder)
    log.info("measuring for %g min (stops by itself); summary in %s", probe.minutes, probe.path)
    summary = asyncio.run(probe.main())
    print(report(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
