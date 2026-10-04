"""The "launch" paper strategy: would sniping brand-new pump.fun tokens work?

It runs on a small always-on server (see deploy/LAUNCH_SERVER_SETUP.md), fed
by PumpPortal's free real-time data WebSocket: new tokens and migrations.
PumpPortal's token-trade stream needs an API key and a funded wallet, so the
bot doesn't use it: it never sees individual buys and sells (trade_feed is
off), and the buy/sell counts, first-block buyers and price change since
creation are saved blank. It is PAPER trading only: it only READS public
data. It never connects to a wallet, never uses a private key and never uses
PumpPortal's trading API.

For every new pump.fun token:
  1. Instant checks (skip if any fails):
     - not a copycat: no earlier launch with the same name or symbol in the
       last 7 days (seen by this bot)
     - the creator has no dead earlier token: none of their earlier launches
       (seen by this bot) is older than an hour without having graduated
     - the hourly cap (10 selected launches an hour) isn't used up
  2. First block (the first ~1 second): the launch is FLAGGED if the creator
     bought in the creation transaction or other wallets bought in the first
     block. Without the trade feed only the creator's buy is known (it's in
     the creation message). Flags are recorded for every launch;
     skip_flagged decides whether flagged launches are skipped.
  3. The same launch is paper-bought by three "speeds", each with its own
     journal: 5 seconds after creation (sniper-bot speed), 30 seconds and 90
     seconds (human speed), at the bonding-curve price at that moment, plus
     costs: a priority fee per transaction (in SOL), a 1% bot fee, pump.fun's
     own fee, and extra slippage. Each speed holds at most 30 positions.
  4. Exits: sell half at 2x; sell everything left at -30% or 30 minutes after
     the buy, whichever comes first.

Prices: the bonding-curve price in the creation message, then DexScreener
once that price is older than stale_price_seconds or the token graduates.
(With the trade feed, every trade would update the curve price.)
"""

import csv
import json
import os
import time
from collections import deque
from datetime import datetime, timezone

from screener.filters import best_pair, to_float
from screener.jupiter import COLUMNS as JUPITER_COLUMNS
from screener.paper_trader import PaperTrader, append_row, pct

# The 5-minute and 1-hour price change at each buy, like the other strategies'
# entries.csv. Launches are bought at most 90 seconds old, before DexScreener
# reliably lists them, so both are the change since creation measured from the
# PumpPortal trade feed: for a token younger than 5 minutes that's the whole
# window. Without the trade feed they, the buy/sell counts and the first-block
# buyers are blank (not known), never 0.
# jupiter_*: Jupiter's organic score (screener/jupiter.py; logging only). The
# runner looks it up in the background once a launch is selected and every
# JUPITER_EVERY_SECONDS after, so each buy saves the latest reading and
# jupiter_checked_seconds_after_creation says how old the token was then.
# Blank = no reading yet (a launch a few seconds old usually has none).
LAUNCH_ENTRY_COLUMNS = [
    "time_utc", "symbol", "token_address", "price_usd", "seconds_after_creation",
    "buys_so_far", "sells_so_far", "dev_buy_pct", "first_block_buyers", "flagged",
    "price_change_5m_pct", "price_change_1h_pct", *JUPITER_COLUMNS,
    "jupiter_checked_seconds_after_creation",
]
JUPITER_EVERY_SECONDS = 10

TOTAL_SUPPLY = 1_000_000_000  # every pump.fun token
WSOL = "So11111111111111111111111111111111111111112"


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


def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc)


def curve_price_sol(v_sol, v_tokens):
    """Price of one token in SOL on the bonding curve."""
    v_sol, v_tokens = to_float(v_sol), to_float(v_tokens)
    if not v_sol or not v_tokens:
        return None
    return v_sol / v_tokens


def change_pct(before, after):
    """% change from `before` to `after`, or None if either is unknown."""
    if not before or not after:
        return None
    return round((after / before - 1) * 100, 2)


def cell(value):
    """A CSV cell; blank when the value isn't known."""
    return "" if value is None else value


def _atomic_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)  # the push job never sees a half-written file


class LaunchTrader(PaperTrader):
    """One speed (5s, 30s or 90s). Same bookkeeping as the other strategies,
    but launch costs: a priority fee in SOL on every buy and sell, a bot fee
    and pump.fun's fee (both %) and extra slippage (%) on every trade."""

    def __init__(self, cfg, speed, folder):
        merged = dict(cfg, round_trip_cost_pct=0)  # costs are handled below
        super().__init__(merged, folder)
        self.speed = speed
        self.sol_usd = None

    def save(self):
        _atomic_json(self.state_path, self.state)

    def _pct_kept(self):
        c, s = self.cfg, self.speed
        return (1 - (c["bot_fee_pct"] + c["platform_fee_pct"]) / 100) * \
            (1 - s["extra_slippage_pct"] / 100)

    def buy_launch(self, mint, symbol, price_usd, sol_usd, when, info):
        """Paper-buy buy_amount_usd of a launch at the market price."""
        if not price_usd or price_usd <= 0 or not sol_usd or not self.can_buy(mint):
            return None
        amount = float(self.cfg["buy_amount_usd"])
        priority_usd = self.speed["priority_fee_sol"] * sol_usd
        pos = {
            "address": mint, "symbol": symbol, "pair_address": None,
            "entry_time": when.isoformat(),
            "entry_price": price_usd,               # market price: the exits use this
            "peak_price": price_usd,
            "tokens": amount * self._pct_kept() / price_usd,   # what the costs leave
            "cost_usd": amount + priority_usd,      # the buy plus its priority fee
            "remaining_fraction": 1.0, "took_profit": False, "last_price": price_usd,
            "sol_usd_at_entry": sol_usd, "launch": info,
        }
        self.open_positions.append(pos)
        self.state["ever_bought"].append(mint)
        self._journal(when, "BUY", pos, f"launch +{self.speed['delay_seconds']:g}s",
                      price_usd, pos["cost_usd"])
        self._launch_entry(when, pos, info)
        return pos

    def _sell(self, pos, fraction, price, reason, when):
        fraction = min(fraction, pos["remaining_fraction"])
        sol_usd = self.sol_usd or pos.get("sol_usd_at_entry") or 0
        gross = pos["tokens"] * fraction * price
        proceeds = gross * self._pct_kept() - self.speed["priority_fee_sol"] * sol_usd
        cost = pos["cost_usd"] * fraction
        pnl = proceeds - cost
        pos["remaining_fraction"] = round(pos["remaining_fraction"] - fraction, 10)
        self.state["running_total_pnl_usd"] += pnl
        self._journal(when, "SELL", pos, reason, price, proceeds, pnl, pnl / cost * 100)
        pos.setdefault("sells", []).append({
            "time": when.isoformat(), "fraction": fraction, "price": price,
            "reason": reason, "proceeds_usd": proceeds, "pnl_usd": pnl})
        return {"symbol": pos["symbol"], "reason": reason, "pnl_usd": pnl,
                "closed": pos["remaining_fraction"] <= 0, "position": pos}

    def close_reason(self, pos, change_pct, from_peak, hours):
        c = self.cfg
        if change_pct <= -c["stop_loss_pct"]:
            return f"stop loss: down {-change_pct:.0f}% from entry"
        if hours * 60 >= c["time_stop_minutes"]:
            return f"time stop: {hours * 60:.0f} min ({change_pct:+.0f}%)"
        return None

    def _launch_entry(self, when, pos, info):
        append_row(self.entries_path, LAUNCH_ENTRY_COLUMNS, [
            when.strftime("%Y-%m-%d %H:%M:%S"), pos["symbol"], pos["address"],
            f"{pos['entry_price']:.10g}", f"{info['seconds_after_creation']:.1f}",
            cell(info["buys"]), cell(info["sells"]), f"{info['dev_buy_pct']:.2f}",
            cell(info["first_block_buyers"]), "yes" if info["flagged"] else "no",
            pct(info.get("change_since_creation_pct")),
            pct(info.get("change_since_creation_pct")),
            *(cell((info.get("jupiter") or {}).get(k)) for k in JUPITER_COLUMNS),
            cell(info.get("jupiter_checked_seconds_after_creation"))])


class LaunchEngine:
    """All decisions, driven by feed messages and the clock. No network here:
    the runner (launch_bot.py) feeds it and carries out its requests to
    subscribe to or drop a token's trades.

    trade_feed: whether the runner receives each token's trades. The bot runs
    without them (PumpPortal's trade stream needs an API key and a funded
    wallet); then nothing is subscribed and what only trades could tell is
    saved blank. The tests turn it on to check the trade-driven logic."""

    def __init__(self, cfg, data_folder, clock=time.time, trade_feed=False):
        self.c = cfg["launch"]
        self.trade_feed = trade_feed
        self.pt = self.c["paper_trading"]
        self.clock = clock
        self.folder = os.path.join(data_folder, "launch")
        os.makedirs(self.folder, exist_ok=True)
        self.speeds = {s["name"]: s for s in self.c["speeds"]}
        self.traders = {name: LaunchTrader(self.pt, s, os.path.join(self.folder, name))
                        for name, s in self.speeds.items()}
        self.sol_usd = None
        self.watch = {}          # mint -> launch being evaluated, entered or held
        self.external = {}       # mint -> latest USD price after graduation (DexScreener)
        self.jupiter = {}        # mint -> (organic-score values, unix time read): logging only
        self.migrated = set()
        self.selected = deque()  # times of selected launches (hourly cap)
        self.memory = {"names": {}, "creators": {}, "migrated": {}}
        self.stats = {}
        self._load()
        # Counted so restarts show up in stats.json: launches being evaluated
        # when the bot stopped lose the speeds they hadn't reached yet.
        self._count(clock(), "bot started")
        # Positions still open from before a restart need their prices again.
        for trader in self.traders.values():
            for pos in trader.open_positions:
                info = pos.get("launch") or {}
                self.watch.setdefault(pos["address"], {
                    "mint": pos["address"], "symbol": pos["symbol"],
                    "created": datetime.fromisoformat(pos["entry_time"]).timestamp(),
                    "creator": info.get("creator"), "price_sol": None, "status": "held",
                    "entered": set(self.speeds), "buys": 0, "sells": 0,
                    "first_block_buyers": set(), "dev_buy_pct": info.get("dev_buy_pct", 0)})

    # ---- persistence -------------------------------------------------

    def _state_path(self):
        return os.path.join(self.folder, "state.json")

    def _load(self):
        if os.path.exists(self._state_path()):
            with open(self._state_path()) as fh:
                saved = json.load(fh)
            self.memory = saved.get("memory", self.memory)
            self.selected = deque(saved.get("selected", []))
        stats = os.path.join(self.folder, "stats.json")
        if os.path.exists(stats):
            with open(stats) as fh:
                self.stats = json.load(fh)

    def save(self):
        _atomic_json(self._state_path(), {"memory": self.memory,
                                          "selected": list(self.selected)})
        keep = sorted(self.stats)[-24 * 14:]  # two weeks of hourly counts
        _atomic_json(os.path.join(self.folder, "stats.json"),
                     {h: self.stats[h] for h in keep})
        for trader in self.traders.values():
            trader.save()

    def _count(self, t, key):
        hour = utc(t).strftime("%Y-%m-%d %H:00")
        bucket = self.stats.setdefault(hour, {})
        bucket[key] = bucket.get(key, 0) + 1

    def _log(self, t, w, decision, reason=""):
        path = os.path.join(self.folder, "launches.csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="") as fh:
            out = csv.writer(fh)
            if new:
                out.writerow(["time_utc", "mint", "symbol", "name", "creator", "dev_buy_pct",
                              "first_block_buyers", "flagged", "decision", "reason"])
            out.writerow([utc(t).strftime("%Y-%m-%d %H:%M:%S"), w["mint"], w["symbol"],
                          w.get("name", ""), w["creator"], f"{w['dev_buy_pct']:.2f}",
                          cell(self._known(len(w["first_block_buyers"]))),
                          "yes" if w.get("flagged") else "no",
                          decision, reason])

    # ---- the feed ----------------------------------------------------

    def set_sol_price(self, usd):
        if usd and usd > 0:
            self.sol_usd = usd
            for trader in self.traders.values():
                trader.sol_usd = usd

    def on_message(self, msg, t=None):
        """Handle one feed message. Returns (subscribe, unsubscribe) lists."""
        t = t or self.clock()
        if not isinstance(msg, dict) or not msg.get("mint"):
            return [], []  # subscription confirmations and the like
        kind = str(msg.get("txType") or "").lower()
        if kind == "create":
            return self._on_create(msg, t)
        if kind in ("buy", "sell"):
            self._on_trade(msg, kind, t)
        elif "migrat" in kind:
            self._on_migration(msg, t)
        return [], []

    def _on_create(self, msg, t):
        mint, creator = msg["mint"], msg.get("traderPublicKey")
        name, symbol = (msg.get("name") or "").strip(), (msg.get("symbol") or "").strip()
        self._count(t, "launches_seen")
        price = curve_price_sol(msg.get("vSolInBondingCurve"), msg.get("vTokensInBondingCurve"))
        # A launch the free feed doesn't price (e.g. from another launchpad)
        # can't be paper-traded at any speed: skip it before it takes a slot
        # under the hourly cap.
        reason = (self._instant_skip(mint, creator, name, symbol, t)
                  or (None if price else "no price in the feed"))
        self._remember(mint, creator, name, symbol, t)
        if reason:
            self._count(t, f"skipped: {reason}")
            return [], []
        initial = to_float(msg.get("initialBuy")) or 0.0
        self.watch[mint] = {
            "mint": mint, "symbol": symbol or "?", "name": name, "creator": creator,
            "created": t, "slot": msg.get("slot"), "status": "evaluating", "price_time": t,
            "price_sol": price, "created_price_sol": price,
            "dev_buy_pct": initial / TOTAL_SUPPLY * 100, "first_block_buyers": set(),
            "buys": 0, "sells": 0, "entered": set(),
        }
        self._reserve(t)
        return ([mint] if self.trade_feed else []), []

    def _instant_skip(self, mint, creator, name, symbol, t):
        c, mem = self.c, self.memory
        if not self.sol_usd:
            return "no SOL price yet"
        window = c["copycat_window_days"] * 86400
        for key in {k for k in (name.lower(), symbol.lower()) if k}:
            seen = mem["names"].get(key)
            if seen and seen[1] != mint and t - seen[0] <= window:
                return "copycat name"
        for when, other in mem["creators"].get(creator, []):
            if other != mint and t - when >= c["dead_after_minutes"] * 60 \
                    and other not in mem["migrated"]:
                return "creator has a dead token"
        while self.selected and t - self.selected[0] > 3600:
            self.selected.popleft()
        if len(self.selected) >= c["max_new_trades_per_hour"]:
            return "hourly cap reached"
        return None

    def _reserve(self, t):
        """Count a launch against the hourly cap while it's evaluated."""
        self.selected.append(t)

    def _remember(self, mint, creator, name, symbol, t):
        mem = self.memory
        for key in {k for k in (name.lower(), symbol.lower()) if k}:
            mem["names"].setdefault(key, [t, mint])
        if creator:
            mem["creators"].setdefault(creator, []).append([t, mint])

    def _on_trade(self, msg, kind, t):
        mint = msg["mint"]
        w = self.watch.get(mint)
        if not w:
            return
        price = curve_price_sol(msg.get("vSolInBondingCurve"), msg.get("vTokensInBondingCurve"))
        if price:
            w["price_sol"] = price
            w["price_time"] = t
        w["buys" if kind == "buy" else "sells"] += 1
        if w["status"] == "evaluating" and kind == "buy" and msg.get("traderPublicKey") \
                and msg.get("traderPublicKey") != w["creator"]:
            same_block = (w.get("slot") is not None and msg.get("slot") == w["slot"])
            in_window = t - w["created"] <= self.c["first_block_seconds"]
            if same_block or (w.get("slot") is None and in_window):
                w["first_block_buyers"].add(msg["traderPublicKey"])
        if price and self.sol_usd:
            self._update_prices({mint: price * self.sol_usd}, t)

    def _on_migration(self, msg, t):
        mint = msg["mint"]
        self.memory["migrated"][mint] = t
        if mint in self.watch:
            self.migrated.add(mint)

    def set_external_prices(self, prices, t=None):
        """USD prices from DexScreener, for held tokens the feed no longer
        prices (graduated, gone quiet, or restored after a restart)."""
        t = t or self.clock()
        self.external.update({m: (p, t) for m, p in prices.items() if p})
        self._update_prices({m: p for m, p in prices.items()
                             if p and self._uses_external(m, t)}, t)

    def jupiter_due(self, t=None):
        """Selected launches still waiting for a speed's buy whose Jupiter
        reading is missing or older than JUPITER_EVERY_SECONDS."""
        t = t or self.clock()
        due = []
        for mint, w in self.watch.items():
            if w["status"] != "selected" or w["entered"] >= set(self.speeds):
                continue
            last = self.jupiter.get(mint)
            if last is None or t - last[1] >= JUPITER_EVERY_SECONDS:
                due.append(mint)
        return due

    def set_jupiter(self, mint, values, t=None):
        if mint in self.watch:
            self.jupiter[mint] = (values, t or self.clock())

    def needs_external(self, t=None):
        """Held tokens to look up on DexScreener."""
        t = t or self.clock()
        return [m for m in self.watch if self._held(m) and self._uses_external(m, t)]

    def _uses_external(self, mint, t):
        if mint in self.migrated:
            return True
        w = self.watch.get(mint) or {}
        last = w.get("price_time")
        return w.get("price_sol") is None or last is None or \
            t - last > self.c["stale_price_seconds"]

    def _held(self, mint):
        return any(trader.position(mint) for trader in self.traders.values())

    def _update_prices(self, prices, t):
        when = utc(t)
        for trader in self.traders.values():
            if trader.update(prices, when=when):
                trader.save()  # a sell: save right away so a crash can't undo it

    def _current_usd(self, mint, t=None):
        t = t or self.clock()
        if self._uses_external(mint, t) and mint in self.external:
            return self.external[mint][0]
        w = self.watch.get(mint)
        if w and w.get("price_sol") and self.sol_usd:
            return w["price_sol"] * self.sol_usd
        return None

    # ---- the clock ---------------------------------------------------

    def tick(self, t=None):
        """Called about twice a second. Returns (subscribe, unsubscribe)."""
        t = t or self.clock()
        c = self.c
        drop = []
        for mint, w in list(self.watch.items()):
            age = t - w["created"]
            if w["status"] == "evaluating" and age >= c["first_block_seconds"]:
                w["flagged"] = w["dev_buy_pct"] > 0 or len(w["first_block_buyers"]) > 0
                if w["flagged"]:
                    self._count(t, "flagged")
                if w["flagged"] and c["skip_flagged"]:
                    self._log(t, w, "skipped", "flagged (first block)")
                    self._count(t, "skipped: flagged")
                    w["status"] = "done"
                    if w["created"] in self.selected:  # not a trade: free its slot
                        self.selected.remove(w["created"])
                else:
                    self._log(t, w, "selected")
                    self._count(t, "selected")
                    w["status"] = "selected"
            if w["status"] == "selected":
                for name, speed in self.speeds.items():
                    if name in w["entered"] or age < speed["delay_seconds"]:
                        continue
                    w["entered"].add(name)
                    trader = self.traders[name]
                    if len(trader.open_positions) >= c["max_open_per_speed"]:
                        self._count(t, f"{name}: skipped, {c['max_open_per_speed']} open")
                        continue
                    price = self._current_usd(mint, t)
                    info = {"seconds_after_creation": age, "buys": self._known(w["buys"]),
                            "sells": self._known(w["sells"]),
                            "dev_buy_pct": w["dev_buy_pct"],
                            "first_block_buyers": self._known(len(w["first_block_buyers"])),
                            "flagged": w.get("flagged", False), "creator": w["creator"],
                            "change_since_creation_pct": self._known(change_pct(
                                w.get("created_price_sol"), w.get("price_sol")))}
                    reading = self.jupiter.get(mint)
                    if reading:
                        info["jupiter"] = reading[0]
                        info["jupiter_checked_seconds_after_creation"] = round(
                            reading[1] - w["created"], 1)
                    if trader.buy_launch(mint, w["symbol"], price, self.sol_usd, utc(t), info):
                        trader.save()
                if w["entered"] >= set(self.speeds):
                    w["status"] = "held"
            if w["status"] in ("held", "done") and not self._held(mint):
                drop.append(mint)
        # time stops, even when a token has stopped trading
        prices = {m: p for m in self.watch if (p := self._current_usd(m, t))}
        if prices:
            self._update_prices(prices, t)
        for mint in drop:
            self.jupiter.pop(mint, None)
            self.watch.pop(mint, None)
            self.migrated.discard(mint)
            self.external.pop(mint, None)
        return [], (drop if self.trade_feed else [])

    def prune(self, t=None):
        """Forget launches older than the memory window (run hourly)."""
        t = t or self.clock()
        mem, c = self.memory, self.c
        keep_names = c["copycat_window_days"] * 86400
        keep_creators = c["creator_memory_days"] * 86400
        mem["names"] = {k: v for k, v in mem["names"].items() if t - v[0] <= keep_names}
        mem["creators"] = {k: [x for x in v if t - x[0] <= keep_creators]
                           for k, v in mem["creators"].items()}
        mem["creators"] = {k: v for k, v in mem["creators"].items() if v}
        mem["migrated"] = {k: v for k, v in mem["migrated"].items() if t - v <= keep_creators}

    def subscriptions(self):
        """Mints whose trades are needed (after a reconnect)."""
        if not self.trade_feed:
            return []
        return [m for m in self.watch if m not in self.migrated]

    def _known(self, value):
        """A value only the trade feed can tell, or None without it."""
        return value if self.trade_feed else None
