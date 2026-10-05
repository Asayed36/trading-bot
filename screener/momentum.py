"""The "momentum" paper strategy: buy a new pump.fun launch only when it
rises fast in its first minutes, on real buying.

It runs on your server (momentum_bot.py), fed by the Solana public RPC's
live pump.fun events (screener/pumpfeed.py: every trade, launch and
graduation; read-only, no key, no wallet). PAPER trading only.

Every launch seen being created is followed for its first 10 minutes. On
each of its trades, each variant checks its window (the last N minutes):
  - the price rose at least X% from the window's lowest price
  - at least min_buys buys from at least min_unique_buyers different wallets
  - buys outnumber sells at least min_buy_sell_ratio to 1
  - at least min_net_sol SOL of net buying (bought minus sold)
  - no single wallet did more than max_wallet_buy_share_pct of the buying
  - the creator hasn't sold any of it
  - the launch is 1-10 minutes old, still on the curve and less than
    max_curve_progress_pct of the way to graduating
  - not a copycat name (an earlier launch with the same name or symbol in
    the last 7 days) and the creator has no dead token (an earlier launch of
    theirs over an hour old that never graduated): the launch bot's skips,
    from launches this bot has seen
  - the feed was up for the whole window (trades missed in an outage would
    make the counts wrong), and isn't down now
  - this variant: under max_buys_per_hour buys in the last hour and
    max_open positions
When everything passes, it's a signal; the paper buy fills at the first
trade at least fill_delay_seconds later (a human reacting), at that trade's
price. Three variants run side by side, each with its own journal.

Costs and exits are the launch bot's ([launch.paper_trading], its slowest
speed's priority fee and slippage): $5 buys, 1% bot fee, pump.fun's fee and
5% slippage on every trade, sell half at 2x, everything left at -30% or 30
minutes after the buy.

Near-misses (the rise came but another rule failed, or everything else
passed and the rise was close) go to near_misses.csv, once per launch and
variant, so the rules can be tuned later.
"""

import json
import os
import time
from collections import deque
from datetime import datetime, timezone

from screener.jupiter import COLUMNS as JUPITER_COLUMNS
from screener.launch import LaunchTrader
from screener.paper_trader import append_row, pct
from screener.pumpfeed import decode

ENTRY_COLUMNS = [
    "time_utc", "variant", "symbol", "token_address", "price_usd", "price_sol",
    "seconds_after_creation", "seconds_after_signal", "rise_pct", "window_minutes",
    "buys", "sells", "unique_buyers", "net_sol", "top_wallet_buy_pct", "curve_progress_pct",
    *JUPITER_COLUMNS, "jupiter_checked_seconds_after_signal",
]
NEAR_MISS_COLUMNS = [
    "time_utc", "variant", "symbol", "token_address", "seconds_after_creation", "rise_pct",
    "buys", "sells", "unique_buyers", "buy_sell_ratio", "net_sol", "top_wallet_buy_pct",
    "creator_sold", "curve_progress_pct", "failed",
]


def utc(t):
    return datetime.fromtimestamp(t, timezone.utc)


def _atomic_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)  # the push job never sees a half-written file


def window_metrics(trades, now, window_seconds):
    """Rise, counts, buyers and net buying over the trades in the window.
    `trades` are (time, price_sol, is_buy, sol, wallet), oldest first."""
    recent = [x for x in trades if now - x[0] <= window_seconds and x[1]]
    if not recent:
        return None
    low = min(x[1] for x in recent)
    buys = [x for x in recent if x[2]]
    sells = len(recent) - len(buys)
    bought = sum(x[3] for x in buys)
    per_wallet = {}
    for x in buys:
        per_wallet[x[4]] = per_wallet.get(x[4], 0.0) + x[3]
    return {
        "rise_pct": round((recent[-1][1] / low - 1) * 100, 1),
        "buys": len(buys), "sells": sells, "unique_buyers": len(per_wallet),
        "buy_sell_ratio": round(len(buys) / sells, 2) if sells else None,  # None = no sells
        "net_sol": round(bought - sum(x[3] for x in recent if not x[2]), 3),
        "top_wallet_buy_pct": round(100 * max(per_wallet.values()) / bought, 1)
        if bought else None,
    }


class MomentumTrader(LaunchTrader):
    """One variant: the launch bot's costs and exits (LaunchTrader), its own
    journal and entries."""

    def buy_signal(self, mint, symbol, price_usd, sol_usd, when, info):
        if not price_usd or price_usd <= 0 or not sol_usd or not self.can_buy(mint):
            return None
        amount = float(self.cfg["buy_amount_usd"])
        pos = {
            "address": mint, "symbol": symbol, "pair_address": None,
            "entry_time": when.isoformat(), "entry_price": price_usd, "peak_price": price_usd,
            "tokens": amount * self._pct_kept() / price_usd,
            "cost_usd": amount + self.speed["priority_fee_sol"] * sol_usd,
            "remaining_fraction": 1.0, "took_profit": False, "last_price": price_usd,
            "sol_usd_at_entry": sol_usd, "momentum": {k: info.get(k) for k in (
                "rise_pct", "window_minutes", "seconds_after_creation", "creator")},
        }
        self.open_positions.append(pos)
        self.state["ever_bought"].append(mint)
        self._journal(when, "BUY", pos, f"momentum +{info['rise_pct']:g}% in "
                      f"{info['window_minutes']:g} min", price_usd, pos["cost_usd"])
        jup = info.get("jupiter") or {}
        append_row(self.entries_path, ENTRY_COLUMNS, [
            when.strftime("%Y-%m-%d %H:%M:%S"), self.speed["name"], symbol, mint,
            f"{price_usd:.10g}", f"{info['price_sol']:.10g}",
            f"{info['seconds_after_creation']:.1f}", f"{info['seconds_after_signal']:.1f}",
            pct(info["rise_pct"]), pct(info["window_minutes"]), info["buys"], info["sells"],
            info["unique_buyers"], pct(info["net_sol"]), pct(info["top_wallet_buy_pct"]),
            pct(info["curve_progress_pct"]),
            *("" if jup.get(k) is None else jup[k] for k in JUPITER_COLUMNS),
            "" if info.get("jupiter_checked_seconds_after_signal") is None
            else info["jupiter_checked_seconds_after_signal"]])
        return pos


class MomentumEngine:
    """All decisions, driven by the feed's events and the clock. No network
    here: momentum_bot.py feeds it, prices it and looks up Jupiter."""

    def __init__(self, cfg, data_folder, clock=time.time):
        self.c = cfg["momentum"]
        launch = cfg["launch"]
        self.pt = launch["paper_trading"]
        # The launch bot's slowest speed: its priority fee and slippage.
        costs = next(s for s in launch["speeds"] if s["name"] == self.c["costs_like_speed"])
        self.clock = clock
        self.folder = os.path.join(data_folder, self.c["folder"])
        os.makedirs(self.folder, exist_ok=True)
        self.variants = {v["name"]: v for v in self.c["variants"]}
        self.traders = {
            name: MomentumTrader(self.pt, dict(costs, name=name, delay_seconds=0),
                                 os.path.join(self.folder, name))
            for name in self.variants}
        # A variant with stopped = true makes no new buys (and so no signals
        # or near misses); its journal stays.
        for name, v in self.variants.items():
            self.traders[name].buying = not v.get("stopped")
        self.window_max = max(v["window_minutes"] for v in self.variants.values()) * 60
        self.sol_usd = None
        self.launches = {}            # mint -> launch being followed (first 10 min) or held
        self.pending = {}             # (variant, mint) -> signal waiting for its fill
        self.external = {}            # mint -> (USD price, time) from DexScreener
        self.jupiter = {}             # mint -> (values, time read)
        self.buy_times = {name: deque() for name in self.variants}
        self.memory = {"names": {}, "creators": {}, "completed": {}}
        self.near_logged = set()      # (variant, mint) already in near_misses.csv
        self.stats = {}
        # The feed: up or down, and when the last outage ended.
        self.feed_up = False
        self.last_message = None
        self.last_ok = None           # the last message on a live feed
        self.outage_ended = clock()   # nothing seen before the start
        self.endpoint = None          # the RPC it's connected to (its host name)
        self.down_since = None        # when the feed last dropped
        self._load()
        self._count(clock(), "bot started")
        for trader in self.traders.values():
            for pos in trader.open_positions:
                self.launches.setdefault(pos["address"], self._new_launch(
                    pos["address"], pos["symbol"], "", (pos.get("momentum") or {}).get("creator"),
                    datetime.fromisoformat(pos["entry_time"]).timestamp()))

    # ---- persistence -------------------------------------------------

    def _load(self):
        path = os.path.join(self.folder, "state.json")
        if os.path.exists(path):
            with open(path) as fh:
                self.memory = json.load(fh).get("memory", self.memory)
        path = os.path.join(self.folder, "stats.json")
        if os.path.exists(path):
            with open(path) as fh:
                self.stats = json.load(fh)

    def save(self):
        _atomic_json(os.path.join(self.folder, "state.json"), {"memory": self.memory})
        keep = sorted(self.stats)[-24 * 14:]
        _atomic_json(os.path.join(self.folder, "stats.json"), {h: self.stats[h] for h in keep})
        for trader in self.traders.values():
            trader.save()

    def _count(self, t, key, n=1):
        bucket = self.stats.setdefault(utc(t).strftime("%Y-%m-%d %H:00"), {})
        bucket[key] = bucket.get(key, 0) + n

    def prune(self, t=None):
        """Forget launches older than the memory window (run hourly)."""
        t = t or self.clock()
        names = self.c["copycat_window_days"] * 86400
        creators = self.c["creator_memory_days"] * 86400
        mem = self.memory
        mem["names"] = {k: v for k, v in mem["names"].items() if t - v[0] <= names}
        mem["creators"] = {k: [x for x in v if t - x[0] <= creators]
                           for k, v in mem["creators"].items()}
        mem["creators"] = {k: v for k, v in mem["creators"].items() if v}
        mem["completed"] = {k: v for k, v in mem["completed"].items() if t - v <= creators}
        self.near_logged = {k for k in self.near_logged if k[1] in self.launches}

    # ---- the feed ----------------------------------------------------

    def connected(self, t=None, endpoint=None):
        t = t or self.clock()
        if self.down_since is not None:
            # How long it was down, counted in the hour it came back.
            self._count(t, "feed down seconds", round(t - self.down_since))
            self.down_since = None
        if endpoint and self.endpoint and endpoint != self.endpoint:
            self._count(t, "feed endpoint switches")
        self.endpoint = endpoint or self.endpoint
        self.feed_up, self.last_message = True, t
        self.outage_ended = t

    def disconnected(self, t=None):
        t = t or self.clock()
        if self.feed_up:
            self._count(t, "feed disconnects")
            if self.endpoint:
                self._count(t, f"feed disconnects: {self.endpoint}")
            self.down_since = t
        self.feed_up = False

    def feed_ok(self, t):
        return (self.feed_up and self.last_message is not None
                and t - self.last_message <= self.c["feed_stale_seconds"])

    def on_logs(self, logs, failed, t=None):
        """One notification from the feed."""
        t = t or self.clock()
        if self.feed_up and self.last_message and \
                t - self.last_message > self.c["feed_stale_seconds"]:
            self.outage_ended = t            # a silent gap counts as an outage
        self.last_message = t
        if self.feed_up:
            self.last_ok = t
        if failed:
            return
        for e in decode(logs):
            if e["kind"] == "create":
                self._on_create(e, t)
            elif e["kind"] == "trade":
                self._on_trade(e, t)
            else:
                self._on_complete(e, t)

    def set_sol_price(self, usd):
        if usd and usd > 0:
            self.sol_usd = usd
            for trader in self.traders.values():
                trader.sol_usd = usd

    def _new_launch(self, mint, symbol, name, creator, created):
        return {"mint": mint, "symbol": symbol or "?", "name": name, "creator": creator,
                "created": created, "trades": deque(), "price_sol": None, "price_time": None,
                "progress_pct": 0.0, "creator_sold": False, "completed": False,
                "skip": None}

    def _on_create(self, e, t):
        mint, creator = e["mint"], e["creator"]
        self._count(t, "launches seen")
        w = self._new_launch(mint, e["symbol"], e["name"], creator, t)
        w["skip"] = self._instant_skip(mint, creator, e["name"], e["symbol"], t)
        mem = self.memory
        for key in {k for k in (e["name"].lower(), e["symbol"].lower()) if k}:
            mem["names"].setdefault(key, [t, mint])
        if creator:
            mem["creators"].setdefault(creator, []).append([t, mint])
        if w["skip"]:
            self._count(t, f"skipped: {w['skip']}")
        self.launches[mint] = w

    def _instant_skip(self, mint, creator, name, symbol, t):
        """The launch bot's copycat and dead-creator skips (from launches
        this bot has seen)."""
        c, mem = self.c, self.memory
        for key in {k for k in (name.lower(), symbol.lower()) if k}:
            seen = mem["names"].get(key)
            if seen and seen[1] != mint and t - seen[0] <= c["copycat_window_days"] * 86400:
                return "copycat name"
        for when, other in mem["creators"].get(creator, []):
            if other != mint and t - when >= c["dead_after_minutes"] * 60 \
                    and other not in mem["completed"]:
                return "creator has a dead token"
        return None

    def _on_complete(self, e, t):
        self.memory["completed"][e["mint"]] = t
        w = self.launches.get(e["mint"])
        if w:
            w["completed"] = True

    def _on_trade(self, e, t):
        w = self.launches.get(e["mint"])
        if w is None:
            return                            # created before the bot was watching
        self._count(t, "trades")
        if e["price_sol"]:
            w["price_sol"], w["price_time"] = e["price_sol"], t
        w["progress_pct"] = e["progress_pct"]
        if e["user"] == w["creator"] and not w.get("creator_traded"):
            w["creator_traded"] = True       # a check that the creator is decoded right
            self._count(t, "launches whose creator traded")
        if not e["is_buy"] and e["user"] == w["creator"]:
            w["creator_sold"] = True
        trades = w["trades"]
        trades.append((t, e["price_sol"], e["is_buy"], e["sol"], e["user"]))
        while trades and t - trades[0][0] > self.window_max:
            trades.popleft()
        # Fills first: a signal waiting for this launch's next trade.
        for (name, mint), signal in list(self.pending.items()):
            if mint == w["mint"] and t - signal["at"] >= self.c["fill_delay_seconds"]:
                self._fill(name, w, signal, t)
        if w["price_sol"] and self.sol_usd and self._held(w["mint"]):
            self._update_prices({w["mint"]: w["price_sol"] * self.sol_usd}, t)
        age = t - w["created"]
        if self.c["min_age_seconds"] <= age <= self.c["max_age_seconds"]:
            for name, v in self.variants.items():
                self._evaluate(name, v, w, t, age)

    # ---- the rules ---------------------------------------------------

    def _evaluate(self, name, v, w, t, age):
        c, trader, mint = self.c, self.traders[name], w["mint"]
        if (name, mint) in self.pending or not trader.can_buy(mint):
            return
        window = v["window_minutes"] * 60
        m = window_metrics(w["trades"], t, window)
        if m is None:
            return
        while self.buy_times[name] and t - self.buy_times[name][0] > 3600:
            self.buy_times[name].popleft()
        checks = [
            ("rise", m["rise_pct"] >= v["rise_pct"]),
            ("buys", m["buys"] >= c["min_buys"]),
            ("unique buyers", m["unique_buyers"] >= c["min_unique_buyers"]),
            ("buys vs sells", m["buy_sell_ratio"] is None
             or m["buy_sell_ratio"] >= c["min_buy_sell_ratio"]),
            ("net SOL buying", m["net_sol"] >= c["min_net_sol"]),
            ("one wallet's share", m["top_wallet_buy_pct"] is not None
             and m["top_wallet_buy_pct"] <= c["max_wallet_buy_share_pct"]),
            ("creator sold", not w["creator_sold"]),
            ("on the curve", not w["completed"]
             and w["progress_pct"] < c["max_curve_progress_pct"]),
            (w["skip"] or "copycat / dead creator", w["skip"] is None),
            ("feed was down in the window", self.outage_ended <= t - min(window, age)
             and self.feed_ok(t)),
            ("hourly cap", len(self.buy_times[name]) < c["max_buys_per_hour"]),
            ("open positions", len(trader.open_positions) < c["max_open"]),
        ]
        failed = [n for n, ok in checks if not ok]
        if not failed:
            self.pending[(name, mint)] = dict(m, at=t, window_minutes=v["window_minutes"],
                                              progress_pct=w["progress_pct"])
            self._count(t, f"{name}: signals")
            return
        close = (failed == ["rise"]
                 and m["rise_pct"] >= c["near_miss_rise_fraction"] * v["rise_pct"])
        if (checks[0][1] or close) and (name, mint) not in self.near_logged:
            self.near_logged.add((name, mint))
            self._near_miss(name, w, m, age, failed, t)

    def _near_miss(self, name, w, m, age, failed, t):
        self._count(t, f"{name}: near misses")
        append_row(os.path.join(self.folder, "near_misses.csv"), NEAR_MISS_COLUMNS, [
            utc(t).strftime("%Y-%m-%d %H:%M:%S"), name, w["symbol"], w["mint"], f"{age:.0f}",
            pct(m["rise_pct"]), m["buys"], m["sells"], m["unique_buyers"],
            "" if m["buy_sell_ratio"] is None else m["buy_sell_ratio"], pct(m["net_sol"]),
            pct(m["top_wallet_buy_pct"]), "yes" if w["creator_sold"] else "no",
            pct(w["progress_pct"]), "; ".join(failed)])

    def _fill(self, name, w, signal, t):
        """The paper buy, at this trade's price (or nothing, if the feed or
        the caps no longer allow it)."""
        del self.pending[(name, w["mint"])]
        trader = self.traders[name]
        reason = None
        if not self.feed_ok(t) or self.outage_ended > signal["at"]:
            reason = "feed down since the signal"
        elif len(trader.open_positions) >= self.c["max_open"]:
            reason = "open positions"
        elif not self.sol_usd or not w["price_sol"]:
            reason = "no price"
        if reason:
            self._count(t, f"{name}: not filled ({reason})")
            return
        info = dict(signal, price_sol=w["price_sol"], creator=w["creator"],
                    seconds_after_creation=t - w["created"],
                    seconds_after_signal=t - signal["at"],
                    curve_progress_pct=w["progress_pct"])
        reading = self.jupiter.get(w["mint"])
        if reading:
            info["jupiter"] = reading[0]
            info["jupiter_checked_seconds_after_signal"] = round(reading[1] - signal["at"], 1)
        if trader.buy_signal(w["mint"], w["symbol"], w["price_sol"] * self.sol_usd,
                             self.sol_usd, utc(t), info):
            self.buy_times[name].append(t)
            self._count(t, f"{name}: buys")
            trader.save()

    # ---- prices and the clock ----------------------------------------

    def jupiter_due(self):
        """Launches with a signal waiting whose organic score isn't read yet."""
        return sorted({mint for (_, mint) in self.pending if mint not in self.jupiter})

    def set_jupiter(self, mint, values, t=None):
        self.jupiter[mint] = (values, t or self.clock())

    def set_external_prices(self, prices, t=None):
        """USD prices from DexScreener for held tokens the feed no longer
        prices (graduated, gone quiet, or restored after a restart)."""
        t = t or self.clock()
        self.external.update({m: (p, t) for m, p in prices.items() if p})
        self._update_prices({m: p for m, p in prices.items()
                             if p and self._uses_external(m, t)}, t)

    def needs_external(self, t=None):
        t = t or self.clock()
        return [m for m in self.launches if self._held(m) and self._uses_external(m, t)]

    def _uses_external(self, mint, t):
        w = self.launches.get(mint) or {}
        return (w.get("completed") or w.get("price_sol") is None
                or t - (w.get("price_time") or 0) > self.c["stale_price_seconds"])

    def _held(self, mint):
        return any(trader.position(mint) for trader in self.traders.values())

    def _current_usd(self, mint, t):
        if self._uses_external(mint, t) and mint in self.external:
            return self.external[mint][0]
        w = self.launches.get(mint)
        if w and w.get("price_sol") and self.sol_usd and not self._uses_external(mint, t):
            return w["price_sol"] * self.sol_usd
        return None

    def _update_prices(self, prices, t):
        for trader in self.traders.values():
            if trader.update(prices, when=utc(t)):
                trader.save()            # a sell: saved at once so a crash can't undo it

    def tick(self, t=None):
        """About twice a second: time stops, signals that never got a fill,
        and launches no longer followed."""
        t = t or self.clock()
        for key, signal in list(self.pending.items()):
            if t - signal["at"] > self.c["fill_timeout_seconds"]:
                del self.pending[key]
                self._count(t, f"{key[0]}: not filled (no trade)")
        prices = {m: p for m in self.launches if self._held(m) and (p := self._current_usd(m, t))}
        if prices:
            self._update_prices(prices, t)
        pending = {mint for (_, mint) in self.pending}
        for mint, w in list(self.launches.items()):
            if t - w["created"] > self.c["max_age_seconds"] + 5 and not self._held(mint) \
                    and mint not in pending:
                self.launches.pop(mint)
                self.jupiter.pop(mint, None)
                self.external.pop(mint, None)

    def health(self, t=None):
        t = t or self.clock()
        hour = self.stats.get(utc(t).strftime("%Y-%m-%d %H:00"), {})
        return {"updated": utc(t).isoformat(), "feed_up": self.feed_ok(t),
                "last_message": utc(self.last_message).isoformat() if self.last_message else None,
                "last_ok": utc(self.last_ok).isoformat() if self.last_ok else None,
                "endpoint": self.endpoint,
                "following": len(self.launches),
                "open": {n: len(tr.open_positions) for n, tr in self.traders.items()},
                "this_hour": hour}

