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
2. The list. Every day, wallets that recently sold the week's winners
   (GeckoTerminal trades, free) and their biggest holders (RugCheck, free)
   become candidates; wallets already scored in the last week are skipped.
   Each candidate's last 14 days of swaps are read from Helius and their
   realized profit is worked out (a wallet with too few transactions to
   ever close enough trades isn't read). Wallets that trade too often
   (bots), made most of their profit on one token, or didn't close enough
   trades are dropped. Every one that qualifies joins the tracked list (the
   most profitable 50 stay); each tracked wallet is scored again every week
   and leaves the list if it no longer qualifies. This work is spread over
   many runs, within a daily share of the credits.
3. Live. Every 15 minutes (helius_every_minutes), each tracked wallet's new
   transactions are read from Helius and decoded into buys and sells. When
   3+ tracked wallets bought the same token within 20 minutes, and the last
   of those buys was in the last 20 minutes, the token is paper-bought if it
   passes basic checks. Open positions are checked on every run.
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
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta

import requests

from screener.api import ApiError, RateLimited
from screener.filters import (FAIL, PASS, Check, Result, best_pair, find_candidates,
                              insider_status, money, real_holders, to_float)
from screener.paper_trader import PaperTrader, now_utc
from screener.token_record import CandidateLog, CreatorLedger, record_fields

HELIUS_RPC = "https://mainnet.helius-rpc.com/?api-key={}"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
           "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}   # USDT


class BudgetPaused(Exception):
    """Making this call would take Helius usage past the pause limit."""


class RpcError(ApiError):
    """The RPC server answered with an error (the message never has the URL)."""

    def __init__(self, text, server_message=""):
        super().__init__(text)
        self.server_message = server_message


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
        # The count is an estimate (see helius_*_credits_per_call). If those
        # estimates change, rescale what was counted so far by the history
        # rate (the higher one), so the count stays on the safe side.
        rates = {"live": c["helius_live_credits_per_call"],
                 "history": c["helius_history_credits_per_call"]}
        old = (meter.get("rates") or {}).get("history", 10)  # 10 before calibration
        if meter.get("used") and old != rates["history"]:
            factor = rates["history"] / old
            meter["used"] = int(round(meter["used"] * factor))
            meter["by_day"] = {d: int(round(n * factor)) for d, n in meter["by_day"].items()}
            meter["recalibrated"] = f"x{factor:g} on {now:%Y-%m-%d %H:%M} UTC"
        meter["rates"] = rates
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
        return max(1, (self.end - self.now).total_seconds() / 60 / self.c["helius_every_minutes"])

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
            message = str(body["error"].get("message"))
            raise RpcError(f"{self.name} {method}: {message[:120]}", message)
        return body.get("result")

    def signatures(self, address, limit, until=None):
        opts = {"limit": limit}
        if until:
            opts["until"] = until
        return self.call("getSignaturesForAddress", [address, opts]) or []

    max_version = 0  # raised automatically if the server asks for a newer one

    def transaction(self, signature):
        try:
            return self.call("getTransaction", [signature, {
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": self.max_version}])
        except RpcError as exc:
            # e.g. "Transaction version (1) is not supported by the requesting
            # client. Please try the request again with the following
            # configuration parameter: "maxSupportedTransactionVersion": 1"
            wanted = re.search(r'maxSupportedTransactionVersion"?\s*:\s*(\d+)',
                               exc.server_message)
            if not wanted or int(wanted.group(1)) <= self.max_version:
                raise
            self.max_version = int(wanted.group(1))
            return self.call("getTransaction", [signature, {
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": self.max_version}])


def read_transaction(rpc, signature, plan):
    """One transaction, or None if the server can't return it. Unreadable
    transactions are skipped (and counted) instead of stopping the run."""
    try:
        return rpc.transaction(signature)
    except RateLimited:
        raise
    except RpcError:
        plan["unreadable"] = plan.get("unreadable", 0) + 1
        return None


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
    if stats.get("error"):
        return False, "couldn't read their history"
    if stats.get("too_active"):
        return False, "trades too often (bot?)"
    if stats.get("few_tx"):
        return False, f"only {stats['transactions']} transactions (too few for enough closed trades)"
    if stats["closed"] < c["min_closed_trades"]:
        return False, f"only {stats['closed']} closed trade(s)"
    if stats["realized_sol"] < c["min_realized_sol"]:
        return False, f"realized {stats['realized_sol']:+.2f} SOL"
    if stats["win_rate"] < c["min_win_rate_pct"]:
        return False, f"win rate {stats['win_rate']:.0f}%"
    if stats["top_share"] > c["max_top_token_share_pct"]:
        return False, f"{stats['top_share']:.0f}% of profit from one token"
    return True, "ok"


def list_summary(job, c):
    """Why candidates did or didn't qualify, and how many swaps were found,
    e.g. "26 too few closed trades, 3 trades too often (bot?); 41 swaps in
    812 transactions"."""
    reasons = defaultdict(int)
    for stats in job["scored"].values():
        ok, why = qualifies(stats, c)
        if ok:
            why = "qualified"
        elif why.startswith("only "):
            why = "too few closed trades"
        elif why.startswith("realized"):
            why = "not enough profit"
        elif why.startswith("win rate"):
            why = "low win rate"
        elif "one token" in why:
            why = "profit from one token"
        reasons[why] += 1
    parts = ", ".join(f"{n} {why}" for why, n in sorted(reasons.items(), key=lambda r: -r[1]))
    return (f"{parts or 'no candidates'}; {job.get('swaps', 0)} swaps in "
            f"{job.get('transactions', 0)} transactions")


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
        # Recording only (screener/token_record.py): candidates.csv (a row for
        # every converged token the first time it's checked, and its price 1, 6
        # and 24 hours later) and the creator ledger.
        self.candidates = CandidateLog(os.path.join(data_folder, "convergence"), "convergence")
        self.ledger = CreatorLedger(
            os.path.join(data_folder, "convergence", "creator_ledger.json"),
            os.path.join(data_folder, "early", "positions.json"))
        self.trader.ledger = self.ledger
        self.api_key = api_key
        self.rpc_factory = rpc_factory  # tests and --demo pass a fake here

    def _rpcs(self, meter):
        if self.rpc_factory:
            return self.rpc_factory(meter)
        spacing = 1 / self.c["helius_max_requests_per_second"]
        url = HELIUS_RPC.format(self.api_key)
        history = Rpc(url, "Helius", meter, self.c["helius_history_credits_per_call"],
                      min_interval=spacing)
        if self.c["live_rpc"] == "public":
            live = Rpc(PUBLIC_RPC, "public Solana RPC", min_interval=0.3)
        else:
            live = Rpc(url, "Helius", meter, self.c["helius_live_credits_per_call"],
                       min_interval=spacing)
        return history, live

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
                                 "change": change, "seen": now.isoformat(),
                                 "pair": p.get("pairAddress")}
        state["winners"] = sorted(winners.values(), key=lambda w: -w["change"])[:50]

        # Prices for open positions: free DexScreener data (works while paused).
        for pos in trader.open_positions:
            pair = next((p for p in pairs if p.get("pairAddress") == pos["pair_address"]), None)
            pair = pair or best_pair(pairs, pos["address"], [])
            price = to_float((pair or {}).get("priceUsd"))
            if price:
                plan["prices"][pos["address"]] = price

        # Later prices for the candidates log: DexScreener's free batched call,
        # only when a checkpoint is due. Recording only: a failure changes nothing.
        try:
            plan["reprice"] = self.candidates.due(now)
            plan["reprice_pairs"] = api.pairs_for_tokens(list(plan["reprice"])) \
                if plan["reprice"] else []
        except ApiError as exc:
            plan["reprice"], plan["reprice_pairs"] = {}, []
            plan["notes"].append(f"candidate prices skipped this run: {exc}")

        if not (self.api_key or self.rpc_factory):
            plan["notes"].append("not active: add the HELIUS_API_KEY secret (see README)")
            plan["state"] = state
            return plan

        # Helius only on runs at least helius_every_minutes apart (2 min slack
        # for GitHub's start-time jitter), however often the workflow runs.
        last = state.get("last_helius_check")
        gap = self.c["helius_every_minutes"] - 2
        if last and now - datetime.fromisoformat(last) < timedelta(minutes=gap):
            nxt = datetime.fromisoformat(last) + timedelta(minutes=gap)
            plan["notes"].append(f"Helius checked at {last[11:16]} UTC; next check from "
                                 f"{nxt:%H:%M} UTC (every {self.c['helius_every_minutes']} min)")
            plan["state"] = state
            if not state.get("paused_until"):
                try:
                    self._signals(state, api, pairs, now, plan)
                except ApiError as exc:
                    plan["results"] = []
                    plan["notes"].append(f"entry checks failed this run: {exc}")
            return plan
        state["last_helius_check"] = now.isoformat()

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
            clients = [helius] if live is helius else [helius, live]
            plan["credits_this_run"] = sum(r.calls * r.per_call for r in clients)
            if plan.get("unreadable"):
                plan["notes"].append(f"skipped {plan['unreadable']} transaction(s) Helius "
                                     "couldn't return")

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
            plan["notes"].append("no tracked wallets yet (the list is being built)")
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
                for swap in decode_swaps(read_transaction(rpc, s["signature"], plan), wallet):
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
        """Grow and refresh the tracked list, a few wallets per run: score
        candidate wallets (recent sellers and top holders of the week's
        winners), and re-score tracked wallets every recheck_days. Every
        wallet that qualifies joins the list right away (the best
        tracked_wallets by realized profit); a tracked wallet that no longer
        qualifies leaves it. A new round of candidates starts every
        refresh_every_hours. Credits: only today's share of what's left in
        the cycle after reserving the live checks."""
        c = self.c
        listed = state.get("list_updated")
        age = now - datetime.fromisoformat(listed) if listed else None
        due = age is None or age >= timedelta(hours=c["refresh_every_hours"])
        job = state.get("refresh")
        if not job and not due:
            return
        # Keep enough credits for live checks of the list for the rest of the
        # cycle; the rest is spread evenly over the days left.
        per_run_live = len(state.get("tracked") or []) * c["helius_live_credits_per_call"] * 1.5 \
            if c["live_rpc"] == "helius" else 0
        reserve = per_run_live * meter.runs_left()
        today = now.date().isoformat()
        spent = {d: n for d, n in (state.get("refresh_spent") or {}).items() if d >= (
            now - timedelta(days=40)).date().isoformat()}
        days_left = max(1.0, (meter.end - now).total_seconds() / 86400)
        share = (meter.left() - reserve + spent.get(today, 0)) / days_left
        per_wallet = c["helius_history_credits_per_call"] * (c["max_tx_per_candidate"] + 1)
        budget = min(c["refresh_credits_per_run"], meter.left() - reserve,
                     share - spent.get(today, 0))
        if budget < per_wallet:
            plan["notes"].append("list refresh waiting: "
                                 + ("credits reserved for live checks"
                                    if meter.left() - reserve < per_wallet
                                    else "today's share of the credits is used"))
            return
        if not job:
            job = self._new_round(state, now)
            state["refresh"] = job
            plan["notes"].append(f"list refresh started: candidates from "
                                 f"{len(job['winners'])} winner(s), "
                                 f"{c['winners_per_run']} a run"
                                 + (f"; {len(job['queue'])} tracked wallet(s) to re-check"
                                    if job["queue"] else ""))
        if job.get("winners"):
            self._gather(job, state, api, now, plan)

        start_used = meter.used
        since = now.timestamp() - c["history_days"] * 86400
        try:
            while job["queue"]:
                if meter.used - start_used + per_wallet > budget:
                    break
                wallet = job["queue"][0]
                try:
                    sigs = helius.signatures(wallet, c["max_tx_per_candidate"] + 1)
                except RpcError as exc:
                    # Don't let one wallet block the list: record it and move on.
                    job["scored"][wallet] = {"error": str(exc)[:80], "closed": 0, "wins": 0,
                                             "realized_sol": 0.0, "win_rate": 0.0,
                                             "top_share": 100.0, "swaps": 0}
                    job["queue"].pop(0)
                    continue
                recent = [s for s in sigs
                          if not s.get("err") and (s.get("blockTime") or 0) >= since]
                if len(recent) > c["max_tx_per_candidate"]:
                    stats = {"too_active": True, "swaps": len(recent), "closed": 0,
                             "realized_sol": 0.0, "win_rate": 0.0, "top_share": 100.0, "wins": 0}
                elif len(recent) < 2 * c["min_closed_trades"]:
                    # Each closed trade needs a buy and a sell in the window:
                    # too few transactions can never pass, so they aren't read.
                    stats = {"few_tx": True, "transactions": len(recent), "swaps": 0,
                             "closed": 0, "realized_sol": 0.0, "win_rate": 0.0,
                             "top_share": 100.0, "wins": 0}
                else:
                    swaps = []
                    for s in recent:
                        swaps += decode_swaps(read_transaction(helius, s["signature"], plan),
                                              wallet)
                    stats = score_trader(swaps)
                    job["transactions"] = job.get("transactions", 0) + len(recent)
                    job["swaps"] = job.get("swaps", 0) + len(swaps)
                job["scored"][wallet] = stats
                job["queue"].pop(0)
                self._merge(state, wallet, stats, now, plan)
        finally:
            spent[today] = spent.get(today, 0) + meter.used - start_used
            state["refresh_spent"] = spent

        if not job["queue"] and not job.get("winners"):
            state["list_updated"] = now.isoformat()
            state.pop("refresh", None)
            summary = list_summary(job, c)
            state["list_summary"] = summary
            plan["notes"].append(f"list refreshed: tracking {len(state['tracked'])} wallet(s); "
                                 f"{summary}")

    def _merge(self, state, wallet, stats, now, plan):
        """A newly scored wallet: onto the list if it qualifies (the best
        tracked_wallets by realized profit stay), off it if it was tracked
        and no longer qualifies. A wallet that couldn't be read keeps its
        place. Every scored wallet is remembered for recheck_days."""
        c = self.c
        state.setdefault("checked", {})[wallet] = now.isoformat()
        tracked = {w["wallet"]: w for w in state.get("tracked") or []}
        ok, why = qualifies(stats, c)
        if ok:
            tracked[wallet] = dict(stats, wallet=wallet, scored=now.isoformat())
        elif wallet in tracked and not stats.get("error"):
            tracked.pop(wallet)
            plan.setdefault("dropped", []).append(wallet)
            plan["notes"].append(f"{wallet[:6]}... left the list on its re-check: {why}")
        best = sorted(tracked.values(), key=lambda w: -w["realized_sol"])[:c["tracked_wallets"]]
        state["tracked"] = best
        keep = {w["wallet"] for w in best}
        state["last_sig"] = {w: sig for w, sig in (state.get("last_sig") or {}).items()
                             if w in keep}

    def _new_round(self, state, now):
        """A new round of the list: the tracked wallets due a re-check go
        first; candidates come from the week's top winners (the ones not used
        in the last winner_reuse_days first), read winners_per_run a run
        (_gather) so a run never asks GeckoTerminal much."""
        c = self.c
        recheck = timedelta(days=c["recheck_days"])
        listed = state.get("list_updated")
        due = [w["wallet"] for w in state.get("tracked") or []
               if (w.get("scored") or listed) is None
               or now - datetime.fromisoformat(w.get("scored") or listed) >= recheck]
        used = {a: t for a, t in (state.get("winners_used") or {}).items()
                if now - datetime.fromisoformat(t) < timedelta(days=7)}
        reuse = timedelta(days=c["winner_reuse_days"])
        winners = sorted(state.get("winners", []),
                         key=lambda w: (w["address"] in used
                                        and now - datetime.fromisoformat(used[w["address"]])
                                        < reuse, -w["change"]))[:c["winners_per_refresh"]]
        for w in winners:
            used[w["address"]] = now.isoformat()
        state["winners_used"] = used
        return {"started": now.isoformat(), "queue": due, "rechecks": len(due),
                "winners": [dict(w) for w in winners], "read": 0, "counts": {},
                "sellers": [], "scored": {}, "transactions": 0, "swaps": 0}

    def _gather(self, job, state, api, now, plan):
        """Candidates from the next winners_per_run winners: wallets that
        recently SOLD it (GeckoTerminal trades, free) - they've closed trades
        to judge - and its biggest holders (RugCheck, free). Once every
        winner is read, the candidates join the queue: wallets seen on more
        winners first, sellers before holders, and none scored in the last
        recheck_days."""
        c = self.c
        batch = job["winners"][:c["winners_per_run"]]
        missing = [w["address"] for w in batch if not w.get("pair")]
        pools = {}
        if missing:
            try:
                found = api.pairs_for_tokens(missing)
            except RateLimited:
                raise
            except ApiError:
                found = []
            for addr in missing:
                pools[addr] = (best_pair(found, addr, []) or {}).get("pairAddress")
        counts, sellers = job["counts"], set(job["sellers"])
        for win in batch:
            creator = None
            try:
                report = api.rugcheck_report(win["address"])
            except RateLimited:
                raise
            except ApiError:
                report = None
            if report:
                creator = report.get("creator")
                for h in real_holders(report, None, {})[:c["holders_per_winner"]]:
                    owner = h.get("owner") or h.get("address")
                    if owner and owner != creator and not h.get("insider"):
                        counts[owner] = counts.get(owner, 0) + 1
            pool = win.get("pair") or pools.get(win["address"])
            if pool:
                try:
                    trades = api.gecko_pool_trades(pool)
                except ApiError:  # includes rate limits: just use the holders
                    trades = []
                sold = defaultdict(float)
                for t in trades:
                    wallet = t.get("tx_from_address")
                    usd = to_float(t.get("volume_in_usd")) or 0.0
                    if (t.get("kind") == "sell" and wallet and wallet != creator
                            and usd >= c["min_seller_trade_usd"]):
                        sold[wallet] += usd
                for wallet in sorted(sold, key=lambda w: -sold[w])[:c["sellers_per_winner"]]:
                    counts[wallet] = counts.get(wallet, 0) + 1
                    sellers.add(wallet)
            job["winners"].pop(0)
            job["read"] += 1
        job["sellers"] = sorted(sellers)
        if job["winners"]:
            return
        recheck = timedelta(days=c["recheck_days"])
        checked = {w: t for w, t in (state.get("checked") or {}).items()
                   if now - datetime.fromisoformat(t) < recheck}
        state["checked"] = checked
        queued = set(job["queue"]) | {w["wallet"] for w in state.get("tracked") or []}
        fresh = [w for w in counts if w not in checked and w not in queued]
        skipped = sum(1 for w in counts if w in checked and w not in queued)
        # More winners first; on a tie, sellers before holders.
        fresh = sorted(fresh, key=lambda w: (-counts[w], w not in sellers))
        fresh = fresh[:c["candidates_per_refresh"]]
        job["queue"] += fresh
        job.pop("counts")
        job.pop("sellers")
        n_sell = sum(1 for w in fresh if w in sellers)
        plan["notes"].append(
            f"list refresh: {len(fresh)} new candidate wallets to score ({n_sell} recent "
            f"sellers, {len(fresh) - n_sell} top holders of {job['read']} winners"
            + (f"; {skipped} scored in the last {c['recheck_days']} days skipped"
               if skipped else "")
            + (f"; {job['rechecks']} tracked wallet(s) to re-check" if job["rechecks"] else "")
            + ")")

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
            result.insider = insider_status(report)
            result.report = report
            try:
                result.record = record_fields(report, pair, {})   # recording only
            except Exception:
                result.record = None
            plan["results"].append(result)

    def _record(self, plan, bought, now):
        """candidates.csv and the creator ledger, after the trades are saved.
        Recording only: a failure here is noted and changes nothing."""
        try:
            for r in plan["results"]:
                self.candidates.add(
                    r, getattr(r, "report", None), getattr(r, "record", None), now,
                    "PASS" if r.passed else "FAIL",
                    "; ".join(f"{c.name}: {c.detail}" for c in r.checks if c.status == "FAIL"),
                    True, "convergence=" + ("bought" if bought.get(r.address) else
                                            "not bought" if r.passed else "failed checks"),
                    self.ledger, wallets=len(getattr(r, "wallets", []) or []))
            if plan.get("reprice"):
                self.candidates.fill(plan["reprice"], plan.get("reprice_pairs") or [], now, [],
                                     self.ledger)
            self.ledger.save()
        except Exception as exc:
            print(f"  (candidate record skipped this run: {exc})")

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
            out(f"  List refresh: {len(job['scored'])} scored, {len(job['queue'])} to go"
                + (f", {len(job['winners'])} winner(s) still to read for candidates"
                   if job.get("winners") else ""))
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

        bought = {}
        for r in plan["results"]:
            out(format_report(r))
            out("")
            if not r.passed:
                continue
            pos = trader.buy(r, when=now)
            if pos:
                pos["wallets"] = r.wallets
                bought[r.address] = True
                out(f"  BUY  {r.symbol:<10} ${self.pt['buy_amount_usd']} at ${r.price:.10g}")
        if not plan["results"]:
            out("  No convergence this run, so nothing was bought.")
        trader.save()
        self._record(plan, bought, now)
