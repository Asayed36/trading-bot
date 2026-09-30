"""The "convergence" paper strategy: follow proven traders.

Paper-buys $5 of a Solana token when 3 or more wallets from a tracked list of
proven traders buy it within 20 minutes. The list is rebuilt every week from
realized profit. Like everything here it is PAPER trading only: it only
READS public blockchain data. It never connects to a wallet, never uses a
private key and never places an order. The Helius API key it uses is a
data-access key, not a wallet key.

How it works (numbers in [convergence] in config.toml):

1. Winners. Every run, tokens from DexScreener's lists that are up 100%+ in
   24h with real liquidity are remembered for a week.
2. Weekly list. Once a week, the biggest holders of the week's winners
   (from RugCheck, free) become candidates. Each candidate's last 14 days of
   swaps are read from Helius and their realized profit is worked out.
   Wallets that trade too often (bots), made most of their profit on one
   token, or didn't close enough trades are dropped. The most profitable
   ones become the tracked list. This work is spread over many runs.
3. Live. Every run, each tracked wallet's new transactions are read from
   Helius and decoded into buys and sells. When 3+ tracked wallets bought the
   same token within 20 minutes, and the last of those buys was in the last
   20 minutes, the token is paper-bought if it passes basic checks.
4. Exits: sell half at 2x, -30% hard stop, sell the rest when 2 of the
   wallets that triggered the buy sell, a 40% trailing stop after taking
   profit, and 24 hours at most.

Helius credits. getSignaturesForAddress and getTransaction cost 10 credits
each on Helius. Every call is counted before it's made. Spending is paced
across the billing cycle, and the strategy pauses itself (until the next
cycle) rather than go past pause_at_pct (80%) of the free monthly credits.
Open positions keep being managed while paused, using free DexScreener prices.
"""

import copy
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta

import requests

from screener.api import ApiError, RateLimited
from screener.filters import (FAIL, PASS, Check, Result, best_pair, find_candidates,
                              money, real_holders, to_float)
from screener.paper_trader import PaperTrader, now_utc

HELIUS_RPC = "https://mainnet.helius-rpc.com/?api-key={}"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
           "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}   # USDT
CREDITS_PER_CALL = 10  # Helius: getSignaturesForAddress / getTransaction


class BudgetPaused(Exception):
    """Making this call would take Helius usage past the pause limit."""


# ---------------------------------------------------------------------
# Helius credits
# ---------------------------------------------------------------------

def cycle_start(now, cycle_day):
    """Start of the current Helius billing cycle (UTC midnight on cycle_day)."""
    day = max(1, min(28, int(cycle_day)))
    start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if start > now:  # this month's cycle day hasn't come yet
        prev = (now.replace(day=1) - timedelta(days=1))
        start = prev.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    return start


def next_cycle_start(start):
    nxt = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
    return nxt.replace(day=start.day)


class CreditMeter:
    """Counts Helius credits for the current billing cycle, in the strategy's
    positions.json, and refuses calls that would pass the pause limit."""

    def __init__(self, state, c, now):
        self.c = c
        self.now = now
        start = cycle_start(now, c["helius_cycle_day"])
        meter = state.get("helius") or {}
        if meter.get("cycle_start") != start.isoformat():
            meter = {"cycle_start": start.isoformat(), "used": 0, "by_day": {}}
        self.meter = meter
        self.start = start
        self.end = next_cycle_start(start)
        self.cap = int(c["helius_monthly_credits"] * c["pause_at_pct"] / 100)

    @property
    def used(self):
        return self.meter["used"]

    def left(self):
        return self.cap - self.used

    def runs_left(self):
        return max(1, (self.end - self.now).total_seconds() / 60 / self.c["run_every_minutes"])

    def spend(self, credits):
        if self.used + credits > self.cap:
            raise BudgetPaused(f"Helius usage would pass {self.c['pause_at_pct']:g}% of the "
                               f"free {self.c['helius_monthly_credits']:,} monthly credits")
        self.meter["used"] += credits
        day = self.now.date().isoformat()
        self.meter["by_day"][day] = self.meter["by_day"].get(day, 0) + credits

    def export(self):
        m = copy.deepcopy(self.meter)
        # keep ~40 days of daily history
        m["by_day"] = dict(sorted(m["by_day"].items())[-40:])
        m.update({"cap": self.cap, "monthly": self.c["helius_monthly_credits"],
                  "pause_at_pct": self.c["pause_at_pct"], "cycle_end": self.end.isoformat()})
        return m


# ---------------------------------------------------------------------
# Solana RPC (Helius, or the public endpoint)
# ---------------------------------------------------------------------

class Rpc:
    """Minimal read-only Solana JSON-RPC client. Error messages never contain
    the URL, so the Helius API key can't leak into logs or reports."""

    def __init__(self, url, name, meter=None, per_call=0, min_interval=0.25, timeout=20):
        self._url = url
        self.name = name
        self.meter = meter
        self.per_call = per_call
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0
        self.calls = 0

    def call(self, method, params):
        if self.meter is not None and self.per_call:
            self.meter.spend(self.per_call)  # counted before the call is made
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self.calls += 1
        try:
            resp = requests.post(self._url, timeout=self.timeout, json={
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        except requests.RequestException as exc:
            raise ApiError(f"{self.name} {method}: could not connect "
                           f"({type(exc).__name__})") from None
        finally:
            self._last = time.time()
        if resp.status_code == 429:
            raise RateLimited(f"{self.name} {method}: too many requests or credits used up")
        if resp.status_code != 200:
            raise ApiError(f"{self.name} {method}: error {resp.status_code}")
        body = resp.json()
        if body.get("error"):
            raise ApiError(f"{self.name} {method}: {str(body['error'].get('message'))[:120]}")
        return body.get("result")

    def signatures(self, address, limit, until=None):
        opts = {"limit": limit}
        if until:
            opts["until"] = until
        return self.call("getSignaturesForAddress", [address, opts]) or []

    def transaction(self, signature):
        return self.call("getTransaction", [signature, {
            "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])


# ---------------------------------------------------------------------
# Decoding swaps and scoring traders
# ---------------------------------------------------------------------

def decode_swaps(tx, wallet):
    """Buys and sells of one token for SOL by `wallet` in a parsed transaction.
    Returns a list with at most one swap. Anything else (transfers, multi-token
    or stablecoin trades) returns []."""
    if not tx:
        return []
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return []
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in keys]
    if wallet not in keys:
        return []
    i = keys.index(wallet)
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    if i >= len(pre) or i >= len(post):
        return []
    sol = (post[i] - pre[i]) / 1e9

    deltas = defaultdict(float)
    for sign, balances in ((-1, meta.get("preTokenBalances")), (1, meta.get("postTokenBalances"))):
        for b in balances or []:
            if b.get("owner") != wallet:
                continue
            amount = to_float((b.get("uiTokenAmount") or {}).get("uiAmountString"))
            if amount is None:
                amount = to_float((b.get("uiTokenAmount") or {}).get("uiAmount")) or 0.0
            deltas[b.get("mint")] += sign * amount
    sol += deltas.pop(WSOL, 0.0)
    tokens = {m: d for m, d in deltas.items() if abs(d) > 1e-12}
    if not tokens or any(m in STABLES for m in tokens) or len(tokens) != 1:
        return []
    (mint, amount), = tokens.items()
    when = tx.get("blockTime")
    if amount > 0 and sol < 0:
        return [{"mint": mint, "side": "buy", "tokens": amount, "sol": -sol, "time": when}]
    if amount < 0 and sol > 0:
        return [{"mint": mint, "side": "sell", "tokens": -amount, "sol": sol, "time": when}]
    return []


def score_trader(swaps):
    """Realized profit in SOL from a list of swaps (average cost per token).
    Sells of tokens bought before the window have no known cost and are
    ignored."""
    held = defaultdict(lambda: [0.0, 0.0])  # mint -> [tokens, cost in SOL]
    realized, sold = defaultdict(float), set()
    for s in sorted(swaps, key=lambda s: s.get("time") or 0):
        qty, cost = held[s["mint"]]
        if s["side"] == "buy":
            held[s["mint"]] = [qty + s["tokens"], cost + s["sol"]]
            continue
        if qty <= 0:
            continue
        matched = min(s["tokens"], qty)
        cost_part = cost * matched / qty
        realized[s["mint"]] += s["sol"] * matched / s["tokens"] - cost_part
        held[s["mint"]] = [qty - matched, cost - cost_part]
        sold.add(s["mint"])
    closed = {m: realized[m] for m in sold}
    wins = sum(1 for p in closed.values() if p > 0)
    gains = sum(p for p in closed.values() if p > 0)
    return {
        "realized_sol": round(sum(closed.values()), 4),
        "closed": len(closed),
        "wins": wins,
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
        "top_share": round(max(closed.values()) / gains * 100, 1) if gains > 0 else 100.0,
        "swaps": len(swaps),
    }


def qualifies(stats, c):
    if stats.get("too_active"):
        return False, "trades too often (bot?)"
    if stats["closed"] < c["min_closed_trades"]:
        return False, f"only {stats['closed']} closed trade(s)"
    if stats["realized_sol"] < c["min_realized_sol"]:
        return False, f"realized {stats['realized_sol']:+.2f} SOL"
    if stats["win_rate"] < c["min_win_rate_pct"]:
        return False, f"win rate {stats['win_rate']:.0f}%"
    if stats["top_share"] > c["max_top_token_share_pct"]:
        return False, f"{stats['top_share']:.0f}% of profit from one token"
    return True, "ok"


# ---------------------------------------------------------------------
# Paper trader
# ---------------------------------------------------------------------

class ConvergenceTrader(PaperTrader):
    """Sell half at 2x (PaperTrader), then:
      - hard stop: everything left at -30%
      - smart money exit: everything left once 2 of the wallets that
        triggered the buy have sold
      - after take profit: 40% trailing stop, or 24 hours at most."""

    def close_reason(self, pos, change_pct, from_peak, hours):
        c = self.cfg
        if change_pct <= -c["stop_loss_pct"]:
            return f"hard stop: down {-change_pct:.0f}% from entry"
        sellers = len(pos.get("sold_by") or [])
        if sellers >= c["exit_when_wallets_sell"]:
            return f"smart money exit: {sellers} of the buyers sold ({change_pct:+.0f}%)"
        if pos["took_profit"] and from_peak <= -c["trailing_stop_pct"]:
            return f"trailing stop after profit: down {-from_peak:.0f}% from peak"
        if hours >= c["max_hold_hours"]:
            return f"max hold: {hours:.0f}h after entry ({change_pct:+.0f}%)"
        return None


# ---------------------------------------------------------------------
# The strategy
# ---------------------------------------------------------------------

class ConvergenceStrategy:
    name = "convergence"

    def __init__(self, cfg, data_folder, api_key=None, rpc_factory=None):
        self.c = cfg["convergence"]
        self.pt = self.c["paper_trading"]
        self.trader = ConvergenceTrader(self.pt, os.path.join(data_folder, "convergence"))
        self.api_key = api_key
        self.rpc_factory = rpc_factory  # tests and --demo pass a fake here

    def _rpcs(self, meter):
        if self.rpc_factory:
            return self.rpc_factory(meter)
        helius = Rpc(HELIUS_RPC.format(self.api_key), "Helius", meter, CREDITS_PER_CALL,
                     min_interval=1 / self.c["helius_max_requests_per_second"])
        if self.c["live_rpc"] == "public":
            live = Rpc(PUBLIC_RPC, "public Solana RPC", min_interval=0.3)
        else:
            live = helius
        return helius, live

    # ---- the network part: nothing here changes the paper trades ----

    def fetch(self, api, now=None):
        now = now or now_utc()
        c, trader = self.c, self.trader
        state = copy.deepcopy(trader.state)
        meter = CreditMeter(state, c, now)
        plan = {"now": now, "notes": [], "results": [], "paused": None, "prices": {},
                "signals": []}

        # Winners: free DexScreener data, every run.
        pairs = api.pairs_for_tokens(
            list(dict.fromkeys([p["address"] for p in trader.open_positions]
                               + find_candidates(api.latest_profiles(), api.latest_boosts()))))
        winners = {w["address"]: w for w in state.get("winners", [])
                   if (now - datetime.fromisoformat(w["seen"])).days < 7}
        for p in pairs:
            base = (p.get("baseToken") or {}).get("address")
            change = to_float((p.get("priceChange") or {}).get("h24"))
            liq = to_float((p.get("liquidity") or {}).get("usd"))
            if (base and change is not None and change >= c["winner_min_change_24h_pct"]
                    and liq is not None and liq >= c["winner_min_liquidity_usd"]):
                winners[base] = {"address": base, "symbol": p["baseToken"].get("symbol", "?"),
                                 "change": change, "seen": now.isoformat()}
        state["winners"] = sorted(winners.values(), key=lambda w: -w["change"])[:50]

        # Prices for open positions: free DexScreener data (works while paused).
        for pos in trader.open_positions:
            pair = next((p for p in pairs if p.get("pairAddress") == pos["pair_address"]), None)
            pair = pair or best_pair(pairs, pos["address"], [])
            price = to_float((pair or {}).get("priceUsd"))
            if price:
                plan["prices"][pos["address"]] = price

        if not (self.api_key or self.rpc_factory):
            plan["notes"].append("not active: add the HELIUS_API_KEY secret (see README)")
            plan["state"] = state
            return plan

        helius, live = self._rpcs(meter)
        try:
            self._live(state, live, meter, now, plan)
            self._refresh(state, api, helius, meter, now, plan)
        except BudgetPaused as exc:
            plan["paused"] = f"{exc}; paused until {meter.end:%Y-%m-%d} (next Helius cycle)"
            state["paused_until"] = meter.end.isoformat()
        except RateLimited as exc:
            plan["notes"].append(f"stopped early this run: {exc}")
        except ApiError as exc:
            plan["notes"].append(f"stopped early this run: {exc}")
        finally:
            state["helius"] = meter.export()
            plan["credits_this_run"] = helius.calls * helius.per_call

        if plan["paused"] is None and state.get("paused_until"):
            if now >= datetime.fromisoformat(state["paused_until"]):
                state.pop("paused_until")
        plan["state"] = state
        if plan["paused"]:
            return plan  # no new entries while paused
        try:
            self._signals(state, api, pairs, now, plan)
        except ApiError as exc:  # includes RateLimited; credits spent above are still saved
            plan["results"] = []
            plan["notes"].append(f"entry checks failed this run: {exc}")
        return plan

    def _live(self, state, rpc, meter, now, plan):
        c = self.c
        tracked = state.get("tracked") or []
        if state.get("paused_until") and now < datetime.fromisoformat(state["paused_until"]):
            raise BudgetPaused("Helius budget for this cycle already used")
        if not tracked:
            plan["notes"].append("no tracked wallets yet (the weekly list is being built)")
            return
        if rpc.per_call and meter.used + len(tracked) * rpc.per_call > meter.cap:
            raise BudgetPaused("not enough Helius credits left for a full live check")

        last_sig = state.setdefault("last_sig", {})
        buys = state.setdefault("recent_buys", {})
        held = {p["address"]: p for p in self.trader.open_positions}
        sells_seen = state.setdefault("sells_seen", {})
        horizon = now.timestamp() - c["window_minutes"] * 60 * 3
        decoded = 0
        for w in tracked:
            wallet = w["wallet"]
            sigs = rpc.signatures(wallet, c["max_new_tx_per_wallet"], until=last_sig.get(wallet))
            if not sigs:
                continue
            first_look = wallet not in last_sig
            last_sig[wallet] = sigs[0]["signature"]
            if first_look:
                continue  # just remember where we are; don't decode the backlog
            for s in sigs:
                if s.get("err") or (s.get("blockTime") or 0) < horizon:
                    continue
                if decoded >= c["max_decodes_per_run"]:
                    if "decode limit reached this run" not in plan["notes"]:
                        plan["notes"].append("decode limit reached this run")
                    break
                decoded += 1
                for swap in decode_swaps(rpc.transaction(s["signature"]), wallet):
                    mint = swap["mint"]
                    if swap["side"] == "buy":
                        buys.setdefault(mint, {})[wallet] = swap["time"]
                    elif mint in held:
                        sells_seen.setdefault(mint, [])
                        if wallet not in sells_seen[mint]:
                            sells_seen[mint].append(wallet)
        # forget buys that can no longer be part of a signal
        state["recent_buys"] = {m: {w: t for w, t in ws.items() if t >= horizon}
                                for m, ws in buys.items()}
        state["recent_buys"] = {m: ws for m, ws in state["recent_buys"].items() if ws}
        state["sells_seen"] = {m: ws for m, ws in sells_seen.items() if m in held}

    def _refresh(self, state, api, helius, meter, now, plan):
        """Rebuild the tracked list, a few wallets per run."""
        c = self.c
        listed = state.get("list_updated")
        due = not listed or now - datetime.fromisoformat(listed) >= timedelta(days=7)
        job = state.get("refresh")
        if not job and not due:
            return
        # Keep enough credits for live checks for the rest of the cycle.
        per_run_live = len(state.get("tracked") or []) * CREDITS_PER_CALL * 1.5 \
            if c["live_rpc"] == "helius" else 0
        reserve = per_run_live * meter.runs_left()
        per_wallet = CREDITS_PER_CALL * (c["max_tx_per_candidate"] + 1)  # worst case
        budget = min(c["refresh_credits_per_run"], meter.cap - meter.used - reserve)
        if budget < per_wallet:
            plan["notes"].append("weekly list refresh waiting: credits reserved for live checks")
            return

        if not job:
            candidates = {}
            for win in state.get("winners", [])[:c["winners_per_refresh"]]:
                try:
                    report = api.rugcheck_report(win["address"])
                except RateLimited:
                    raise
                except ApiError:
                    continue
                if not report:
                    continue
                creator = report.get("creator")
                for h in real_holders(report, None, {})[:c["holders_per_winner"]]:
                    owner = h.get("owner") or h.get("address")
                    if owner and owner != creator and not h.get("insider"):
                        candidates[owner] = candidates.get(owner, 0) + 1
            order = sorted(candidates, key=lambda w: -candidates[w])[:c["candidates_per_refresh"]]
            job = {"started": now.isoformat(), "queue": order, "scored": {}}
            state["refresh"] = job
            plan["notes"].append(f"weekly list refresh started: {len(order)} candidate wallets")

        start_used = meter.used
        since = now.timestamp() - c["history_days"] * 86400
        while job["queue"]:
            if meter.used - start_used + per_wallet > budget:
                break
            wallet = job["queue"][0]
            sigs = helius.signatures(wallet, c["max_tx_per_candidate"] + 1)
            recent = [s for s in sigs if not s.get("err") and (s.get("blockTime") or 0) >= since]
            if len(recent) > c["max_tx_per_candidate"]:
                stats = {"too_active": True, "swaps": len(recent), "closed": 0,
                         "realized_sol": 0.0, "win_rate": 0.0, "top_share": 100.0, "wins": 0}
            else:
                swaps = []
                for s in recent:
                    swaps += decode_swaps(helius.transaction(s["signature"]), wallet)
                stats = score_trader(swaps)
            job["scored"][wallet] = stats
            job["queue"].pop(0)

        if not job["queue"]:
            good = [(w, s) for w, s in job["scored"].items() if qualifies(s, c)[0]]
            good.sort(key=lambda ws: -ws[1]["realized_sol"])
            state["tracked"] = [dict(s, wallet=w) for w, s in good[:c["tracked_wallets"]]]
            state["list_updated"] = now.isoformat()
            state["last_sig"] = {w["wallet"]: state.get("last_sig", {}).get(w["wallet"])
                                 for w in state["tracked"]
                                 if state.get("last_sig", {}).get(w["wallet"])}
            state.pop("refresh", None)
            plan["notes"].append(f"weekly list refreshed: {len(state['tracked'])} of "
                                 f"{len(job['scored'])} candidates qualified")

    def _signals(self, state, api, pairs, now, plan):
        """3+ tracked wallets bought the same token within the window."""
        c = self.c
        window = c["window_minutes"] * 60
        for mint, wallets in (state.get("recent_buys") or {}).items():
            times = sorted(wallets.values())
            best = []
            for i, start in enumerate(times):
                group = [t for t in times[i:] if t - start <= window]
                if len(group) > len(best):
                    best = group
            if len(best) < c["min_wallets"]:
                continue
            if now.timestamp() - best[-1] > c["max_signal_age_minutes"] * 60:
                continue  # it converged too long ago
            if not self.trader.can_buy(mint):
                continue
            who = sorted(w for w, t in wallets.items() if best[0] <= t <= best[-1])
            plan["signals"].append({"mint": mint, "wallets": who,
                                    "first": best[0], "last": best[-1]})

        for sig in plan["signals"]:
            mint = sig["mint"]
            found = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
            if not found:
                found = api.pairs_for_tokens([mint])
            pair = best_pair(found, mint, [])
            checks = [Check(f"{c['min_wallets']}+ tracked wallets bought", PASS,
                            f"{len(sig['wallets'])} within "
                            f"{(sig['last'] - sig['first']) / 60:.0f} min")]
            price = to_float((pair or {}).get("priceUsd"))
            checks.append(Check("Price available", PASS if price else FAIL,
                                "no DexScreener pair" if not pair else f"${price:.10g}"
                                if price else "no price"))
            liq = to_float(((pair or {}).get("liquidity") or {}).get("usd"))
            ok = liq is not None and liq >= c["min_liquidity_usd"]
            checks.append(Check("Liquidity", PASS if ok else FAIL,
                                f"{money(liq)} (need at least {money(c['min_liquidity_usd'])})"))
            try:
                report = api.rugcheck_report(mint)
            except RateLimited:
                raise
            except ApiError:
                report = None
            token = (report or {}).get("token") or {}
            for label, key in (("Mint authority revoked", "mintAuthority"),
                               ("Freeze authority revoked", "freezeAuthority")):
                if not report:
                    checks.append(Check(label, FAIL, "no RugCheck report"))
                    continue
                value = token.get(key, report.get(key))
                checks.append(Check(label, PASS if not value else FAIL,
                                    "revoked" if not value else "still active"))
            base = (pair or {}).get("baseToken") or {}
            result = Result(mint, base.get("symbol", "?"), base.get("name", "?"), pair, checks)
            result.wallets = sig["wallets"]
            plan["results"].append(result)

    # ---- the paper trades ----

    def apply(self, plan, out=print):
        from screener.filters import format_report

        trader, now = self.trader, plan["now"]
        # The plan's state replaces everything except the trade records, so
        # keys the fetch step removed (a finished refresh, a lifted pause) go too.
        kept = {k: trader.state[k] for k in ("open_positions", "ever_bought",
                                              "running_total_pnl_usd") if k in trader.state}
        trader.state.clear()
        trader.state.update({k: v for k, v in plan["state"].items() if k not in kept})
        trader.state.update(kept)

        meter = trader.state.get("helius") or {}
        if meter:
            out(f"  Helius credits this cycle: {meter['used']:,} of the {meter['cap']:,} "
                f"allowed ({meter['pause_at_pct']:g}% of {meter['monthly']:,}); "
                f"{plan.get('credits_this_run', 0):,} this run")
        tracked = trader.state.get("tracked") or []
        out(f"  Tracking {len(tracked)} wallet(s)"
            + (f", list from {trader.state['list_updated'][:10]}"
               if trader.state.get("list_updated") else ""))
        job = trader.state.get("refresh")
        if job:
            out(f"  Weekly list refresh: {len(job['scored'])} scored, "
                f"{len(job['queue'])} to go")
        if plan["paused"]:
            out(f"  PAUSED: {plan['paused']}")
        for note in plan["notes"]:
            out(f"  ({note})")
        out("")

        # wallets that sold what we hold
        for pos in trader.open_positions:
            sold = [w for w in (trader.state.get("sells_seen") or {}).get(pos["address"], [])
                    if w in (pos.get("wallets") or [])]
            pos["sold_by"] = sold

        for s in trader.update(plan["prices"], when=now):
            out(f"  SELL {s['symbol']:<10} {s['reason']:<45} P&L ${s['pnl_usd']:+.2f}")

        for r in plan["results"]:
            out(format_report(r))
            out("")
            if not r.passed:
                continue
            pos = trader.buy(r, when=now)
            if pos:
                pos["wallets"] = r.wallets
                out(f"  BUY  {r.symbol:<10} ${self.pt['buy_amount_usd']} at ${r.price:.10g}")
        if not plan["results"]:
            out("  No convergence this run, so nothing was bought.")
        trader.save()
