"""Runs the "launch" paper strategy around the clock (on your own server).

    python launch_bot.py

It listens to PumpPortal's free real-time data feed for new pump.fun tokens
and the trades of the tokens it is following, and paper-trades them at three
speeds (see screener/launch.py). Results are written to data/launch/ and
pushed to GitHub by deploy/push_results.sh.

PAPER TRADING ONLY. This program only READS public data. It never connects
to a wallet, never uses a private key, never signs anything and never calls
PumpPortal's trading API. The only messages it ever sends to PumpPortal are
the four data subscriptions in ALLOWED_METHODS.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time

import websockets

from run import HERE, load_config
from screener.api import ApiError, PublicApi
from screener.filters import best_pair, to_float
from screener.launch import LaunchEngine

WSOL = "So11111111111111111111111111111111111111112"
# The only things this program ever asks PumpPortal for (read-only data).
ALLOWED_METHODS = {"subscribeNewToken", "subscribeMigration",
                   "subscribeTokenTrade", "unsubscribeTokenTrade"}

log = logging.getLogger("launch_bot")


def request(method, keys=None):
    """A PumpPortal data request, refusing anything that isn't read-only."""
    if method not in ALLOWED_METHODS:
        raise ValueError(f"{method} is not an allowed read-only data request")
    msg = {"method": method}
    if keys is not None:
        msg["keys"] = list(keys)
    return json.dumps(msg)


def sol_price(api):
    """SOL in USD from DexScreener's most liquid SOL/USDC or SOL/USDT pool."""
    pairs = [p for p in api.pairs_for_tokens([WSOL])
             if (p.get("baseToken") or {}).get("address") == WSOL
             and (p.get("quoteToken") or {}).get("symbol") in ("USDC", "USDT")]
    pair = max(pairs, key=lambda p: to_float((p.get("liquidity") or {}).get("usd")) or 0,
               default=None)
    return to_float((pair or {}).get("priceUsd"))


def token_prices(api, mints):
    pairs = api.pairs_for_tokens(mints) if mints else []
    out = {}
    for mint in mints:
        pair = best_pair(pairs, mint, [])
        price = to_float((pair or {}).get("priceUsd"))
        if price:
            out[mint] = price
    return out


class Runner:
    def __init__(self, cfg, data_folder):
        self.cfg = cfg
        self.engine = LaunchEngine(cfg, data_folder)
        self.api = PublicApi(timeout=15)
        self.stop = asyncio.Event()
        self.ws = None

    async def send(self, method, keys=None):
        if self.ws is not None:
            await self.ws.send(request(method, keys))

    async def apply(self, subscribe, unsubscribe):
        if subscribe:
            await self.send("subscribeTokenTrade", subscribe)
        if unsubscribe:
            await self.send("unsubscribeTokenTrade", unsubscribe)

    async def feed(self):
        """One connection to PumpPortal, reconnecting with a growing pause."""
        pause = 5
        while not self.stop.is_set():
            try:
                async with websockets.connect(self.cfg["launch"]["ws_url"], ping_interval=20,
                                              ping_timeout=20, max_size=2**22) as ws:
                    self.ws = ws
                    await self.send("subscribeNewToken")
                    await self.send("subscribeMigration")
                    await self.apply(self.engine.subscriptions(), [])
                    log.info("connected to PumpPortal")
                    pause = 5
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        await self.apply(*self.engine.on_message(msg, time.time()))
                        if self.stop.is_set():
                            break
            except (OSError, websockets.WebSocketException) as exc:
                log.warning("feed disconnected (%s); retrying in %ss", exc, pause)
            finally:
                self.ws = None
            if not self.stop.is_set():
                try:
                    await asyncio.wait_for(self.stop.wait(), pause)
                except asyncio.TimeoutError:
                    pass
                pause = min(pause * 2, 60)

    async def clock(self):
        last_save = last_prune = last_status = time.time()
        while not self.stop.is_set():
            await asyncio.sleep(0.5)
            now = time.time()
            await self.apply(*self.engine.tick(now))
            if now - last_save >= 30:
                self.engine.save()
                last_save = now
            if now - last_prune >= 3600:
                self.engine.prune(now)
                last_prune = now
            if now - last_status >= 600:
                open_ = {n: len(t.open_positions) for n, t in self.engine.traders.items()}
                log.info("following %d launch(es); open positions %s; SOL $%s",
                         len(self.engine.watch), open_, self.engine.sol_usd)
                last_status = now

    async def prices(self):
        """SOL price every 5 minutes; DexScreener prices for held tokens the
        feed no longer prices, every 20 seconds."""
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

    async def main(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except NotImplementedError:  # Windows
                pass
        tasks = [asyncio.create_task(x) for x in (self.feed(), self.clock(), self.prices())]
        await self.stop.wait()
        if self.ws is not None:
            await self.ws.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.engine.save()
        log.info("stopped; everything saved")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    if not cfg.get("launch", {}).get("enabled"):
        print("The launch strategy is turned off ([launch] enabled = false).")
        return 0
    folder = os.path.join(HERE, cfg["files"]["data_folder"])
    asyncio.run(Runner(cfg, folder).main())
    return 0


if __name__ == "__main__":
    sys.exit(main())
