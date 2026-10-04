"""Runs the "main (1 min)" paper strategy every minute (on your own server).

    python main_1min.py            <- run for good (the main-1min service does this)
    python main_1min.py --test     <- one run against the real sites; saves nothing

It is the main strategy, checked every minute instead of every few minutes:
exactly main's entry checks ([filters] in config.toml, screener/filters.py)
and main's exits and costs ([paper_trading]: $10 buys, sell half at +50%,
-30% stop, trailing stop 40% below the peak, the 48-hour time exit, 3%
costs). Only the timing differs, so the two can be compared. Its own
positions, journal and entries are in data/main-1min/: it never reads or
writes the GitHub main strategy's files, and it opens no GitHub issues.
deploy/push_results.sh pushes data/main-1min to GitHub once an hour.

Staying within the free limits, every minute:
  - DexScreener: the latest profiles and boosts, the candidates' pairs (30
    per request) and the open positions' prices: about 4-6 requests a minute
    (its limits are 60 a minute for the lists, 300 a minute for pairs).
  - RugCheck: only tokens that pass the market checks, and only when they're
    new or their last report is older than rugcheck_recheck_minutes (the
    reports are kept in memory), at most rugcheck_max_per_run a minute,
    spaced out like main ([api] rugcheck_delay_seconds). Tokens over the cap
    wait for the next minute. If RugCheck says "too many requests", it isn't
    asked again for rugcheck_pause_minutes.

PAPER TRADING ONLY. It only READS public data with GET requests. It never
connects a wallet, never uses a private key, never signs or sends anything.
"""

import argparse
import json
import logging
import os
import signal
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

from run import HERE, current_prices, load_config
from screener.api import ApiError, PublicApi, RateLimited
from screener.filters import PASS, best_pair, evaluate, find_candidates, market_checks
from screener.jupiter import JupiterOrganic
from screener.paper_trader import PaperTrader, now_utc

log = logging.getLogger("main_1min")
HOURS_KEPT = 48            # call counts per hour kept in health.json


class SafeTrader(PaperTrader):
    """Main's PaperTrader (the same exits and costs), saving positions.json
    in one step so the hourly push never sees a half-written file."""

    def save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.state, fh, indent=2)
        os.replace(tmp, self.state_path)


class CountingApi:
    """The read-only PublicApi, counting requests per site (for the health
    row: shows it stays within the free limits)."""

    def __init__(self, api):
        self.api = api
        self.calls = {"dexscreener": 0, "rugcheck": 0}

    def latest_profiles(self):
        self.calls["dexscreener"] += 1
        return self.api.latest_profiles()

    def latest_boosts(self):
        self.calls["dexscreener"] += 1
        return self.api.latest_boosts()

    def pairs_for_tokens(self, addresses):
        addresses = list(addresses)
        self.calls["dexscreener"] += (len(addresses) + 29) // 30
        return self.api.pairs_for_tokens(addresses)

    def rugcheck_report(self, address):
        self.calls["rugcheck"] += 1
        return self.api.rugcheck_report(address)


class MainOneMinute:
    def __init__(self, cfg, data_folder, api, jupiter=None):
        self.cfg = cfg
        self.c, self.f, self.pt = cfg["main_1min"], cfg["filters"], cfg["paper_trading"]
        self.folder = os.path.join(data_folder, self.c["folder"])
        self.api = CountingApi(api)
        self.jupiter = jupiter
        self.reports = {}          # token -> (when, RugCheck report): memory only
        self.rugcheck_paused_until = None

    def _report(self, address, now, budget):
        """RugCheck's report: from memory when fresh, else asked (if the
        budget and RugCheck allow). Returns (report, asked) or None = wait."""
        fresh = timedelta(minutes=self.c["rugcheck_recheck_minutes"])
        known = self.reports.get(address)
        if known and now - known[0] < fresh:
            return known[1], False
        if budget["rugcheck"] <= 0:
            return None
        if self.rugcheck_paused_until and now < self.rugcheck_paused_until:
            return None
        budget["rugcheck"] -= 1
        try:
            report = self.api.rugcheck_report(address)
        except RateLimited:
            self.rugcheck_paused_until = now + timedelta(minutes=self.c["rugcheck_pause_minutes"])
            budget["rugcheck"] = 0
            return None
        except ApiError as exc:
            log.info("RugCheck failed for %s: %s", address, exc)
            report = None            # like main: no report = the safety checks fail
        self.reports[address] = (now, report)
        return report, True

    def run_once(self, now=None, out=print):
        """One run: fetch everything first, then trade. A DexScreener failure
        skips the run without changing anything (like main)."""
        now = now or now_utc()
        # Forget reports nobody will reuse.
        fresh = timedelta(minutes=self.c["rugcheck_recheck_minutes"])
        self.reports = {a: r for a, r in self.reports.items() if now - r[0] < fresh}
        before = dict(self.api.calls)
        try:
            trader = SafeTrader(self.pt, self.folder)
            trader.organic = self.jupiter
            prices = current_prices(self.api, trader.open_positions, self.f["allowed_dexes"])
            addresses = find_candidates(self.api.latest_profiles(), self.api.latest_boosts())
            pairs = self.api.pairs_for_tokens(addresses) if addresses else []
            budget = {"rugcheck": self.c["rugcheck_max_per_run"]}
            results, waiting = [], 0
            for addr in addresses:
                pair = best_pair(pairs, addr, self.f["allowed_dexes"])
                market_ok = all(c.status == PASS for c in market_checks(pair, self.f))
                skip = self.cfg["api"]["skip_safety_if_market_fails"] and not market_ok
                report = None
                if not skip:
                    got = self._report(addr, now, budget)
                    if got is None:
                        waiting += 1          # checked in a later minute
                        continue
                    report = got[0]
                results.append(evaluate(addr, pair, report, self.f, safety_skipped=skip))
        except ApiError as exc:
            self._health(now, before, str(exc))
            out(f"{now:%H:%M} skipped, nothing changed: {exc}")
            return None

        lines = []
        for s in trader.update(prices, when=now):
            lines.append(f"SELL {s['symbol']} {s['reason']} P&L ${s['pnl_usd']:+.2f}")
        for r in results:
            if r.passed and trader.buy(r, when=now):
                lines.append(f"BUY  {r.symbol} ${self.pt['buy_amount_usd']} at ${r.price:.10g}")
        trader.save()
        passed = sum(r.passed for r in results)
        note = f", {waiting} waiting for RugCheck" if waiting else ""
        self._health(now, before, None)
        out(f"{now:%H:%M} {len(addresses)} candidate(s), {len(results)} checked, {passed} "
            f"passed{note}; {len(trader.open_positions)} open; "
            f"P&L ${trader.state['running_total_pnl_usd']:+.2f}"
            + "".join(f"\n  {line}" for line in lines))
        return results

    def _health(self, now, before, error):
        """data/main-1min/health.json: the last good run, the last error,
        and requests per site per hour (pushed with the results)."""
        path = os.path.join(self.folder, "health.json")
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        if error is None:
            data["last_ok"] = now.isoformat()
        else:
            data["last_error"], data["error_at"] = error[:200], now.isoformat()
        hour = now.strftime("%Y-%m-%dT%H:00")
        calls = data.setdefault("calls_per_hour", {})
        row = calls.setdefault(hour, {"runs": 0, "dexscreener": 0, "rugcheck": 0})
        row["runs"] += 1
        for site, n in self.api.calls.items():
            row[site] = row.get(site, 0) + n - before.get(site, 0)
        for old in sorted(calls)[:-HOURS_KEPT]:
            calls.pop(old)
        if self.rugcheck_paused_until and now < self.rugcheck_paused_until:
            data["rugcheck_paused_until"] = self.rugcheck_paused_until.isoformat()
        else:
            data.pop("rugcheck_paused_until", None)
        os.makedirs(self.folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)


def forever(bot, every=60, clock=time.time, sleep=time.sleep, out=print, stop=None):
    """A run at the start of every minute until `stop()` says so. A crash in
    one run is logged and the next minute runs as normal."""
    stop = stop or (lambda: False)
    while not stop():
        try:
            bot.run_once(datetime.fromtimestamp(clock(), timezone.utc), out)
        except Exception:  # keep going: one bad answer mustn't stop the bot
            log.exception("run failed")
        if stop():
            break
        sleep(every - clock() % every)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="one run against the real sites in a temporary folder "
                             "(nothing is saved)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config()
    if not cfg.get("main_1min", {}).get("enabled"):
        print("main_1min is turned off in config.toml ([main_1min] enabled = false).")
        return 0
    api = PublicApi(cfg["api"]["timeout_seconds"], cfg["api"]["rugcheck_delay_seconds"])
    if args.test:
        with tempfile.TemporaryDirectory() as folder:
            print("Test run: real data, results in a temporary folder (nothing is saved).")
            MainOneMinute(cfg, folder, api, JupiterOrganic()).run_once(out=print)
        return 0
    bot = MainOneMinute(cfg, os.path.join(HERE, cfg["files"]["data_folder"]), api,
                        JupiterOrganic())
    # systemd stops the bot with SIGTERM: between runs it exits at once; in
    # the middle of a run it finishes and saves first.
    busy, stopping = [], []

    def on_term(*_):
        stopping.append(1)
        if not busy:
            raise SystemExit(0)
    signal.signal(signal.SIGTERM, on_term)

    class Guarded:
        def run_once(self, now, out):
            busy.append(1)
            try:
                return bot.run_once(now, out)
            finally:
                busy.clear()

    print(f"main (1 min): paper trading every {cfg['main_1min']['every_seconds']} s into "
          f"{bot.folder}", flush=True)
    forever(Guarded(), cfg["main_1min"]["every_seconds"], out=lambda s: print(s, flush=True),
            stop=lambda: bool(stopping))
    return 0


if __name__ == "__main__":
    sys.exit(main())
