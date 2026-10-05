"""Runs the "momentum" paper strategy around the clock (on your own server).

    python momentum_bot.py            <- run for good (the momentum-bot service does this)
    python momentum_bot.py --test     <- try it for 2 minutes; saves nothing
    python momentum_bot.py --check-feeds  <- which free RPC endpoints work now

It listens to a free public Solana RPC for pump.fun's live events (every
trade, launch and graduation: screener/pumpfeed.py; [momentum] ws_urls are
the endpoints, with backups to switch to) and paper-trades three
momentum variants side by side (screener/momentum.py). Results go to
data/momentum/ and are pushed to GitHub by deploy/push_results.sh. When that
push brings new code the bot uses, it saves everything and exits by itself,
and systemd starts it again with the new code ("automatic restart" in
journalctl -u momentum-bot).

PAPER TRADING ONLY. It only READS public data: one read-only subscription
("logsSubscribe") to the RPC, plus DexScreener (SOL's price, and held
tokens' prices once they leave the curve) and Jupiter (the organic score at
each buy). It never connects to a wallet, never uses a private key, never
signs or sends anything.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import tempfile
import time
from urllib.parse import urlparse

import websockets

from screener.api import ApiError, PublicApi
from screener.autorestart import CodeWatcher, restart_message
from screener.jupiter import JupiterOrganic
from screener.launch import sol_price, token_prices
from screener.momentum import MomentumEngine
from screener.pumpfeed import subscribe_request
from screener.settings import HERE, load_config

# The config.toml sections the bot reads: only changes there restart it.
CONFIG_SECTIONS = ("momentum", "launch", "files")
CODE_CHECK_SECONDS = 30

log = logging.getLogger("momentum_bot")


class Runner:
    def __init__(self, cfg, data_folder, watcher=None, connect=websockets.connect,
                 api=None, jupiter=None):
        self.cfg, self.c = cfg, cfg["momentum"]
        self.engine = MomentumEngine(cfg, data_folder)
        self.connect = connect
        self.api = api or PublicApi(timeout=15)
        self.jupiter = jupiter if jupiter is not None else JupiterOrganic(timeout=5)
        self.watcher = watcher
        self.restarting = None
        self.stop = asyncio.Event()

    def health(self):
        """data/momentum/health.json (pushed): is the feed up, the last
        time it was, and this hour's counts."""
        path = os.path.join(self.engine.folder, "health.json")
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        now = time.time()
        last_ok = data.get("last_ok")
        data.update(self.engine.health(now))
        data["last_ok"] = data["last_ok"] or last_ok      # kept across restarts
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)

    async def feed(self):
        """The live feed, from the first of [momentum] ws_urls that works.
        After a drop it reconnects to the same endpoint within
        reconnect_seconds; a connection that lasted under stable_seconds (or
        never got going) moves on to the next endpoint. The wait only grows
        once every endpoint has failed in a row."""
        c, urls = self.c, feed_urls(self.c)
        at, failures = 0, 0
        while not self.stop.is_set():
            url = urls[at % len(urls)]
            started = None
            try:
                async with self.connect(url, ping_interval=20, ping_timeout=20,
                                        max_size=2**22, open_timeout=15) as ws:
                    await ws.send(subscribe_request())
                    started = time.time()
                    self.engine.connected(started, host(url))
                    log.info("connected to %s; subscribed to pump.fun's events", host(url))
                    while not self.stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), c["watchdog_seconds"])
                        except asyncio.TimeoutError:
                            raise ConnectionError(
                                f"no message for {c['watchdog_seconds']} s") from None
                        self.on_raw(raw)
            except (OSError, ConnectionError, asyncio.TimeoutError,
                    websockets.WebSocketException) as exc:
                if self.stop.is_set():
                    break
                lasted = time.time() - started if started else 0
                if lasted >= c["stable_seconds"]:
                    failures = 0              # it was working: try it again first
                else:
                    failures += 1
                    at += 1                   # it wasn't: the next endpoint
                pause = c["reconnect_seconds"]
                if failures >= len(urls):     # every endpoint failed in a row
                    pause = min(pause * 2 ** (failures - len(urls) + 1),
                                c["max_reconnect_seconds"])
                log.warning("feed disconnected from %s after %.0f s (%s); no new buys until "
                            "it's back; trying %s in %ss", host(url), lasted, str(exc)[:120],
                            host(urls[at % len(urls)]), pause)
            finally:
                self.engine.disconnected(time.time())
            if self.stop.is_set():
                break
            try:
                await asyncio.wait_for(self.stop.wait(), pause)
            except asyncio.TimeoutError:
                pass

    def on_raw(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("method") != "logsNotification":
            if "error" in msg:
                if msg.get("id") == 1:        # it refused the subscription itself
                    raise ConnectionError(f"refused the subscription: "
                                          f"{str(msg['error'])[:160]}")
                log.warning("RPC says: %s", str(msg["error"])[:200])
            return
        value = ((msg.get("params") or {}).get("result") or {}).get("value") or {}
        self.engine.on_logs(value.get("logs"), value.get("err") is not None, time.time())

    async def clock(self):
        last_save = last_prune = last_status = time.time()
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), 0.5)
                return
            except asyncio.TimeoutError:
                pass
            now = time.time()
            self.engine.tick(now)
            if now - last_save >= 30:
                self.engine.save()
                self.health()
                last_save = now
            if now - last_prune >= 3600:
                self.engine.prune(now)
                last_prune = now
            if now - last_status >= 600:
                h = self.engine.health(now)
                log.info("feed %s; following %d launch(es); open %s; this hour %s",
                         "up" if h["feed_up"] else "DOWN", h["following"], h["open"],
                         h["this_hour"])
                last_status = now

    async def prices(self):
        """SOL every 5 minutes; DexScreener for held tokens the feed no
        longer prices, every 20 seconds."""
        last_sol = 0.0
        while not self.stop.is_set():
            now = time.time()
            try:
                if now - last_sol >= 300 or not self.engine.sol_usd:
                    price = await asyncio.to_thread(sol_price, self.api)
                    if price:
                        self.engine.set_sol_price(price)
                        last_sol = now
                mints = self.engine.needs_external(now)
                if mints:
                    found = await asyncio.to_thread(token_prices, self.api, mints)
                    self.engine.set_external_prices(found, time.time())
            except ApiError as exc:
                log.warning("DexScreener: %s", exc)
            try:
                await asyncio.wait_for(self.stop.wait(), 20)
            except asyncio.TimeoutError:
                pass

    async def organic(self):
        """Jupiter's organic score for launches with a signal (logging only:
        it goes into entries.csv; a failed lookup leaves it blank)."""
        while not self.stop.is_set():
            for mint in self.engine.jupiter_due():
                values = await asyncio.to_thread(self.jupiter, mint) if self.jupiter else {}
                self.engine.set_jupiter(mint, values, time.time())
            try:
                await asyncio.wait_for(self.stop.wait(), 1)
            except asyncio.TimeoutError:
                pass

    async def watch_code(self):
        while self.watcher is not None and not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), CODE_CHECK_SECONDS)
                return
            except asyncio.TimeoutError:
                pass
            changed = self.watcher.changed()
            if changed:
                self.restarting = changed
                log.warning(restart_message(changed))
                self.stop.set()

    async def main(self, stop_after=None):
        loop = asyncio.get_running_loop()
        if stop_after:
            loop.call_later(stop_after, self.stop.set)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except NotImplementedError:
                pass
        tasks = [asyncio.create_task(x) for x in (self.feed(), self.clock(), self.prices(),
                                                  self.organic(), self.watch_code())]
        await self.stop.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.engine.save()
        self.health()
        log.info("stopped; everything saved"
                 + ("; systemd starts the new code in about 10 s" if self.restarting else ""))


def feed_urls(c):
    """[momentum] ws_urls (ws_url in older config files)."""
    return list(c.get("ws_urls") or [c["ws_url"]])


def host(url):
    return urlparse(url).netloc or url


async def check_feed(url, seconds=15, connect=websockets.connect):
    """Connect to one endpoint, subscribe, and count pump.fun notifications
    for `seconds`. Returns a line saying how it went."""
    try:
        async with connect(url, open_timeout=15, max_size=2**22) as ws:
            await ws.send(subscribe_request())
            notes, end = 0, time.time() + seconds
            while time.time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), max(end - time.time(), 0.1))
                except asyncio.TimeoutError:
                    break
                msg = json.loads(raw)
                if msg.get("id") == 1 and "error" in msg:
                    return f"FAIL {host(url)}: refused the subscription: {str(msg['error'])[:120]}"
                notes += msg.get("method") == "logsNotification"
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException, ValueError) as exc:
        return f"FAIL {host(url)}: {type(exc).__name__}: {str(exc)[:120]}"
    if not notes:
        return f"FAIL {host(url)}: connected, but no pump.fun events in {seconds} s"
    return f"OK   {host(url)}: {notes} pump.fun notifications in {seconds} s ({notes / seconds:.0f}/s)"


def test_summary(engine):
    totals = {}
    for hour in engine.stats.values():
        for key, n in hour.items():
            totals[key] = totals.get(key, 0) + n
    lines = ["", "Test run summary (nothing was saved to data/momentum):"]
    lines += [f"  {key}: {n}" for key, n in sorted(totals.items())]
    for name, trader in engine.traders.items():
        lines.append(f"  paper buys at {name}: {len(trader.state['ever_bought'])}")
    path = os.path.join(engine.folder, "near_misses.csv")
    if os.path.exists(path):
        with open(path) as fh:
            near = fh.read().splitlines()
        lines.append(f"  near misses logged: {len(near) - 1}")
        lines += [f"    {row[:200]}" for row in near[:6]]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", nargs="?", const=120, type=int, metavar="SECONDS",
                        help="try it: run for SECONDS (default 120) with results in a temporary "
                             "folder, then print a summary")
    parser.add_argument("--check-feeds", action="store_true",
                        help="try each of [momentum] ws_urls for 15 seconds and say which "
                             "deliver pump.fun's events (saves nothing)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    if args.check_feeds:
        urls = feed_urls(cfg["momentum"])
        print(f"Trying {len(urls)} endpoint(s), 15 seconds each (read-only)...", flush=True)
        lines = [asyncio.run(check_feed(url)) for url in urls]
        print("\n".join(lines))
        return 0 if any(line.startswith("OK") for line in lines) else 1
    if not cfg.get("momentum", {}).get("enabled"):
        print("The momentum strategy is turned off ([momentum] enabled = false).")
        return 0
    if args.test:
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(cfg, folder)
            asyncio.run(runner.main(stop_after=args.test))
            print(test_summary(runner.engine))
        return 0
    watcher = CodeWatcher(HERE, CONFIG_SECTIONS)
    log.info("watching %d code file(s) and config.toml %s for updates",
             len(watcher.files), ", ".join(f"[{s}]" for s in CONFIG_SECTIONS))
    asyncio.run(Runner(cfg, os.path.join(HERE, cfg["files"]["data_folder"]), watcher).main())
    return 0


if __name__ == "__main__":
    sys.exit(main())
