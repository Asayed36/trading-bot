"""The early-launch RECORDER's runner (screener/launch_record.py): listens to pump.fun's
on-chain events and saves, for every new launch, what was known at creation and its real
price path for the first hour (data/launch-record/launches-YYYY-MM-DD.csv).

    python launch_record_bot.py --test 900          <- record for 15 minutes into a temporary
                                                       folder (nothing is saved), then print
                                                       a summary and the size estimate

On the server this is not run by hand: launch_bot.py (the launch-bot service) runs it while
[launch] stopped = true and [launch_record] enabled = true, and restarts itself on new code.

RECORDING ONLY. It never buys or sells, never uses a wallet, a key or a paid service. It only
READS: one read-only "logsSubscribe" to the Solana public RPC (the same endpoints, reconnect
rules and message decoder as the momentum bot: [momentum] ws_urls, screener/pumpfeed.py) and
the market backdrop (screener/backdrop.py, its own 15-minute cache).
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

from screener.backdrop import MarketBackdrop
from screener.launch_record import LaunchRecorder
from screener.pumpfeed import subscribe_request
from screener.settings import HERE, load_config

log = logging.getLogger("launch_record")

SAVE_SECONDS = 30                  # rows and health are written this often
LEDGER_SAVE_SECONDS = 600
BACKDROP_SECONDS = 60              # asking is free: the backdrop has its own 15-minute cache


def feed_urls(c):
    """[momentum] ws_urls (ws_url in older config files): the endpoints the momentum bot uses."""
    return list(c.get("ws_urls") or [c["ws_url"]])


def host(url):
    return urlparse(url).netloc or url


class RecordRunner:
    def __init__(self, cfg, data_folder, stop=None, connect=websockets.connect,
                 backdrop=None, clock=time.time):
        self.cfg, self.m = cfg, cfg["momentum"]
        self.recorder = LaunchRecorder(cfg, data_folder, clock=clock)
        self.connect, self.clock = connect, clock
        self.stop = stop or asyncio.Event()
        self.backdrop = backdrop
        self.last_ledger_save = clock()

    # ---- the feed (the momentum bot's connection and reconnect rules) ----

    async def feed(self):
        """The live feed, from the first of the endpoints that works. After a drop it
        reconnects to the same endpoint within reconnect_seconds; a connection that lasted
        under stable_seconds (or never got going) moves on to the next endpoint. The wait only
        grows once every endpoint has failed in a row."""
        m, urls = self.m, feed_urls(self.m)
        at, failures = 0, 0
        while not self.stop.is_set():
            url = urls[at % len(urls)]
            started = None
            pause = m["reconnect_seconds"]
            try:
                async with self.connect(url, ping_interval=20, ping_timeout=20,
                                        max_size=2**22, open_timeout=15) as ws:
                    await ws.send(subscribe_request())
                    started = self.clock()
                    self.recorder.connected(started, host(url))
                    log.info("connected to %s; subscribed to pump.fun's events", host(url))
                    while not self.stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), m["watchdog_seconds"])
                        except asyncio.TimeoutError:
                            raise ConnectionError(
                                f"no message for {m['watchdog_seconds']} s") from None
                        self.on_raw(raw)
            except (OSError, ConnectionError, asyncio.TimeoutError,
                    websockets.WebSocketException) as exc:
                if self.stop.is_set():
                    break
                lasted = self.clock() - started if started else 0
                if lasted >= m["stable_seconds"]:
                    failures = 0
                else:
                    failures += 1
                    at += 1
                if failures >= len(urls):
                    pause = min(pause * 2 ** (failures - len(urls) + 1), m["max_reconnect_seconds"])
                log.warning("feed disconnected from %s after %.0f s (%s); trying %s in %ss",
                            host(url), lasted, str(exc)[:120], host(urls[at % len(urls)]), pause)
            finally:
                self.recorder.disconnected(self.clock(), stopping=self.stop.is_set())
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
                if msg.get("id") == 1:
                    raise ConnectionError(f"refused the subscription: {str(msg['error'])[:160]}")
                log.warning("RPC says: %s", str(msg["error"])[:200])
            return
        result = (msg.get("params") or {}).get("result") or {}
        value = result.get("value") or {}
        slot = (result.get("context") or {}).get("slot")
        self.recorder.on_logs(value.get("logs"), value.get("err") is not None, self.clock(), slot)

    # ---- the clock, the backdrop, the files ----

    async def clock_task(self):
        last_save = last_prune = last_status = self.clock()
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), 0.5)
                return
            except asyncio.TimeoutError:
                pass
            now = self.clock()
            self.recorder.tick(now)
            if now - last_save >= SAVE_SECONDS:
                self.recorder.flush(now)
                self.recorder.write_health(now)
                last_save = now
            if now - self.last_ledger_save >= LEDGER_SAVE_SECONDS:
                self.last_ledger_save = now
                await asyncio.to_thread(self.recorder.save)
            if now - last_prune >= 3600:
                self.recorder.prune(now)
                last_prune = now
            if now - last_status >= 600:
                h = self.recorder.health(now)
                log.info("launch record: feed %s; %d launch(es) in the last hour; %d followed; "
                         "%d row(s) today (%d skipped by the cap)",
                         "up" if h["feed_up"] else "DOWN", h["launches_seen_last_hour"],
                         h["in_flight"], h["rows_written_today"], h["rows_skipped_by_cap_today"])
                last_status = now

    async def backdrop_task(self):
        """The market backdrop for new launches. Asking is cheap: the answer is cached for 15
        minutes (and in a file shared with the other bots), so this adds no requests."""
        if self.backdrop is None:
            return
        while not self.stop.is_set():
            try:
                self.recorder.set_backdrop(await asyncio.to_thread(self.backdrop))
            except Exception as exc:              # recording only: the columns stay blank
                log.info("backdrop skipped: %s", str(exc)[:120])
            try:
                await asyncio.wait_for(self.stop.wait(), BACKDROP_SECONDS)
            except asyncio.TimeoutError:
                pass

    def tasks(self):
        """The coroutines to run beside other work (launch_bot.py adds them to its own loop)."""
        return [self.feed(), self.clock_task(), self.backdrop_task()]

    def shutdown(self):
        """Save what is saved: finished rows, the ledger and the health file. Launches still
        followed are dropped (a partial hour would bias the data) and counted in the health file
        as the dropped_at_last_restart of the next start."""
        self.recorder.flush()
        self.recorder.write_health()
        self.recorder.save()

    async def main(self, stop_after=None, partial_at_end=False):
        loop = asyncio.get_running_loop()
        if stop_after:
            loop.call_later(stop_after, self.stop.set)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except NotImplementedError:
                pass
        tasks = [asyncio.create_task(x) for x in self.tasks()]
        await self.stop.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if partial_at_end:
            self.recorder.finish_all()
        self.shutdown()


def test_report(recorder, seconds, out=print):
    """What a short run saw, and what it says about a whole day (see the notes in the text)."""
    import csv
    import statistics
    rows = []
    for name in sorted(os.listdir(recorder.folder)):
        if name.startswith("launches-") and name.endswith(".csv"):
            with open(os.path.join(recorder.folder, name), newline="") as fh:
                rows += list(csv.DictReader(fh))
    days = recorder.days.values()
    total = lambda key: sum(d.get(key, 0) for d in days)          # noqa: E731
    seen, watched, by_buyers = total("launches_seen"), total("watched_60"), total("buyers_qualified")
    qualified = [r for r in rows if r["qualified"] == "1"]
    sample = [r for r in rows if r["sample"] == "1"]
    graduated = [r for r in rows if r["graduated"] == "yes"]
    out("")
    out(f"=== Launch recorder test run: {seconds / 60:.1f} minutes ===")
    out(f"Launches seen: {seen}  ({seen / max(seconds, 1) * 60:.0f} a minute)")
    out(f"Launches watched for at least 60 s: {watched}; with >= {recorder.min_buyers} buyers "
        f"in 60 s: {by_buyers}")
    out(f"Rows written (the launches still followed were finished early, see tracked_seconds): "
        f"{len(rows)}  = {len(qualified)} qualified + {len(sample)} in the 2% sample "
        f"(overlap counted in both), {len(graduated)} graduated")
    out(f"Feed: {total('feed_disconnects')} disconnect(s), {total('gap_seconds')} s of gaps; "
        f"{len([r for r in rows if r['incomplete'] == '1'])} row(s) marked incomplete")
    # the on-chain creation time: is it there, and is it close to the receive time?
    lags = sorted(recorder.lags)
    if lags:
        out(f"Creation time: {recorder.chain_creates} launch(es) used the on-chain time, "
            f"{recorder.received_creates} fell back to the receive time; receive time minus "
            f"on-chain time: median {statistics.median(lags):.1f} s, 90th percentile "
            f"{lags[int(len(lags) * 0.9)]:.1f} s, largest {lags[-1]:.1f} s")
    dev = [r for r in rows if r["dev_buy_pct"]]
    out(f"Rows with a creator buy in the creation transaction: {len(dev)} of {len(rows)}"
        + (f" (median {statistics.median(float(r['dev_buy_pct']) for r in dev):.2f}% of the supply)"
           if dev else ""))
    # the estimate for a whole day
    per_day = seen * 86400 / max(seconds, 1)
    f = by_buyers / watched if watched else None
    out("")
    out("Estimate for a whole day (this window only; pump.fun is busier at some hours):")
    out(f"  launches a day: about {per_day:,.0f}")
    if f is not None:
        rows_day = per_day * (f + (1 - f) * recorder.sample_pct / 100)
        sample_day = per_day * recorder.sample_pct / 100
        non_sample = rows_day - sample_day
        sizes = [len(",".join(r.values())) + 1 for r in rows]
        mean = statistics.mean(sizes) * 1.1 if sizes else 0
        out(f"  share with >= {recorder.min_buyers} buyers in 60 s: {100 * f:.1f}%")
        out(f"  rows a day: about {rows_day:,.0f} (qualified {non_sample:,.0f}, the 2% sample "
            f"{sample_day:,.0f}); graduations add a few more")
        out(f"  cap max_rows_per_day = {recorder.max_rows} applies to the qualified-only rows: "
            + ("the cap WOULD be reached" if non_sample > recorder.max_rows else "not reached"))
        out(f"  row size: about {mean:.0f} bytes -> about {rows_day * mean / 1e6:.1f} MB a day "
            f"({rows_day * mean * 30 / 1e6:.0f} MB a month)")
    else:
        out("  not enough launches watched for a minute to estimate")
    out("")
    out("A handful of real rows:")
    keep = ("created_at_utc", "created_source", "token_address", "symbol", "dev_buy_pct",
            "first_block_buyers", "bundle_suspect_buyers", "creator_prior_launches", "copycat_name",
            "buyers_60s", "buys", "sells", "price_sol_5s", "price_sol_60s", "price_sol_300s",
            "peak_price_sol", "seconds_to_peak", "graduated", "btc_change_1h_pct",
            "sol_change_1h_pct", "incomplete", "sample", "qualified", "tracked_seconds")
    shown = (qualified[:3] + [r for r in sample if r not in qualified][:3]) or rows[:5]
    for r in shown[:6]:
        out("  " + json.dumps({k: r[k] for k in keep}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", type=int, metavar="SECONDS", required=True,
                        help="record for SECONDS (e.g. 900) into a temporary folder (or --out), "
                             "finish the launches still followed with the time they were "
                             "followed, and print a summary and the size estimate")
    parser.add_argument("--out", help="keep the files of the test run in this folder")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        data = args.out or tmp
        runner = RecordRunner(cfg, data, backdrop=MarketBackdrop(
            os.path.join(data, "backdrop_cache.json")))
        asyncio.run(runner.main(stop_after=args.test, partial_at_end=True))
        test_report(runner.recorder, time.time() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
