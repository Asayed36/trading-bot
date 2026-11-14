"""The "viral trigger" paper experiment, run inside the launch recorder (launch_record_bot.py,
in the launch-bot service). [viral] in config.toml.

PART 1, RECORDING (every launch the recorder sees, in data/viral/launches-YYYY-MM-DD.csv; no
column is added to any existing file):
  name_burst      how many other launches used the same normalized symbol in the previous
                  burst_window_minutes (30), and whether this token was the first of that
                  symbol in the last first_of_name_hours (24): "yes", "no", or "unknown" while
                  the name memory is younger than 24 hours (just after it started).
  watchlist_match the [[viral.watchlist]] entry the token's name or symbol matches, if any.
A token is FLAGGED (data/viral/flags-YYYY-MM-DD.csv, one row per token, by the day it was
flagged) when it matches the watchlist (at its creation), or when it was the first of its name
in 24 hours and min_followers (10) other launches with the same symbol followed within 30
minutes (at the moment the 10th one arrives).

PART 2, ONE PAPER VERSION (v1, [[viral.versions]]): a flagged token is checked on DexScreener
every check_every_seconds for watch_hours after it was flagged. At the first check where its
liquidity is at least min_liquidity_usd, each version buys buy_amount_usd at that check's price
plus buy_slippage_pct (never the same token twice). Exits like liquid l6: everything after
max_hold_minutes, or at -stop_loss_pct from the buy price, checked at every check with the same
DexScreener answer. Costs: round_trip_cost_pct over the whole trade. The version keeps its start
time in positions.json ("started_utc"); the daily comparison counts only trades after it.

FIXED RULES decided in advance: the numbers in [viral] are not tuned from results; a change is
a new version.

PAPER TRADING ONLY. It reads public data (the recorder's feed and DexScreener's free pairs
endpoint); it never uses a wallet, a key or a real order.
"""

import csv
import json
import logging
import os
import re
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from screener.filters import best_pair, to_float
from screener.liquid import LiquidTrader, LiquidVersion
from screener.paper_trader import PaperTrader
from screener.token_record import pair_facts

log = logging.getLogger("viral")

LAUNCH_COLUMNS = ["created_utc", "token_address", "symbol", "name", "symbol_key",
                  "same_symbol_prev_30m", "first_of_name_24h", "watchlist_entry",
                  "watchlist_category"]
FLAG_COLUMNS = ["flagged_utc", "token_address", "symbol", "name", "created_utc",
                "by_watchlist", "watchlist_entry", "watchlist_category",
                "by_name_burst", "name_burst_utc", "same_symbol_followers_30m",
                "watch_until_utc", "checks", "max_liquidity_usd", "reached_liquidity_utc",
                "bought_utc", "bought_by"]
ISO = "%Y-%m-%dT%H:%M:%SZ"
HOURS_KEPT = 26
STATE_SAVE_SECONDS = 600
MIN_TERM = 3                      # shorter watchlist terms would match far too much


def utc(t):
    return datetime.fromtimestamp(t, timezone.utc)


def iso(t):
    return utc(t).strftime(ISO) if t is not None else ""


def _fold(text):
    return unicodedata.normalize("NFKC", text or "").casefold()


def symbol_key(text):
    """The normalized symbol: letters and digits only, in lower case ("$Trump " -> "trump")."""
    return "".join(ch for ch in _fold(text) if ch.isalnum())


def words(text):
    """The words of a name, in lower case ("Donald Trump's Cat" -> donald, trump, s, cat)."""
    return re.findall(r"[^\W_]+", _fold(text))


class Watchlist:
    """[[viral.watchlist]]: name, category and terms. A token matches an entry when its
    normalized symbol equals a term's letters and digits ("TRUMP", "$trump"), or when a term's
    words appear as whole consecutive words in its name or symbol ("Trump Cat" matches "trump";
    "Strumpet" does not)."""

    def __init__(self, entries):
        self.entries = []
        self.by_key, self.sequences = {}, []
        for e in entries or []:
            terms = e.get("terms") or [e["name"]]
            entry = {"name": e["name"], "category": e.get("category", "")}
            for term in terms:
                key = symbol_key(term)
                if len(key) < MIN_TERM:
                    raise ValueError(f"viral watchlist term {term!r} is shorter than {MIN_TERM} "
                                     "letters")
                self.by_key.setdefault(key, entry)
                self.sequences.append((tuple(words(term)), entry))
            self.entries.append(entry)

    def match(self, name, symbol):
        entry = self.by_key.get(symbol_key(symbol))
        if entry:
            return entry
        for text in (name, symbol):
            have = words(text)
            for seq, entry in self.sequences:
                n = len(seq)
                if n and any(tuple(have[i:i + n]) == seq for i in range(len(have) - n + 1)):
                    return entry
        return None


class NameMemory:
    """When each normalized symbol was last launched (24 hours), the launches of the last
    burst window, and the open burst windows of tokens that were the first of their name."""

    def __init__(self, window_s, first_s, min_followers, since):
        self.window_s, self.first_s, self.min_followers = window_s, first_s, min_followers
        self.since = since                 # the memory is complete from this time on
        self.last_seen, self.recent, self.firsts = {}, {}, {}

    def observe(self, key, mint, symbol, name, t):
        """A new launch. Returns (same symbol in the previous window, first of its name in
        24 hours: "yes"/"no"/"unknown", the first-of-name entry this launch made reach
        min_followers or None, the open first-of-name entry it followed or None)."""
        recent = self.recent.setdefault(key, deque())
        while recent and recent[0] < t - self.window_s:
            recent.popleft()
        previous = len(recent)
        last = self.last_seen.get(key)
        if last is not None and t - last <= self.first_s:
            first = "no"
        elif t - self.since < self.first_s:
            first = "unknown"              # not 24 hours of memory yet
        else:
            first = "yes"
        burst = followed = None
        f = self.firsts.get(key)
        if f is not None and t - f["t"] <= self.window_s:
            f["followers"] += 1
            followed = f
            if f["followers"] == self.min_followers:
                burst = f
        elif f is not None:
            del self.firsts[key]
        if first == "yes":
            self.firsts[key] = {"mint": mint, "symbol": symbol, "name": name, "t": t,
                                "followers": 0}
        recent.append(t)
        self.last_seen[key] = t
        return previous, first, burst, followed

    def prune(self, t):
        self.last_seen = {k: v for k, v in self.last_seen.items() if t - v <= self.first_s}
        self.recent = {k: d for k, d in self.recent.items() if d and d[-1] >= t - self.window_s}
        self.firsts = {k: f for k, f in self.firsts.items() if t - f["t"] <= self.window_s}

    def to_state(self):
        return {"since": self.since, "last_seen": self.last_seen,
                "recent": {k: list(d) for k, d in self.recent.items()}, "firsts": self.firsts}

    def load(self, state, t):
        self.since = float(state.get("since", self.since))
        self.last_seen = {k: float(v) for k, v in (state.get("last_seen") or {}).items()}
        self.recent = {k: deque(float(x) for x in v) for k, v in (state.get("recent") or {}).items()}
        self.firsts = {k: dict(v) for k, v in (state.get("firsts") or {}).items()}
        self.prune(t)


class ViralTrader(LiquidTrader, PaperTrader):
    """A viral version's paper trader: PaperTrader's buying and costs, the liquid exits
    (screener/liquid.py: here only the stop loss and the time exit), saved in one step."""

    buy_reason = "viral flag and enough liquidity"

    def save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.state, fh, indent=2)
        os.replace(tmp, self.state_path)


@dataclass
class Check:
    """What a buy needs from a check (like screener.filters.Result)."""
    address: str
    symbol: str
    name: str
    pair: dict
    price: float
    insider: dict = None
    record: dict = None


class Viral:
    def __init__(self, cfg, data_folder, clock):
        self.cfg, self.c, self.clock = cfg, cfg["viral"], clock
        c = self.c
        self.folder = os.path.join(data_folder, c.get("folder", "viral"))
        os.makedirs(self.folder, exist_ok=True)
        self.allowed_dexes = cfg.get("filters", {}).get("allowed_dexes", [])
        self.watchlist = Watchlist(c.get("watchlist"))
        now = clock()
        self.memory = NameMemory(c["burst_window_minutes"] * 60, c["first_of_name_hours"] * 3600,
                                 c["min_followers"], now)
        self.flags = {}                    # token -> its flags row (recent days only)
        self.dirty_days = set()
        self.rows = []                     # launch rows waiting to be written
        self.hours = {}                    # "YYYY-MM-DDTHH" -> counters
        self.last_check_ok = None
        self.last_state_save = now
        self.versions = [LiquidVersion(c, dict(v, label=v.get("label") or f"viral {v['name']}"),
                                       data_folder, c["buy_amount_usd"])
                         for v in c.get("versions", []) if v.get("enabled", True)]
        self.traders = {}
        started = utc(now).replace(microsecond=0).isoformat()
        for v in self.versions:
            t = ViralTrader(v.cfg, v.folder)
            t.buying = not v.stopped
            t.state.setdefault("started_utc", started)     # kept for good: never back-filled
            self.traders[v.name] = t
        self._load(now)

    # ---- persistence ---------------------------------------------------

    def _path(self, name):
        return os.path.join(self.folder, name)

    def _load(self, now):
        try:
            with open(self._path("state.json")) as fh:
                self.memory.load(json.load(fh), now)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        try:
            with open(self._path("health.json")) as fh:
                self.hours = json.load(fh).get("hours") or {}
        except (OSError, ValueError, TypeError, AttributeError):
            self.hours = {}
        today = utc(now).date()
        for back in (1, 0):                       # the flags still watched: today and yesterday
            day = datetime.fromordinal(today.toordinal() - back).strftime("%Y-%m-%d")
            try:
                with open(self._path(f"flags-{day}.csv"), newline="") as fh:
                    for row in csv.DictReader(fh):
                        self.flags[row["token_address"]] = dict(row)
            except OSError:
                pass

    def save(self, now=None):
        """Write the launch rows, the flags of the days that changed, the traders, the health
        file, and the name memory (every STATE_SAVE_SECONDS)."""
        now = self.clock() if now is None else now
        self._write_launches()
        for day in sorted(self.dirty_days):
            rows = [r for r in self.flags.values() if r["flagged_utc"][:10] == day]
            path = self._path(f"flags-{day}.csv")
            with open(path + ".tmp", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FLAG_COLUMNS, extrasaction="ignore")
                w.writeheader()
                w.writerows(sorted(rows, key=lambda r: (r["flagged_utc"], r["token_address"])))
            os.replace(path + ".tmp", path)
        self.dirty_days.clear()
        for t in self.traders.values():
            t.save()
        if now - self.last_state_save >= STATE_SAVE_SECONDS:
            self.save_state(now)
        self._write_health(now)

    def save_state(self, now=None):
        now = self.clock() if now is None else now
        self.memory.prune(now)
        path = self._path("state.json")
        with open(path + ".tmp", "w") as fh:
            json.dump(self.memory.to_state(), fh, separators=(",", ":"))
        os.replace(path + ".tmp", path)
        self.last_state_save = now
        # flags older than the watch window and the day before are no longer needed in memory
        keep = utc(now - 2 * 86400).strftime("%Y-%m-%d")
        self.flags = {k: r for k, r in self.flags.items() if r["flagged_utc"][:10] >= keep}

    def _write_launches(self):
        by_day = {}
        for row in self.rows:
            by_day.setdefault(row[0][:10], []).append(row)
        self.rows = []
        for day, rows in by_day.items():
            path = self._path(f"launches-{day}.csv")
            new = not os.path.exists(path)
            with open(path, "a", newline="") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(LAUNCH_COLUMNS)
                w.writerows(rows)

    def _count(self, t, key, n=1):
        hour = self.hours.setdefault(utc(t).strftime("%Y-%m-%dT%H"), {})
        hour[key] = hour.get(key, 0) + n

    def _write_health(self, now):
        for old in sorted(self.hours)[:-HOURS_KEPT]:
            del self.hours[old]
        last_hour = [v for k, v in self.hours.items()
                     if k >= utc(now - 3600).strftime("%Y-%m-%dT%H")]
        data = {
            "updated": iso(now),
            "memory_since": iso(self.memory.since),
            "first_of_name_known": now - self.memory.since >= self.memory.first_s,
            "watched_now": len(self._watched(now)),
            "last_check_ok": iso(self.last_check_ok) if self.last_check_ok else None,
            "last_hour": {k: sum(h.get(k, 0) for h in last_hour)
                          for k in ("launches", "flags_watchlist", "flags_name_burst", "checks",
                                    "check_errors", "dexscreener", "buys")},
            "versions": {name: {"open": len(t.open_positions),
                                "started_utc": t.state.get("started_utc")}
                         for name, t in self.traders.items()},
            "hours": self.hours,
        }
        path = self._path("health.json")
        with open(path + ".tmp", "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(path + ".tmp", path)

    # ---- the launches (called by the recorder for every new launch) -----

    def on_launch(self, mint, name, symbol, t):
        """Recording only: one launch row, and a flag when it matches the watchlist or makes
        an earlier first-of-name token reach min_followers. Never raises."""
        try:
            key = symbol_key(symbol)
            previous, first, burst, followed = (self.memory.observe(key, mint, symbol, name, t)
                                                if key else (0, "unknown", None, None))
            entry = self.watchlist.match(name, symbol)
            clean = (name or "").replace("\n", " ").replace("\r", " ")[:64]
            self.rows.append([iso(t), mint, (symbol or "")[:32], clean, key, previous, first,
                              entry["name"] if entry else "", entry["category"] if entry else ""])
            self._count(t, "launches")
            if entry:
                self._flag(mint, symbol, name, t, t, watchlist=entry)
            if followed is not None and followed["mint"] in self.flags:
                row = self.flags[followed["mint"]]
                row["same_symbol_followers_30m"] = str(followed["followers"])
                self.dirty_days.add(row["flagged_utc"][:10])
            if burst is not None:
                self._flag(burst["mint"], burst["symbol"], burst["name"], burst["t"], t,
                           followers=burst["followers"])
        except Exception:
            log.exception("viral: launch %s not recorded", mint)

    def _flag(self, mint, symbol, name, created, t, watchlist=None, followers=None):
        row = self.flags.get(mint)
        if row is None:
            row = {k: "" for k in FLAG_COLUMNS}
            row.update(flagged_utc=iso(t), token_address=mint, symbol=(symbol or "")[:32],
                       name=(name or "").replace("\n", " ")[:64], created_utc=iso(created),
                       by_watchlist="no", by_name_burst="no", checks="0",
                       watch_until_utc=iso(t + self.c["watch_hours"] * 3600))
            self.flags[mint] = row
        if watchlist is not None and row["by_watchlist"] != "yes":
            row.update(by_watchlist="yes", watchlist_entry=watchlist["name"],
                       watchlist_category=watchlist["category"])
            self._count(t, "flags_watchlist")
        if followers is not None and row["by_name_burst"] != "yes":
            row.update(by_name_burst="yes", name_burst_utc=iso(t),
                       same_symbol_followers_30m=str(followers))
            self._count(t, "flags_name_burst")
        self.dirty_days.add(row["flagged_utc"][:10])

    # ---- the checks (launch_record_bot.py: every check_every_seconds) ---

    def _watched(self, now):
        """The flagged tokens still waiting for enough liquidity, newest first."""
        until = iso(now)
        rows = [r for r in self.flags.values()
                if not r["bought_utc"] and r["watch_until_utc"] > until]
        rows.sort(key=lambda r: r["flagged_utc"], reverse=True)
        return rows[:self.c["max_watched"]]

    def to_check(self, now):
        """The tokens to ask DexScreener about now: the watched flags and the open positions."""
        held = [p["address"] for t in self.traders.values() for p in t.open_positions]
        watched = [r["token_address"] for r in self._watched(now)]
        return list(dict.fromkeys(held + watched))

    def check_failed(self, now, error):
        self._count(now, "check_errors")
        log.warning("viral: DexScreener check skipped this time: %s", str(error)[:160])

    def apply(self, pairs, now, requests=0):
        """One DexScreener answer: every version's exits on its open positions, then a buy in
        every version for each watched token whose liquidity is at least min_liquidity_usd."""
        self.last_check_ok = now
        self._count(now, "checks")
        self._count(now, "dexscreener", requests)
        when = utc(now)
        for t in self.traders.values():
            prices = {}
            for pos in t.open_positions:
                pair = next((p for p in pairs if p.get("pairAddress") == pos.get("pair_address")),
                            None) or best_pair(pairs, pos["address"], self.allowed_dexes)
                price = to_float((pair or {}).get("priceUsd"))
                if price and price > 0:
                    prices[pos["address"]] = price
            for s in t.update(prices, when=when, fetched_at=when):
                log.info("viral: SELL %s %s P&L $%+.2f", s["symbol"], s["reason"], s["pnl_usd"])
        minimum = self.c["min_liquidity_usd"]
        for row in self._watched(now):
            mint = row["token_address"]
            pair = best_pair(pairs, mint, self.allowed_dexes)
            row["checks"] = str(int(row["checks"] or 0) + 1)
            self.dirty_days.add(row["flagged_utc"][:10])
            if pair is None:
                continue
            liquidity = pair_facts(pair, when)["liquidity_usd"]
            if liquidity is None:
                continue
            if liquidity > (to_float(row["max_liquidity_usd"]) or 0):
                row["max_liquidity_usd"] = f"{liquidity:.0f}"
            price = to_float(pair.get("priceUsd"))
            if liquidity < minimum or not price or price <= 0:
                continue
            if not row["reached_liquidity_utc"]:
                row["reached_liquidity_utc"] = iso(now)
            got = Check(mint, row["symbol"], row["name"], pair, price)
            bought = [name for name, t in self.traders.items()
                      if t.buy(got, when=when, fetched_at=when)]
            if bought:
                row.update(bought_utc=iso(now), bought_by=" ".join(bought))
                self._count(now, "buys", len(bought))
                log.info("viral: BUY %s at $%.10g (liquidity $%.0f; %s)", row["symbol"], price,
                         liquidity, ", ".join(bought))
