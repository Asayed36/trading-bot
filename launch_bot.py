"""Runs the "launch" paper strategy around the clock (on your own server).

    python launch_bot.py            <- run for good (the systemd service does this)
    python launch_bot.py --test     <- try the setup for 2 minutes; saves nothing

It listens to PumpPortal's free real-time data feed for new pump.fun tokens
and migrations, and paper-trades them at three speeds (see
screener/launch.py). It doesn't subscribe to the tokens' trades: PumpPortal's
trade stream needs an API key and a funded wallet. Prices after creation
come from DexScreener. Results are written to data/launch/ and
pushed to GitHub by deploy/push_results.sh. When that push brings new code
the bot uses, it saves everything and exits by itself, and systemd starts it
again with the new code (screener/autorestart.py; "automatic restart" in
journalctl -u launch-bot).

PAPER TRADING ONLY. This program only READS public data. It never connects
to a wallet, never uses a private key, never signs anything and never calls
PumpPortal's trading API. The only messages it ever sends to PumpPortal are
the two free data subscriptions in ALLOWED_METHODS.
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

import websockets

from screener.api import ApiError, PublicApi
from screener.autorestart import CodeWatcher, restart_message
from screener.jupiter import JupiterOrganic
from screener.launch import LaunchEngine, sol_price, token_prices
from screener.settings import HERE, load_config

# The config.toml sections the bot reads: only changes there restart it.
CONFIG_SECTIONS = ("launch", "files")
CODE_CHECK_SECONDS = 30
# The only things this program ever asks PumpPortal for (read-only data).
ALLOWED_METHODS = {"subscribeNewToken", "subscribeMigration"}

log = logging.getLogger("launch_bot")


def request(method, keys=None):
    """A PumpPortal data request, refusing anything that isn't read-only."""
    if method not in ALLOWED_METHODS:
        raise ValueError(f"{method} is not an allowed read-only data request")
    msg = {"method": method}
    if keys is not None:
        msg["keys"] = list(keys)
    return json.dumps(msg)


class Runner:
    ORGANIC_POLL_SECONDS = 2     # how often to look for launches due a Jupiter reading

    def __init__(self, cfg, data_folder, watcher=None):
        self.cfg = cfg
        self.watcher = watcher   # CodeWatcher: restart when the push brings new code
        self.restarting = None
        self.engine = LaunchEngine(cfg, data_folder)
        self.api = PublicApi(timeout=15)
        self.stop = asyncio.Event()
        self.ws = None
        self.kinds = {}          # feed messages received, by type (for --test)
        self.jupiter = JupiterOrganic(timeout=5)   # organic score for entries.csv (logging)

    async def send(self, method, keys=None):
        if self.ws is not None:
            await self.ws.send(request(method, keys))

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
                    log.info("connected to PumpPortal")
                    pause = 5
                    said = set()
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        kind = str(msg.get("txType") or "reply") if isinstance(msg, dict) \
                            else "other"
                        self.kinds[kind] = self.kinds.get(kind, 0) + 1
                        if not (isinstance(msg, dict) and msg.get("mint")):
                            # PumpPortal's replies (subscription confirmations,
                            # errors): logged once each per connection.
                            text = str(msg)[:300]
                            if text not in said and len(said) < 50:
                                said.add(text)
                                log.info("PumpPortal says: %s", text)
                            continue
                        self.engine.on_message(msg, time.time())
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
            self.engine.tick(now)
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

    async def organic(self):
        """Jupiter's organic score for selected launches, every couple of
        seconds until their last speed has bought. Logging only: the readings
        only go into entries.csv, and a failed lookup leaves them blank."""
        while not self.stop.is_set():
            for mint in self.engine.jupiter_due(time.time()):
                values = await asyncio.to_thread(self.jupiter, mint)
                self.engine.set_jupiter(mint, values, time.time())
            try:
                await asyncio.wait_for(self.stop.wait(), self.ORGANIC_POLL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def watch_code(self):
        """Every CODE_CHECK_SECONDS: if the hourly push changed the bot's
        code, stop (everything is saved below) so systemd restarts it."""
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
            except NotImplementedError:  # Windows
                pass
        tasks = [asyncio.create_task(x)
                 for x in (self.feed(), self.clock(), self.prices(), self.organic(),
                           self.watch_code())]
        await self.stop.wait()
        if self.ws is not None:
            await self.ws.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.engine.save()
        log.info("stopped; everything saved"
                 + ("; systemd starts the new code in about 10 s" if self.restarting else ""))


def test_summary(engine, kinds=None):
    """What a --test run saw, for checking the setup."""
    totals = {}
    for hour in engine.stats.values():
        for key, n in hour.items():
            totals[key] = totals.get(key, 0) + n
    lines = ["", "Test run summary (nothing was saved to data/launch):"]
    lines += [f"  {key}: {n}" for key, n in sorted(totals.items())] or ["  no launches seen"]
    for name, trader in engine.traders.items():
        lines.append(f"  paper buys at {name}: {len(trader.state['ever_bought'])}")
    if kinds is not None:
        got = ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())) or "none"
        lines.append(f"  feed messages by type: {got}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", nargs="?", const=120, type=int, metavar="SECONDS",
                        help="try the setup: run for SECONDS (default 120, enough for all three "
                             "speeds) with results in a temporary folder, then print a summary")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    if not cfg.get("launch", {}).get("enabled"):
        print("The launch strategy is turned off ([launch] enabled = false).")
        return 0
    if args.test:
        # A test must never write real results: a short run leaves the slower
        # speeds without their buys and uses up the hourly cap.
        with tempfile.TemporaryDirectory() as folder:
            runner = Runner(cfg, folder)
            asyncio.run(runner.main(stop_after=args.test))
            print(test_summary(runner.engine, runner.kinds))
        return 0
    folder = os.path.join(HERE, cfg["files"]["data_folder"])
    # Watch the code it loaded (everything is imported by now).
    watcher = CodeWatcher(HERE, CONFIG_SECTIONS)
    log.info("watching %d code file(s) and config.toml %s for updates",
             len(watcher.files), ", ".join(f"[{s}]" for s in CONFIG_SECTIONS))
    asyncio.run(Runner(cfg, folder, watcher).main())
    return 0


if __name__ == "__main__":
    sys.exit(main())
