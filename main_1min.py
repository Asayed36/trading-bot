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
deploy/push_results.sh pushes data/main-1min to GitHub once an hour. When
that push brings new code the bot uses, it exits by itself between two runs
(everything is saved after each run) and systemd starts it again with the
new code (screener/autorestart.py; "automatic restart" in
journalctl -u main-1min).

Paper versions ([[main_1min.versions]]) run inside the same bot, on the same
data each minute: main's checks plus extra rules (A: 3 consecutive passing
minutes; B: not up more than 100% in the last hour and a Jupiter organic
score of 60+; C: B's rules, decided once at the minute a token first passes
main's checks), the same exits and costs, and their own files in
data/main-1min/<a, b, c>/. With [main_1min] stopped = true, main (1 min)
buys nothing of its own; its checks still run for the versions. A version
with stopped = true buys nothing new.

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

Recording only (screener/token_record.py): candidates.csv has a row for every
token the first time it is checked (bought or skipped, with the failed checks
and what A, B and C decided) and its price, market cap and liquidity 1, 6 and
24 hours later, from DexScreener's free batched call (30 tokens a request, at
most one call every 4 minutes, only when a price is due); entries.csv has
extra RugCheck / DexScreener columns; creator_ledger.json remembers creators'
launches. Nothing reads them to decide anything.

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
from datetime import timedelta

from screener.api import ApiError, PublicApi, RateLimited, Unavailable
from screener.autorestart import CodeWatcher
from screener.autorestart import forever as run_forever
from screener.backdrop import MarketBackdrop
from screener.btc import BtcTrend
from screener.filters import (PASS, best_pair, current_prices, evaluate, find_candidates,
                              market_checks, to_float)
from screener.jupiter import ERROR as JUPITER_ERROR
from screener.jupiter import JupiterOrganic
from screener.liquid import LiquidTrader, LiquidVersion, entry_problem
from screener.paper_trader import PaperTrader, now_utc
from screener.settings import HERE, load_config
from screener.token_record import CandidateLog, CreatorLedger, reprice

log = logging.getLogger("main_1min")
HOURS_KEPT = 48            # call counts per hour kept in health.json
DEXSCREENER_RETRY_SECONDS = 2   # wait before the one retry of a DexScreener 5xx / timeout
# The config.toml sections the bot reads: only changes there restart it.
CONFIG_SECTIONS = ("filters", "paper_trading", "main_1min", "liquid", "api", "files")


class SafeTrader(PaperTrader):
    """Main's PaperTrader (the same exits and costs), saving positions.json
    in one step so the hourly push never sees a half-written file."""

    def save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.state, fh, indent=2)
        os.replace(tmp, self.state_path)


class LiquidSafeTrader(LiquidTrader, SafeTrader):
    """A "liquid" version's trader (screener/liquid.py): SafeTrader's saving and buying
    with the liquid exits."""


class CountingApi:
    """The read-only PublicApi, counting requests per site (for the health
    row: shows it stays within the free limits). A DexScreener call that gets
    a 5xx answer or no answer is tried once more after DEXSCREENER_RETRY_SECONDS
    ("dexscreener retries" in health.json); if that fails too, it is logged once,
    counted ("dexscreener skipped") and raised as Unavailable, which the caller
    skips for this minute."""

    def __init__(self, api, sleep=time.sleep):
        self.api = api
        self.sleep = sleep
        self.calls = {"dexscreener": 0, "rugcheck": 0, "jupiter": 0}

    def _count(self, key, n=1):
        self.calls[key] = self.calls.get(key, 0) + n

    def _dexscreener(self, name, requests, call, *args):
        """`call(*args)`, which makes `requests` requests, with one retry."""
        self._count("dexscreener", requests)
        try:
            return call(*args)
        except Unavailable as first:
            self._count("dexscreener retries")
            self.sleep(DEXSCREENER_RETRY_SECONDS)
            self._count("dexscreener", requests)
            try:
                return call(*args)
            except Unavailable as exc:
                self._count("dexscreener skipped")
                log.warning("DexScreener %s skipped this minute (%s; again after %ss: %s)",
                            name, str(first)[:100], DEXSCREENER_RETRY_SECONDS, str(exc)[:100])
                raise

    def latest_profiles(self):
        return self._dexscreener("profiles", 1, self.api.latest_profiles)

    def latest_boosts(self):
        return self._dexscreener("boosts", 1, self.api.latest_boosts)

    def pairs_for_tokens(self, addresses):
        addresses = list(addresses)
        return self._dexscreener("pairs", (len(addresses) + 29) // 30,
                                 self.api.pairs_for_tokens, addresses)

    def rugcheck_report(self, address):
        self._count("rugcheck")
        return self.api.rugcheck_report(address)


class Version:
    """One paper version of main (1 min) ([[main_1min.versions]]): the same
    data each minute and the same exits and costs ([paper_trading]), with
    extra entry rules and its own files."""

    def __init__(self, v, data_folder):
        self.name = v["name"]
        self.label = v.get("label") or f"main (1 min) {self.name}"
        self.folder = os.path.join(data_folder, v["folder"])
        # A: buy only on the Nth consecutive minute a token passes.
        self.passes = int(v.get("consecutive_passes", 1))
        # B: skip tokens up more than this in the last hour...
        self.max_change_1h = v.get("max_change_1h_pct")
        # ...and require at least this Jupiter organic score.
        self.min_organic = v.get("min_organic_score")
        # C: decide once, at the minute a token first passes main's checks
        # (buy or skip for good); never wait for it to change.
        self.first_pass_only = bool(v.get("first_pass_only"))
        # stopped = true: no new buys; open positions finish under the exits.
        self.stopped = bool(v.get("stopped"))
        # Paper buys pay this much over the market price (reaction time).
        self.buy_slippage_pct = float(v.get("buy_slippage_pct") or 0)

    def why_not(self, result, streak, organic):
        """None when this version buys the token (it passed main's checks);
        otherwise why not, for the hourly counts."""
        if streak < self.passes:
            return f"{streak} of {self.passes} passes"
        if self.max_change_1h is not None:
            change = to_float(((result.pair or {}).get("priceChange") or {}).get("h1"))
            if change is None:
                return "no 1h change"
            if change > self.max_change_1h:
                return f"up >{self.max_change_1h:g}% in 1h"
        if self.min_organic is not None:
            values = organic(result.address)
            if values.get(JUPITER_ERROR):
                return NO_JUPITER_ANSWER
            score = to_float(values.get("jupiter_organic_score"))
            if score is None:
                return "no organic score"
            if score < self.min_organic:
                return f"organic score <{self.min_organic:g}"
        return None


# Version.why_not when Jupiter didn't answer: C waits for an answer before
# deciding; B skips the token this minute (as before).
NO_JUPITER_ANSWER = "no Jupiter answer"


class MainOneMinute:
    def __init__(self, cfg, data_folder, api, jupiter=None):
        self.cfg = cfg
        self.c, self.f, self.pt = cfg["main_1min"], cfg["filters"], cfg["paper_trading"]
        self.folder = os.path.join(data_folder, self.c["folder"])
        self.api = CountingApi(api)
        self.jupiter = jupiter
        self.reports = {}          # token -> (when, RugCheck report): memory only
        self.rugcheck_paused_until = None
        self.versions = [Version(v, data_folder) for v in self.c.get("versions", [])
                         if v.get("enabled", True)]
        # The "liquid" paper strategy ([liquid]): bought at a token's first check when
        # its pool is liquid enough, four sets of exits (screener/liquid.py).
        lc = cfg.get("liquid") or {}
        self.liquid_cfg = lc
        self.liquid = [LiquidVersion(lc, v, data_folder, self.pt["buy_amount_usd"])
                       for v in lc.get("versions", []) if lc.get("enabled") and v.get("enabled", True)]
        # Consecutive minutes each token has passed main's checks (memory
        # only: a restart starts the counts again).
        self.streaks = {}
        self.organic_cache = {}    # token -> (when, Jupiter's values)
        self.now = None
        # Recording only (screener/token_record.py): candidates.csv, a row for
        # every token the first time it's checked (bought or not) and its
        # price 1, 6 and 24 hours later; and the creator ledger.
        self.candidates = CandidateLog(self.folder, "main (1 min)")
        self.ledger = CreatorLedger(os.path.join(self.folder, "creator_ledger.json"),
                                    os.path.join(data_folder, "early", "positions.json"))
        self.last_reprice = None

    @staticmethod
    def _optional(call, *args):
        """(answer, None), or (None, the error) when DexScreener was unavailable (5xx or
        timeout) even after CountingApi's retry. Any other error is raised, as before."""
        try:
            return call(*args), None
        except Unavailable as exc:
            return None, exc

    def organic(self, address):
        """Jupiter's organic score values, read at most every
        organic_cache_minutes per token (version B's check and every buy's
        entries.csv row share them)."""
        if not self.jupiter:
            return {}
        known = self.organic_cache.get(address)
        if known and self.now - known[0] < timedelta(minutes=self.c["organic_cache_minutes"]):
            return known[1]
        self.api.calls["jupiter"] += 1
        values = self.jupiter(address) or {}
        self.organic_cache[address] = (self.now, values)
        return values

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
        self.now = now
        # Forget reports and organic scores nobody will reuse.
        fresh = timedelta(minutes=self.c["rugcheck_recheck_minutes"])
        self.reports = {a: r for a, r in self.reports.items() if now - r[0] < fresh}
        keep = timedelta(minutes=self.c.get("organic_cache_minutes", 10))
        self.organic_cache = {a: v for a, v in self.organic_cache.items() if now - v[0] < keep}
        before = dict(self.api.calls)
        try:
            trader = SafeTrader(self.pt, self.folder)
            trader.organic = self.organic if self.jupiter else None
            trader.ledger = self.ledger
            # [main_1min] stopped = true: main (1 min) buys nothing of its
            # own; its checks still run every minute for the versions.
            trader.buying = not self.c.get("stopped")
            vtraders = {}
            for v in self.versions:
                pt = dict(self.pt, buy_slippage_pct=v.buy_slippage_pct) \
                    if v.buy_slippage_pct else self.pt
                vtraders[v.name] = SafeTrader(pt, v.folder)
                vtraders[v.name].organic = trader.organic
                vtraders[v.name].ledger = self.ledger
                vtraders[v.name].buying = not v.stopped
            ltraders = {}
            for lv in self.liquid:
                ltraders[lv.name] = LiquidSafeTrader(lv.cfg, lv.folder)
                ltraders[lv.name].ledger = self.ledger
                ltraders[lv.name].buying = not lv.stopped
            held, seen = [], set()
            for t in [trader, *vtraders.values(), *ltraders.values()]:
                for pos in t.open_positions:
                    if pos["address"] not in seen:
                        seen.add(pos["address"])
                        held.append(pos)
            # A DexScreener call that still fails after its one retry (a 5xx or a timeout)
            # is skipped for this minute alone: positions keep their last price, a missing
            # list adds no candidates. Nothing is recorded from an answer that did not come.
            prices, _ = self._optional(current_prices, self.api, held, self.f["allowed_dexes"])
            prices = prices or {}
            prices_at = now_utc()          # when they were fetched (the journal says)
            profiles, failed_profiles = self._optional(self.api.latest_profiles)
            boosts, failed_boosts = self._optional(self.api.latest_boosts)
            if failed_profiles and failed_boosts:
                raise failed_profiles      # no list at all: the run is skipped, as before
            addresses = find_candidates(profiles or [], boosts or [])
            # Version A also re-checks the tokens on a run of passes that
            # have dropped off DexScreener's lists, after the listed ones (so
            # main (1 min) keeps its RugCheck budget). Only A uses them.
            listed = set(addresses)
            watched = [a for a in self.streaks if a not in listed]
            to_check = addresses + watched
            pairs, failed_pairs = self._optional(self.api.pairs_for_tokens, to_check) \
                if to_check else ([], None)
            if failed_pairs:
                to_check = []              # without their pairs nothing can be checked or recorded
            pairs_at = now_utc()           # the buys' prices
            budget = {"rugcheck": self.c["rugcheck_max_per_run"]}
            results, waiting = [], 0
            for addr in to_check:
                pair = best_pair(pairs, addr, self.f["allowed_dexes"])
                market_ok = all(c.status == PASS for c in market_checks(pair, self.f))
                skip = self.cfg["api"]["skip_safety_if_market_fails"] and not market_ok
                report = None
                if not skip:
                    got = self._report(addr, now, budget)
                    if got is None:
                        waiting += addr in listed     # checked in a later minute
                        continue
                    report = got[0]
                results.append(evaluate(addr, pair, report, self.f, safety_skipped=skip))
        except ApiError as exc:
            self._health(now, before, str(exc))
            out(f"{now:%H:%M} skipped, nothing changed: {exc}")
            return None

        # Runs of consecutive passes: a token checked this minute that
        # failed, or wasn't checked (off the lists, waiting for RugCheck),
        # starts again from zero.
        self.streaks = {r.address: self.streaks.get(r.address, 0) + 1
                        for r in results if r.passed}
        main_results = [r for r in results if r.address in listed]

        lines, counts = [], {}
        decisions = {}             # token -> {version: what it decided} (candidates.csv)
        main_before = list(trader.state.get("ever_bought", []))   # before this minute's buys
        for s in trader.update(prices, when=now, fetched_at=prices_at):
            lines.append(f"SELL {s['symbol']} {s['reason']} P&L ${s['pnl_usd']:+.2f}")
        for r in main_results:
            bought = r.passed and trader.buy(r, when=now, fetched_at=pairs_at)
            decisions[r.address] = {"main": "bought" if bought else (
                "failed main's checks" if not r.passed else
                "passed, not bought (stopped)" if not trader.buying else
                "passed, not bought (held or bought before)")}
            if bought:
                lines.append(f"BUY  {r.symbol} ${self.pt['buy_amount_usd']} at ${r.price:.10g}")
        trader.save()
        for v in self.versions:
            vt = vtraders[v.name]
            for s in vt.update(prices, when=now, fetched_at=prices_at):
                lines.append(f"[{v.name}] SELL {s['symbol']} {s['reason']} "
                             f"P&L ${s['pnl_usd']:+.2f}")
            if v.first_pass_only:
                self._first_pass(v, vt, main_before, main_results, now, counts, lines, pairs_at,
                                 decisions)
                vt.save()
                continue
            for r in (results if v.passes > 1 else main_results):
                if not r.passed or not vt.can_buy(r.address):
                    continue
                why = v.why_not(r, self.streaks.get(r.address, 0), self.organic)
                decisions.setdefault(r.address, {})[v.name] = f"skipped ({why})" if why \
                    else "bought"
                if why:
                    key = f"{v.name} waiting" if why.endswith("passes") else f"{v.name} skipped"
                    counts[key] = counts.get(key, 0) + 1
                    continue
                if vt.buy(r, when=now, fetched_at=pairs_at):
                    counts[f"{v.name} buys"] = counts.get(f"{v.name} buys", 0) + 1
                    lines.append(f"[{v.name}] BUY  {r.symbol} ${self.pt['buy_amount_usd']} at "
                                 f"${r.price:.10g}")
            vt.save()
        try:
            self._liquid(ltraders, main_results, prices, now, prices_at, pairs_at, counts, lines)
        except Exception:
            # An error in the liquid strategy must never stop the rest of the minute
            # (candidates.csv, the other versions, the health file).
            log.exception("liquid step failed this minute; the rest of the run continues")
            counts["liquid errors"] = counts.get("liquid errors", 0) + 1
            for lt in ltraders.values():       # keep whatever was recorded so far
                try:
                    lt.save()
                except Exception:
                    log.exception("liquid state could not be saved")
        self._record(main_results, decisions, now)
        # Only tokens a run-of-passes version could still buy are watched.
        self.streaks = {a: n for a, n in self.streaks.items()
                        if any(vtraders[v.name].can_buy(a) for v in self.versions
                               if v.passes > 1)}
        passed = sum(r.passed for r in main_results)
        note = f", {waiting} waiting for RugCheck" if waiting else ""
        self._health(now, before, None, counts, vtraders, ltraders)
        extra = "".join(f"; {v.name}: {len(vtraders[v.name].open_positions)} open, "
                        f"P&L ${vtraders[v.name].state['running_total_pnl_usd']:+.2f}"
                        for v in self.versions)
        extra += "".join(f"; {v.name}: {len(ltraders[v.name].open_positions)} open, "
                         f"P&L ${ltraders[v.name].state['running_total_pnl_usd']:+.2f}"
                         for v in self.liquid)
        out(f"{now:%H:%M} {len(addresses)} candidate(s), {len(main_results)} checked, {passed} "
            f"passed{note}; {len(trader.open_positions)} open; "
            f"P&L ${trader.state['running_total_pnl_usd']:+.2f}{extra}"
            + "".join(f"\n  {line}" for line in lines))
        return main_results

    def _liquid(self, ltraders, main_results, prices, now, prices_at, pairs_at, counts, lines):
        """The liquid strategy: every version's exits on the open positions, then a paper
        buy in every version for each token whose first check is this minute (no row for it
        in candidates.csv yet; _record writes it after this) when its liquidity is at least
        min_liquidity_usd. Runs before _record, so "first check" is the same moment."""
        if not self.liquid:
            return
        minimum = self.liquid_cfg["min_liquidity_usd"]
        for lv in self.liquid:
            for s in ltraders[lv.name].update(prices, when=now, fetched_at=prices_at):
                lines.append(f"[{lv.name}] SELL {s['symbol']} {s['reason']} "
                             f"P&L ${s['pnl_usd']:+.2f}")
        try:
            first = [r for r in main_results if r.address not in self.candidates.seen()]
        except Exception as exc:           # the candidate log can't be read: buy nothing
            log.info("liquid buys skipped this minute: %s", exc)
            return
        for r in first:
            why = entry_problem(r, now, minimum)
            if why:
                counts["liquid skipped"] = counts.get("liquid skipped", 0) + 1
                continue
            for lv in self.liquid:
                if ltraders[lv.name].buy(r, when=now, fetched_at=pairs_at):
                    counts[f"{lv.name} buys"] = counts.get(f"{lv.name} buys", 0) + 1
                    lines.append(f"[{lv.name}] BUY  {r.symbol} ${self.pt['buy_amount_usd']} at "
                                 f"${r.price:.10g}")
        for lv in self.liquid:
            ltraders[lv.name].save()

    def _record(self, main_results, decisions, now):
        """candidates.csv: a row for every token checked for the first time
        this minute, then the later prices that are due (DexScreener's free
        batched call, at most every 4 minutes). Recording only: a failure here
        is logged and changes nothing."""
        try:
            for r in main_results:
                if r.address in self.candidates.seen():
                    continue
                known = decisions.get(r.address, {})
                for v in self.versions:
                    known.setdefault(v.name, "not considered (failed main's checks)"
                                     if not r.passed else "not bought")
                report = (self.reports.get(r.address) or (None, None))[1]
                self.candidates.add(
                    r, report, r.record, now, "PASS" if r.passed else "FAIL",
                    "; ".join(f"{c.name}: {c.detail}" for c in r.checks if c.status == "FAIL"),
                    not any(c.status == "SKIP" for c in r.checks),
                    "; ".join(f"{k}={v}" for k, v in known.items()), self.ledger)
            if self.last_reprice is None or now - self.last_reprice >= timedelta(minutes=4):
                self.last_reprice = now
                reprice(self.candidates, self.api, now, self.f["allowed_dexes"], self.ledger)
            self.ledger.save()
        except Exception as exc:          # includes ApiError / RateLimited
            log.info("candidate record skipped this minute: %s", exc)

    def _first_pass(self, v, vt, main_before, main_results, now, counts, lines, pairs_at=None,
                    decisions=None):
        """Version C: each token is decided once, at the first minute it
        passes main's checks: bought if its extra rules pass then, else
        skipped for good. A token waiting for Jupiter's answer (Jupiter
        didn't answer) isn't decided yet: it's decided at the first minute
        it passes with an answer. Decided tokens are kept in its
        positions.json ("decided", token -> when; "skipped", token -> when,
        symbol and why), so a restart doesn't give a token a second chance.
        On its first run, the tokens main (1 min) had already passed (and
        bought) count as decided: their first pass was earlier."""
        if "decided" not in vt.state:
            vt.state["decided"] = {a: "before C started" for a in main_before}
        decided = vt.state["decided"]
        skipped = vt.state.setdefault("skipped", {})
        for r in main_results:
            if not r.passed or r.address in decided or not vt.buying:
                continue
            why = v.why_not(r, 1, self.organic)
            if decisions is not None:
                decisions.setdefault(r.address, {})[v.name] = (
                    "waiting for Jupiter" if why == NO_JUPITER_ANSWER
                    else f"skipped ({why})" if why else "bought")
            if why == NO_JUPITER_ANSWER:
                counts[f"{v.name} waiting for Jupiter"] = \
                    counts.get(f"{v.name} waiting for Jupiter", 0) + 1
                continue
            decided[r.address] = now.isoformat()
            if why:
                counts[f"{v.name} skipped"] = counts.get(f"{v.name} skipped", 0) + 1
                skipped[r.address] = {"time": now.isoformat(), "symbol": r.symbol,
                                      "reason": why}
                continue
            if vt.buy(r, when=now, fetched_at=pairs_at):
                counts[f"{v.name} buys"] = counts.get(f"{v.name} buys", 0) + 1
                lines.append(f"[{v.name}] BUY  {r.symbol} ${self.pt['buy_amount_usd']} at "
                             f"${r.price:.10g}")
        # Forget decisions older than 14 days (a token that passes again
        # after that is a new first pass).
        cutoff = (now - timedelta(days=14)).isoformat()
        vt.state["decided"] = {a: t for a, t in decided.items()
                               if not t[:1].isdigit() or t >= cutoff}
        vt.state["skipped"] = {a: x for a, x in skipped.items() if x["time"] >= cutoff}

    def _health(self, now, before, error, counts=None, vtraders=None, ltraders=None):
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
        # Each version's buys, and tokens it passed on this hour (waiting
        # for more passes, or skipped by its extra rules).
        for key, n in (counts or {}).items():
            row[key] = row.get(key, 0) + n
        if vtraders is not None:
            data["versions"] = {
                v.name: {"label": v.label, "open": len(vtraders[v.name].open_positions),
                         "watching": sum(1 for a in self.streaks if v.passes > 1
                                         and vtraders[v.name].can_buy(a)),
                         **({"decided": len(vtraders[v.name].state.get("decided", {}))}
                            if v.first_pass_only else {}),
                         **({"stopped": True} if v.stopped else {})}
                for v in self.versions}
        if ltraders:
            data.setdefault("versions", {}).update({
                v.name: {"label": v.label, "open": len(ltraders[v.name].open_positions),
                         **({"stopped": True} if v.stopped else {})}
                for v in self.liquid})
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


def forever(bot, every=60, **kw):
    """A run at the start of every minute (screener/autorestart.py), logged
    as main_1min."""
    kw.setdefault("logger", log)
    return run_forever(bot, every, **kw)


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
    api = PublicApi(cfg["api"]["timeout_seconds"], cfg["api"]["rugcheck_delay_seconds"],
                    dexscreener_attempts=1)    # CountingApi retries a DexScreener failure once
    # Bitcoin's trend in every paper buy's entries.csv row (logging only).
    PaperTrader.market = BtcTrend()
    # BTC/ETH/SOL moves from Binance's public data, no key (logging only).
    PaperTrader.backdrop = MarketBackdrop(
        None if args.test else os.path.join(HERE, cfg["files"]["data_folder"],
                                            "backdrop_cache.json"))
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
    watcher = CodeWatcher(HERE, CONFIG_SECTIONS)
    log.info("watching %d code file(s) and config.toml %s for updates",
             len(watcher.files), ", ".join(f"[{s}]" for s in CONFIG_SECTIONS))
    if forever(Guarded(), cfg["main_1min"]["every_seconds"],
               out=lambda s: print(s, flush=True), stop=lambda: bool(stopping), watcher=watcher):
        log.info("stopped; everything saved; systemd starts the new code in about 10 s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
