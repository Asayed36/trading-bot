"""Runs the "news (listings)" paper strategy every minute (on your own server).

    python news_listings_bot.py           <- run for good (the news-listings service does this)
    python news_listings_bot.py --test    <- one run against the real sites; saves nothing

It is the news strategy (screener/news.py) for the exchange listings only:
the [[news.sources]] marked runs_on = "server" in config.toml (Binance's
new-listing list, Kraken's blog, and new coins in the public market lists
of Coinbase, Upbit and OKX), read every minute instead of every 15 minutes
on GitHub, where those sources are no longer read. Everything else is the
news strategy's: the coin matching, the checks, the AI check, the costs and
the exits (all under [news]). Only the timing differs, so the two can be
compared. Its own positions, journal, candidate log and AI verdicts are in
data/news-listings/: it never reads or writes the GitHub news strategy's
files, and it opens no GitHub issues. deploy/push_results.sh pushes them to
GitHub once an hour. When that push brings new code the bot uses, it exits
by itself between two runs and systemd starts it again with the new code
(screener/autorestart.py; "automatic restart" in journalctl -u news-listings).

A second paper version, "news (listings) fast" ([news_listings.fast]), buys
the same signals at the same moment and price but exits within hours: half
at +20%, the rest 10% below its peak, everything at -10% or after 6 hours.
Its own positions and journal are in data/news-listings/fast/.

Requests, all read-only and well within the free limits: each source once a
minute (5 a minute in all); CoinGecko only when there's a new listing to
match, plus the open positions' prices every [news_listings]
prices_every_minutes, within its own monthly count; and the AI check (Claude
Haiku 4.5) only for new listings, within its own daily limit. The Anthropic
key comes from systemd's credential (deploy/news-listings.service, see
deploy/LAUNCH_SERVER_SETUP.md, Part J); without it the rule-based checks run
alone.

Recording only (screener/listing_track.py): listing_track.csv has a row for
every listing signal, bought or not, with CoinGecko's price at detection and
about 1, 5, 15 and 60 minutes and 6 hours later. Those later prices are one
CoinGecko markets call per run with a checkpoint due (none when the coin was
priced anyway), in the same monthly count; nothing reads the file to decide
anything.

PAPER TRADING ONLY. It only READS public data with GET requests (and asks
Anthropic's API about headlines). It never connects a wallet, never uses a
private key, never signs or sends anything.
"""

import argparse
import json
import logging
import os
import signal
import sys
import tempfile
from datetime import datetime, timedelta
from urllib.parse import urlparse

from screener.api import ApiError
from screener.autorestart import CodeWatcher, forever
from screener.news import CoinGecko, FastNewsTrader, NewsHttp, NewsStrategy
from screener.news_ai import api_key
from screener.btc import BtcTrend
from screener.listing_track import KEEP_CALLS, ListingTrack
from screener.paper_trader import PaperTrader, now_utc
from screener.settings import HERE, load_config

log = logging.getLogger("news_listings")
HOURS_KEPT = 48            # call counts per hour kept in health.json
# listing_track.csv (screener/listing_track.py): recording only; the tests turn
# it off to count the trading's own requests.
TRACK_LISTINGS = True
# The config.toml sections the bot reads: only changes there restart it.
CONFIG_SECTIONS = ("news", "news_listings", "api", "files")


def listings_config(cfg):
    """The news strategy's settings, with the listings bot's own timing and
    limits: checks every run, prices every prices_every_minutes, its own
    CoinGecko and AI counts, and its buy slippage. The checks, costs and
    exits are unchanged."""
    c, own = cfg["news"], cfg["news_listings"]
    news = dict(c, every_minutes=0, prices_every_minutes=own["prices_every_minutes"],
                coingecko_monthly_calls=own["coingecko_monthly_calls"])
    if own.get("buy_slippage_pct"):
        # Its paper buys pay this much over the market price (reaction time).
        news["paper_trading"] = dict(c["paper_trading"],
                                     buy_slippage_pct=own["buy_slippage_pct"])
    if c.get("ai"):
        news["ai"] = dict(c["ai"], daily_limit=own["ai_daily_limit"])
    return dict(cfg, news=news)


def secret(name, env):
    """A key from systemd's credentials (LoadCredential= in the .service
    file: a file only this service can read), or else from the environment
    (for a test by hand). None when there's none."""
    folder = os.environ.get("CREDENTIALS_DIRECTORY")
    if folder:
        try:
            with open(os.path.join(folder, name)) as fh:
                value = fh.read().strip()
            if value:
                return value
        except OSError:
            pass
    return os.environ.get(env) or None


class CountingHttp:
    """The read-only NewsHttp, counting requests per site (for the health
    row: shows it stays within the free limits)."""

    def __init__(self, http):
        self.http = http
        self.calls = {}

    def _count(self, url):
        host = urlparse(url).netloc.removeprefix("www.").removeprefix("api.")
        self.calls[host] = self.calls.get(host, 0) + 1

    def text(self, url, headers=None):
        self._count(url)
        return self.http.text(url, headers) if headers else self.http.text(url)

    def json(self, url, headers=None):
        self._count(url)
        return self.http.json(url, headers)


class NewsListings:
    def __init__(self, cfg, data_folder, http, coingecko_key=None, ai_key=None, ai_client=None):
        self.cfg = listings_config(cfg)
        self.own = cfg["news_listings"]
        self.data_folder = data_folder
        self.folder = os.path.join(data_folder, self.own["folder"])
        self.http = CountingHttp(http)
        self.coingecko_key, self.ai_key, self.ai_client = coingecko_key, ai_key, ai_client

    def fast_trader(self):
        """news (listings) fast's trader, or None when it's turned off."""
        fast = self.own.get("fast") or {}
        if not fast.get("enabled"):
            return None
        return FastNewsTrader(fast["paper_trading"], os.path.join(self.folder, fast["folder"]))

    def strategy(self, fast=None):
        return NewsStrategy(self.cfg, self.data_folder, self.http, self.coingecko_key,
                            self.ai_key, self.ai_client, folder=self.own["folder"],
                            runs_on="server", followers=[fast] if fast else [])

    def run_once(self, now=None, out=print):
        """One run: the news strategy's fetch (read everything, change
        nothing), then apply (log, sell, buy, save)."""
        now = now or now_utc()
        before = dict(self.http.calls)
        os.makedirs(self.folder, exist_ok=True)
        fast = self.fast_trader()
        news = self.strategy(fast)
        try:
            plan = news.fetch(now=now)
        except ApiError as exc:
            self._health(now, before, str(exc), news)
            out(f"{now:%H:%M} skipped, nothing changed: {exc}")
            return None
        lines = []
        bought = news.apply(plan, None, lines.append)
        if fast is not None:
            self._fast_exits(fast, news, plan, now, lines.append)
        # No GitHub issues from the server: forget the ones apply() queues.
        if news.trader.state.pop("issues_to_close", None) is not None:
            news.trader.save()
        if TRACK_LISTINGS:
            self._track_listings(news, plan, bought, now, lines.append)
        self._health(now, before, None, news)
        sources = plan["sources"]
        working = sum(1 for s in sources if s.get("ok"))
        fresh = sum(s.get("new", 0) for s in sources)
        t = news.trader
        summary = (f"{now:%H:%M} {working}/{len(sources)} source(s) ok, {fresh} new item(s); "
                   f"{len(t.open_positions)} open; P&L ${t.state['running_total_pnl_usd']:+.2f}")
        # The full report only when something happened: a new item, a sell,
        # a failing source or a note (else one line a minute).
        busy = (fresh or plan["notes"] or working < len(sources)
                or any(line.lstrip().startswith(("SELL", "BUY")) for line in lines))
        out(summary + ("".join(f"\n  {line}" for line in lines if line.strip()) if busy else ""))
        return bought

    def _track_listings(self, news, plan, bought, now, out):
        """data/news-listings/listing_track.csv: a row for every listing signal
        (bought or not) with CoinGecko's price at detection, and the price
        about 1, 5, 15 and 60 minutes and 6 hours later. Recording only, after
        the trading is saved: any failure here is noted and nothing else
        changes. The later prices come from one CoinGecko markets call per run
        with a checkpoint due (the same call and monthly count as the open
        positions' prices; coins this run already priced cost no call)."""
        try:
            track = ListingTrack(self.folder)
            owned = {p["address"] for p in bought}
            new = []
            for cand in plan["candidates"]:
                source, item = cand["source"], cand["item"]
                if source.get("kind") != "exchange":
                    continue
                coin = cand["coins"][0] if len(cand["coins"]) == 1 else None
                passed = all(ch.status == "PASS" for ch in cand["checks"])
                new.append(track.signal_row(now, source, item, cand["coins"], passed,
                                            bool(coin) and coin["id"] in owned,
                                            plan.get("fetched_at")))
            for source, item in plan.get("unmatched", []):
                if source.get("kind") == "exchange":
                    new.append(track.signal_row(now, source, item, [], False, False, None))
            track.add(new)
            due = track.due(now)
            if not due:
                return
            prices = {i: plan["prices"][i] for i in due if plan["prices"].get(i)}
            fetched = dict.fromkeys(prices, plan.get("fetched_at") or now)
            want = [i for i in due if i not in prices]
            if want:
                gecko = CoinGecko(self.http, self.coingecko_key, news.trader.state,
                                  self.cfg["news"]["coingecko_monthly_calls"], now)
                if gecko.left() > KEEP_CALLS:
                    try:
                        got = {x["id"]: x["price"] for x in gecko.markets(ids=want)
                               if x.get("price")}
                        prices.update(got)
                        fetched.update(dict.fromkeys(got, now_utc()))
                    except ApiError as exc:
                        out(f"  (listing track: no prices this run: {exc})")
                    news.trader.save()                 # the CoinGecko count
            if prices:
                track.fill({i: due[i] for i in due if i in prices}, prices, fetched)
        except Exception as exc:              # recording must never stop the bot
            out(f"  (listing track: skipped this run: {exc})")

    def _fast_exits(self, fast, news, plan, now, out):
        """news (listings) fast's exits: its open positions' prices every
        [news_listings.fast] prices_every_minutes (this run's prices for
        news (listings) are reused; the rest from CoinGecko, in news
        (listings)' monthly count), then its sells. A position past its time
        limit with no new price closes at its last known price."""
        # (not the ones just bought: their price is this moment's)
        held = [p["address"] for p in fast.open_positions if p["entry_time"] != now.isoformat()]
        last = fast.state.get("last_prices")
        every = timedelta(minutes=self.own["fast"]["prices_every_minutes"] - 0.5)
        if held and (not last or now - datetime.fromisoformat(last) >= every):
            prices = {i: plan["prices"][i] for i in held if plan["prices"].get(i)}
            fetched = {i: plan.get("fetched_at") or now for i in prices}
            want = [i for i in held if i not in prices]
            if want:
                gecko = CoinGecko(self.http, self.coingecko_key, news.trader.state,
                                  self.cfg["news"]["coingecko_monthly_calls"], now)
                try:
                    got = {x["id"]: x["price"] for x in gecko.markets(ids=want) if x.get("price")}
                    prices.update(got)
                    fetched.update(dict.fromkeys(got, now_utc()))
                except ApiError as exc:
                    out(f"  (news (listings) fast: no prices this run: {exc})")
                news.trader.save()                 # the CoinGecko count
            fast.state["last_prices"] = now.isoformat()
            limit = fast.cfg["max_hold_hours"]
            for p in fast.open_positions:
                age = (now - datetime.fromisoformat(p["entry_time"])).total_seconds() / 3600
                if p["address"] not in prices and age >= limit:
                    # No fresh price: closed at the last one (its sell says so).
                    prices[p["address"]] = p["last_price"]
                    fetched[p["address"]] = p.get("last_price_time") or ""
                    p["stale_price_from"] = p.get("last_price_time") or "an earlier run"
            for s in fast.update(prices, when=now, fetched_at=fetched):
                out(f"  SELL {s['symbol']:<10} {'(fast) ' + s['reason']:<45} "
                    f"P&L ${s['pnl_usd']:+.2f}")
        fast.save()

    def _health(self, now, before, error, news):
        """data/news-listings/health.json: the last good run, the last
        error, and requests per site per hour (pushed with the results)."""
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
        row = calls.setdefault(hour, {"runs": 0})
        row["runs"] += 1
        for site, n in self.http.calls.items():
            if n - before.get(site, 0):
                row[site] = row.get(site, 0) + n - before.get(site, 0)
        for old in sorted(calls)[:-HOURS_KEPT]:
            calls.pop(old)
        data["ai_key"] = bool(self.ai_key or self.ai_client)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="one run against the real sites in a temporary folder "
                             "(nothing is saved; the market lists are only read, so no "
                             "listing is found)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config()
    if not cfg.get("news_listings", {}).get("enabled"):
        print("The news listings bot is turned off ([news_listings] enabled = false).")
        return 0
    http = NewsHttp(cfg["api"]["timeout_seconds"])
    coingecko_key = secret("coingecko_api_key", "COINGECKO_API_KEY")
    # Bitcoin's trend in every paper buy's entries.csv row (logging only).
    PaperTrader.market = BtcTrend(coingecko_key or "")
    ai_key = api_key()
    print(f"AI check: {'on' if ai_key else 'off (no Claude API key: rule-based checks only)'}",
          flush=True)
    if args.test:
        with tempfile.TemporaryDirectory() as folder:
            print("Test run: real data, results in a temporary folder (nothing is saved).")
            NewsListings(cfg, folder, http, coingecko_key, ai_key).run_once(
                out=lambda s: print(s, flush=True))
        return 0
    bot = NewsListings(cfg, os.path.join(HERE, cfg["files"]["data_folder"]), http,
                       coingecko_key, ai_key)
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

    names = ", ".join(s["name"] for s in bot.strategy().sources)
    print(f"news (listings): paper trading every {cfg['news_listings']['every_seconds']} s "
          f"into {bot.folder}; sources: {names}", flush=True)
    watcher = CodeWatcher(HERE, CONFIG_SECTIONS)
    log.info("watching %d code file(s) and config.toml %s for updates",
             len(watcher.files), ", ".join(f"[{s}]" for s in CONFIG_SECTIONS))
    if forever(Guarded(), cfg["news_listings"]["every_seconds"],
               out=lambda s: print(s, flush=True), stop=lambda: bool(stopping), watcher=watcher,
               logger=log):
        log.info("stopped; everything saved; systemd starts the new code in about 10 s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
