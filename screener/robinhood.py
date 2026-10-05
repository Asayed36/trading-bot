"""The "robinhood" paper strategy: graduated memecoins on Robinhood Chain.

Robinhood Chain (chain 4663) is an EVM chain. Its biggest memecoin
launchpads are Pons (a pump.fun-style bonding curve that graduates into a
Uniswap v4 pool) and Pools.trade (Uniswap Labs' launchpad, Uniswap v4 pools).
This strategy only trades tokens AFTER they reach a Uniswap pool, while that
pool is 30 minutes to 6 hours old. What the free sources return was measured
first with robinhood_probe.py.

PAPER trading only. It only READS public data: GET requests to public
websites and read-only JSON-RPC calls (the four in RPC_METHODS). It never
connects a wallet, never uses a private key, never signs or sends anything.

Each run:
  1. Prices for open positions from DexScreener.
  2. New pools from GeckoTerminal (which lists the launchpads as DEXes:
     "pons-v2-dex" = graduated Pons pools, "uniswap-pools-trade" =
     Pools.trade). GeckoTerminal only allows a few calls a minute from
     GitHub's runners, so at most gecko_calls_per_run calls, spaced out, with
     one retry after a 429; the pools seen are kept in a watchlist so later
     runs can check them once they're old enough. Pons' graduations come
     from the chain (step 5): every one goes on the watchlist, named (and
     later priced) from DexScreener, so its GeckoTerminal list is only read
     when there are calls to spare. Every graduation gets the same checks.
  3. Each pool aged 30 min - 6 h is checked, cheap checks first (each one
     only when the ones before passed, so a run stays within the free limits):
       - Pool age and minimum liquidity (DexScreener, the same pool; the
         minimum is per launchpad)
       - Market (DexScreener, the same pool): market cap at least $25,000,
         not down more than 50% in 24 hours, more buys than sells in the
         last hour
       - Not a copycat: no other Pons or Pools.trade token with the same name
         or symbol graduated before it in the last 7 days (ignoring later
         ones, and clones with liquidity of 90%+ of their market cap)
       - GoPlus: not a honeypot, not mintable, no hidden owner, owner can't
         change balances, no blacklist (unknown counts as a fail)
       - Pons tokens only: holders rebuilt from the token's Transfer events on
         the public RPC: the creator holds under 5%, the top 10 hold under
         30% (pools, launchpad contracts and burn addresses left out), and no
         cluster of 5+ near-equal balances holding 3%+ together (bundled
         buys). A 429 from the RPC is retried after a pause.
  4. A token that passes everything is paper-bought, with the pool fee,
     slippage and gas on the buy and on every sell. Exits are main's.
  5. Read-only: the Pons tokens that graduated on the chain in the last 24
     hours (the graduation event's logs: the whole day once, then only the
     new blocks each run, usually one call, never waiting on a 429), for
     step 2 and the run log.

Every check value at the moment of a buy goes to entries.csv (blank =
unknown); every checked candidate to candidates.csv (when its result
changes).
"""

import copy
import csv
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from screener.api import ApiError, RateLimited
from screener.filters import FAIL, PASS, Check, money, to_float
from screener.paper_trader import PaperTrader, append_row, now_utc, pct

CHAIN_ID = 4663
DEXSCREENER = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"
GOPLUS = "https://api.gopluslabs.io/api/v1"

HEADERS = {"User-Agent": "memecoin-screener/1.0 (read-only paper trading)"}
# The only JSON-RPC calls this strategy makes (all read-only).
RPC_METHODS = {"eth_blockNumber", "eth_getBlockByNumber", "eth_getLogs",
               "eth_getTransactionByHash"}
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# Watchlist key of a graduation found on the chain (its pool comes from
# DexScreener when it's checked).
ONCHAIN = "onchain:"
ZERO = "0x" + "0" * 40
BURN = {ZERO, "0x000000000000000000000000000000000000dead"}
SOURCES = ("geckoterminal", "dexscreener", "goplus", "rpc")

# GoPlus fields that must be "0", and what the check is called.
GOPLUS_FLAGS = (("is_honeypot", "Not a honeypot"), ("is_mintable", "Not mintable"),
                ("hidden_owner", "No hidden owner"),
                ("owner_change_balance", "Owner can't change balances"),
                ("is_blacklisted", "No blacklist"))
GOPLUS_INFO = ("buy_tax", "sell_tax", "cannot_sell_all", "is_open_source", "owner_address")

# What's known about a token when it's checked: every value goes to
# candidates.csv and (for buys) entries.csv. Blank = unknown or not checked.
VALUE_COLUMNS = [
    "symbol", "token_address", "launchpad", "pool_address", "price_usd", "pool_age_minutes",
    "liquidity_usd", "market_cap_usd", "buys_1h", "sells_1h", "price_change_5m_pct",
    "price_change_1h_pct", "price_change_24h_pct", "copycat_of",
    *(f"goplus_{k}" for k, _ in GOPLUS_FLAGS), *(f"goplus_{k}" for k in GOPLUS_INFO),
    "creator", "creator_pct", "top10_pct", "holders", "equal_group_size", "equal_group_pct",
    "holders_complete",
]
ENTRY_COLUMNS = ["time_utc", *VALUE_COLUMNS, "pool_fee_pct", "slippage_pct", "gas_usd"]
CANDIDATE_COLUMNS = ["time_utc", "result", "failed_checks", *VALUE_COLUMNS]


def rpc_request(method, params, request_id=1):
    """A JSON-RPC request, refusing anything that isn't a read-only call."""
    if method not in RPC_METHODS:
        raise ValueError(f"{method} is not an allowed read-only RPC call")
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def rpc_result(body):
    """The result of a JSON-RPC answer. Raises RateLimited when the error
    is "too many requests" (the RPC sends {"code": 429, ...} with HTTP 200),
    ApiError for any other error."""
    error = (body or {}).get("error") if isinstance(body, dict) else "not a JSON-RPC answer"
    if error is None:
        return body.get("result")
    if (isinstance(error, dict) and error.get("code") == 429) \
            or "too many requests" in str(error).lower():
        raise RateLimited(f"Robinhood Chain RPC said 'too many requests': {str(error)[:120]}")
    raise ApiError(f"Robinhood Chain RPC: {str(error)[:160]}")


class RobinhoodHttp:
    """GET requests and read-only JSON-RPC calls, spaced out per source.
    Raises ApiError (RateLimited for HTTP 429); 404 returns None."""

    def __init__(self, rpc_url, timeout=20, gaps=None):
        self.rpc_url = rpc_url
        self.timeout = timeout
        self.gaps = gaps or {}
        self._last = {}

    @classmethod
    def from_config(cls, c, timeout=20):
        return cls(c["rpc_url"], timeout, gaps={
            "geckoterminal": c["gecko_gap_seconds"], "goplus": c["goplus_gap_seconds"],
            "dexscreener": 0.3, "rpc": 0.05})

    def _pace(self, source):
        wait = self._last.get(source, 0) + self.gaps.get(source, 0) - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last[source] = time.time()

    def get(self, source, url, params=None):
        self._pace(source)
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(f"could not reach {url.split('/')[2]}: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimited(f"{url.split('/')[2]} said 'too many requests' (HTTP 429)")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ApiError(f"{url.split('/')[2]} answered with error {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError(f"{url.split('/')[2]} sent something that isn't JSON") from exc

    def rpc(self, method, params):
        payload = rpc_request(method, params)
        self._pace("rpc")
        try:
            resp = requests.post(self.rpc_url, json=payload, headers=HEADERS,
                                 timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(f"Robinhood Chain RPC: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimited("Robinhood Chain RPC said 'too many requests' (HTTP 429)")
        try:
            body = resp.json()
        except ValueError as exc:
            raise ApiError(f"Robinhood Chain RPC: {exc}") from exc
        return rpc_result(body)


# ---------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------

def hex_int(value):
    return int(value, 16) if isinstance(value, str) and value.startswith("0x") else None


def topic_to_address(topic):
    return ("0x" + topic[-40:]).lower() if isinstance(topic, str) and len(topic) == 66 else None


def topic_address(address):
    return "0x" + "0" * 24 + address.lower()[2:]


def _utc(text):
    if not text:
        return None
    when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def name_key(text):
    """Names and symbols compared without case, spaces or punctuation."""
    return re.sub(r"[\W_]+", "", (text or "").lower())


def balances_from_transfers(logs):
    """Token balances rebuilt from ERC-20 Transfer logs (from, to, amount),
    and the total minted (transfers from the zero address)."""
    bal, minted = {}, 0
    for log in logs:
        topics = log.get("topics") or []
        if len(topics) < 3 or topics[0] != TRANSFER:
            continue
        amount = hex_int(log.get("data") or "0x0") or 0
        frm, to = topic_to_address(topics[1]), topic_to_address(topics[2])
        if frm == ZERO:
            minted += amount
        else:
            bal[frm] = bal.get(frm, 0) - amount
        bal[to] = bal.get(to, 0) + amount
    bal.pop(ZERO, None)
    return {a: v for a, v in bal.items() if v > 0}, minted


def equal_groups(balances, tolerance):
    """Groups of near-identical balances (within `tolerance` of each other),
    biggest group first, as lists of balances. Bundled buys often get
    exactly the same amount."""
    values = sorted(b for b in balances if b > 0)
    groups, current = [], []
    for v in values:
        if current and v - current[0] <= current[0] * tolerance:
            current.append(v)
        else:
            if len(current) > 1:
                groups.append(current)
            current = [v]
    if len(current) > 1:
        groups.append(current)
    return sorted(groups, key=lambda g: (-len(g), -sum(g)))


def holder_stats(balances, supply, exclude, creator, c):
    """Creator share, top-10 share and the equal-balance cluster that counts,
    with pools, launchpad contracts and burn addresses left out."""
    supply = supply or sum(balances.values()) or 1
    rows = sorted(((a, v) for a, v in balances.items() if a not in exclude),
                  key=lambda r: -r[1])
    floor = supply * c["cluster_min_holder_pct"] / 100       # ignore dust wallets
    groups = equal_groups([v for _, v in rows if v >= floor], c["cluster_tolerance_pct"] / 100)
    # The cluster that counts: of the groups big enough, the one holding the
    # most; with none big enough, the biggest group (shown, never a fail).
    big = [g for g in groups if len(g) >= c["cluster_min_size"]]
    biggest = max(big, key=sum) if big else (groups[0] if groups else [])
    return {
        "holders": len(rows),
        "creator_pct": round(100 * balances.get(creator, 0) / supply, 3) if creator else None,
        "top10_pct": round(100 * sum(v for _, v in rows[:10]) / supply, 3),
        "top10": [{"wallet": a, "pct": round(100 * v / supply, 3)} for a, v in rows[:10]],
        "equal_group_size": len(biggest),
        "equal_group_pct": round(100 * sum(biggest) / supply, 3) if biggest else 0.0,
    }


def gecko_pools(body, allowed):
    """Pools from a GeckoTerminal pools list, only on the allowed DEXes, with
    the token's name (from the included base tokens), the pool's liquidity
    and the token's market cap (FDV when GeckoTerminal has no market cap)."""
    included = {t.get("id"): t.get("attributes") or {}
                for t in (body or {}).get("included") or [] if t.get("type") == "token"}
    out = []
    for pool in (body or {}).get("data") or []:
        a = pool.get("attributes") or {}
        rel = pool.get("relationships") or {}
        dex = ((rel.get("dex") or {}).get("data") or {}).get("id")
        base = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
        token = base.split("_", 1)[-1].lower()
        if dex in allowed and token.startswith("0x") and a.get("address"):
            info = included.get(base) or {}
            out.append({"pool": a["address"].lower(), "dex": dex, "token": token,
                        "name": (a.get("name") or "").split(" / ")[0].strip(),
                        "title": (info.get("name") or "").strip(),
                        "created": a.get("pool_created_at"),
                        "liquidity_usd": to_float(a.get("reserve_in_usd")),
                        "market_cap_usd": to_float(a.get("market_cap_usd"))
                        or to_float(a.get("fdv_usd"))})
    return out


def pick_pair(pairs, token, pool=None):
    """The DexScreener pair for this pool, else the token's most liquid one."""
    mine = [p for p in pairs if p.get("chainId") == "robinhood"
            and (p.get("baseToken") or {}).get("address", "").lower() == token]
    if pool:
        same = [p for p in mine if (p.get("pairAddress") or "").lower() == pool]
        if same:
            return same[0]
    return max(mine, key=lambda p: to_float((p.get("liquidity") or {}).get("usd")) or 0,
               default=None)


# ---------------------------------------------------------------------
# Paper trading with Robinhood Chain costs
# ---------------------------------------------------------------------

class RobinhoodTrader(PaperTrader):
    """Main's exits (PaperTrader). Costs: the pool's fee and slippage (%) on
    every buy and sell, and gas (USD) per transaction."""

    def __init__(self, cfg, folder):
        super().__init__(dict(cfg, round_trip_cost_pct=0), folder)  # costs below

    def _kept(self, fee_pct):
        return (1 - fee_pct / 100) * (1 - self.cfg["slippage_pct"] / 100)

    def buy_token(self, token, symbol, pair_address, price, fee_pct, when, values):
        if not price or price <= 0 or not self.can_buy(token):
            return None
        amount, gas = float(self.cfg["buy_amount_usd"]), float(self.cfg["gas_usd_per_trade"])
        pos = {
            "address": token, "symbol": symbol, "pair_address": pair_address,
            "entry_time": when.isoformat(),
            "entry_price": price,                         # market price: exits use this
            "peak_price": price,
            "tokens": amount * self._kept(fee_pct) / price,   # what fee and slippage leave
            "cost_usd": amount + gas,
            "pool_fee_pct": fee_pct,
            "remaining_fraction": 1.0, "took_profit": False, "last_price": price,
        }
        self.open_positions.append(pos)
        self.state["ever_bought"].append(token)
        self._journal(when, "BUY", pos, f"passed all checks ({values.get('launchpad')})",
                      price, pos["cost_usd"])
        row = dict(values, time_utc=when.strftime("%Y-%m-%d %H:%M:%S"), pool_fee_pct=fee_pct,
                   slippage_pct=self.cfg["slippage_pct"], gas_usd=gas)
        append_row(self.entries_path, ENTRY_COLUMNS, [cell(row.get(k)) for k in ENTRY_COLUMNS])
        return pos

    def _sell(self, pos, fraction, price, reason, when):
        fraction = min(fraction, pos["remaining_fraction"])
        gross = pos["tokens"] * fraction * price
        proceeds = gross * self._kept(pos.get("pool_fee_pct", 0)) - self.cfg["gas_usd_per_trade"]
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


def cell(value):
    """A CSV cell: blank when unknown; numbers without needless decimals."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return pct(value)
    return value


# ---------------------------------------------------------------------
# The strategy
# ---------------------------------------------------------------------

class RobinhoodStrategy:
    def __init__(self, cfg, data_folder, http=None, sleep=time.sleep):
        self.c = cfg["robinhood"]
        self.pt = self.c["paper_trading"]
        self.folder = os.path.join(data_folder, "robinhood")
        self.trader = RobinhoodTrader(self.pt, self.folder)
        self.http = http or RobinhoodHttp.from_config(self.c)
        self.candidates_path = os.path.join(self.folder, "candidates.csv")
        self.launchpads = {d["dex"]: d for d in self.c["launchpads"]}
        self.exclude = {a.lower() for a in self.c["excluded_holders"]} | BURN
        self.sleep = sleep

    # ---- talking to the sources (every call recorded for the health check) ----

    def _call(self, plan, source, fn, *args):
        s = plan["sources"].setdefault(source, {"calls": 0, "errors": 0, "rate_limited": 0})
        s["calls"] += 1
        try:
            return fn(*args)
        except ApiError as exc:
            s["errors"] += 1
            s["rate_limited"] += isinstance(exc, RateLimited)
            s["error"] = str(exc)[:160]
            raise

    def _get(self, plan, source, url, params=None):
        return self._call(plan, source, self.http.get, source, url, params)

    def _rpc(self, plan, method, params, retry=True):
        """A read-only RPC call. When the RPC says 429 (too many requests),
        wait and try again: rpc_retries times, rpc_retry_seconds longer each
        time, and no more than rpc_retry_budget_seconds of waiting a run.
        retry=False: no waiting (the caller carries on next run instead)."""
        c = self.c
        for attempt in range(c["rpc_retries"] + 1 if retry else 1):
            try:
                return self._call(plan, "rpc", self.http.rpc, method, params)
            except RateLimited:
                pause = c["rpc_retry_seconds"] * (attempt + 1)
                waited = plan.get("rpc_waited", 0)
                if not retry or attempt >= c["rpc_retries"] \
                        or waited + pause > c["rpc_retry_budget_seconds"]:
                    raise
                plan["rpc_waited"] = waited + pause
                self.sleep(pause)

    def _dex_pairs(self, plan, tokens):
        pairs = []
        tokens = list(dict.fromkeys(tokens))
        for i in range(0, len(tokens), 30):
            got = self._get(plan, "dexscreener",
                            f"{DEXSCREENER}/tokens/v1/robinhood/{','.join(tokens[i:i + 30])}")
            pairs += got if isinstance(got, list) else []
        return pairs

    # ---- fetch: read everything, change nothing ----

    def fetch(self, now=None):
        now = now or now_utc()
        c, trader = self.c, self.trader
        state = copy.deepcopy(trader.state)
        plan = {"now": now, "notes": [], "sources": {}, "prices": {}, "candidates": [],
                "watch": dict(state.get("watch") or {}),
                "registry": copy.deepcopy(state.get("launchpad_tokens") or {}),
                "graduations": dict(state.get("graduations") or {}),
                "checked": dict(state.get("checked") or {}),
                "lookups": dict(state.get("onchain_lookups") or {})}

        # 1. Prices for open positions (from the pool they were bought in).
        # Without DexScreener nothing can be priced or bought: skip the run.
        held = trader.open_positions
        if held:
            pairs = self._dex_pairs(plan, [p["address"] for p in held])
            for pos in held:
                pair = pick_pair(pairs, pos["address"], (pos.get("pair_address") or "").lower())
                price = to_float((pair or {}).get("priceUsd"))
                if price:
                    plan["prices"][pos["address"]] = price

        # 2. New launchpad pools from GeckoTerminal, and the Pons graduations
        # read from the chain that GeckoTerminal hasn't listed, into the
        # watchlist.
        # Before the checks only a few calls (the new blocks since the last
        # run usually take one); a first full read goes on after them.
        self._discover(plan, now)
        self._graduations(plan, now, c["graduation_calls_before_checks"])
        self._discover_onchain(plan, now)

        # 3. Pools old enough to check, and not checked too recently.
        lo = timedelta(minutes=c["min_pool_age_minutes"])
        hi = timedelta(hours=c["max_pool_age_hours"])
        recheck = timedelta(minutes=c["recheck_minutes"])
        bought = set(state.get("ever_bought") or []) | {p["address"] for p in held}
        due = []
        for pool, w in plan["watch"].items():
            created = _utc(w.get("created"))
            if not created or not lo <= now - created <= hi or w["token"] in bought:
                continue
            last = plan["checked"].get(pool, {}).get("at")
            if last and now - _utc(last) < recheck:
                continue
            due.append((pool, w))
        due.sort(key=lambda x: (x[0] in plan["checked"], x[1]["created"]))  # new ones first
        due = due[:c["max_candidates_per_run"]]
        if not due:
            plan["notes"].append(f"{len(plan['watch'])} pool(s) on the watchlist, none due a check")
            self._graduations(plan, now, c["graduation_rpc_calls"], again=True)
            self._discover_onchain(plan, now)        # checked from the next run
            return plan

        pairs = self._dex_pairs(plan, [w["token"] for _, w in due])
        budget = {"goplus": c["goplus_max_per_run"], "holders": c["holder_checks_per_run"]}
        for pool, w in due:
            cand = self._check(plan, now, pool, w, pick_pair(pairs, w["token"], pool), budget)
            plan["candidates"].append(cand)
            plan["checked"][pool] = {"at": now.isoformat(), "passed": cand["passed"],
                                     "failed": cand["failed"]}
        self._graduations(plan, now, c["graduation_rpc_calls"], again=True)
        self._discover_onchain(plan, now)            # checked from the next run
        return plan

    def _discover(self, plan, now):
        c = self.c
        calls = c["gecko_calls_per_run"]
        # Launchpads whose graduations are read from the chain (Pons) come
        # last: their list is only read when there are calls to spare.
        def lists(chain):
            return [(f"{GECKO}/networks/robinhood/dexes/{dex}/pools", {"page": 1})
                    for dex, pad in self.launchpads.items()
                    if bool(pad.get("onchain_graduations")) == chain]
        off_chain = lists(False)
        # Take turns when there are more of those lists than calls to spare.
        turn = int(now.timestamp() // 60) % max(len(off_chain), 1)
        order = (off_chain[turn:] + off_chain[:turn]
                 + [(f"{GECKO}/networks/robinhood/new_pools", {"page": 1})] + lists(True))
        found, retried = 0, False
        for url, params in order[:calls]:
            params = dict(params, include="base_token,dex")
            try:
                try:
                    body = self._get(plan, "geckoterminal", url, params)
                except RateLimited:
                    if retried or not c.get("gecko_retry_seconds"):
                        raise
                    retried = True                # once a run: wait, and try it again
                    self.sleep(c["gecko_retry_seconds"])
                    body = self._get(plan, "geckoterminal", url, params)
            except RateLimited:
                plan["gecko_missed"] = True
                plan["notes"].append("GeckoTerminal is rate-limiting: the rest of its lists "
                                     "wait for the next run")
                break
            except ApiError as exc:
                plan["notes"].append(f"GeckoTerminal: {exc}")
                continue
            for p in gecko_pools(body, self.launchpads):
                found += 1
                # Found on the chain earlier: GeckoTerminal's pool replaces it.
                if plan["watch"].pop(ONCHAIN + p["token"], None) is not None:
                    plan["checked"].pop(ONCHAIN + p["token"], None)
                plan["watch"].setdefault(p["pool"], p)
                self._register(plan, p, now)
        # Forget pools too old to trade, and launchpad tokens that graduated
        # too long ago to matter to the copycat check.
        hi = timedelta(hours=c["max_pool_age_hours"])
        plan["watch"] = {k: v for k, v in plan["watch"].items()
                         if _utc(v.get("created")) and now - _utc(v["created"]) <= hi}
        plan["checked"] = {k: v for k, v in plan["checked"].items() if k in plan["watch"]}
        keep = timedelta(days=c["copycat_window_days"]) + hi
        plan["registry"] = {k: v for k, v in plan["registry"].items()
                            if now - _utc(v.get("graduated") or v["seen"]) <= keep}
        plan["notes"].append(f"GeckoTerminal: {found} launchpad pool(s) listed; "
                             f"{len(plan['watch'])} on the watchlist")

    @staticmethod
    def _register(plan, p, now):
        """Remember a Pons or Pools.trade token (for the copycat check): its
        names, when it graduated (its launchpad pool's creation, the earliest
        seen) and its latest liquidity and market cap."""
        r = plan["registry"].setdefault(p["token"], {"dex": p["dex"], "graduated": None})
        if p["created"] and (not r["graduated"] or _utc(p["created"]) < _utc(r["graduated"])):
            r["graduated"] = p["created"]
        r.update(symbol=p["name"] or r.get("symbol") or "",
                 title=p.get("title") or r.get("title") or "", seen=now.isoformat())
        # Where it was found: GeckoTerminal's lists, or only the chain (named
        # from DexScreener). Once GeckoTerminal lists it, it counts as listed.
        if p.get("source") == "chain" and r.get("source") != "geckoterminal":
            r["source"] = "chain"
        elif p.get("source") != "chain":
            r["source"] = "geckoterminal"
        for key in ("liquidity_usd", "market_cap_usd"):
            if p.get(key) is not None:
                r[key] = p[key]

    # ---- the checks ----

    def _check(self, plan, now, pool, w, pair, budget):
        c = self.c
        pad = self.launchpads[w["dex"]]
        v = dict.fromkeys(VALUE_COLUMNS)
        v.update(token_address=w["token"], launchpad=pad["name"],
                 pool_address=None if pool.startswith(ONCHAIN) else pool,
                 symbol=w["name"])
        checks = []

        def add(name, ok, detail):
            checks.append(Check(name, PASS if ok else FAIL, detail))
            return ok

        if pair:
            base = pair.get("baseToken") or {}
            tx = (pair.get("txns") or {}).get("h1") or {}
            change = pair.get("priceChange") or {}
            v.update(symbol=base.get("symbol") or w["name"],
                     price_usd=to_float(pair.get("priceUsd")),
                     liquidity_usd=to_float((pair.get("liquidity") or {}).get("usd")),
                     market_cap_usd=to_float(pair.get("marketCap")) or to_float(pair.get("fdv")),
                     buys_1h=tx.get("buys"), sells_1h=tx.get("sells"),
                     price_change_5m_pct=to_float(change.get("m5")),
                     price_change_1h_pct=to_float(change.get("h1")),
                     price_change_24h_pct=to_float(change.get("h24")))
            v["pool_address"] = (pair.get("pairAddress") or v["pool_address"] or "").lower() \
                or None
        created = (datetime.fromtimestamp(pair["pairCreatedAt"] / 1000, timezone.utc)
                   if pair and pair.get("pairCreatedAt") else _utc(w["created"]))
        age = (now - created).total_seconds() / 60
        v["pool_age_minutes"] = round(age, 1)
        cand = {"pool": pool, "watch": w, "pad": pad, "pair": pair, "values": v,
                "checks": checks, "top10": []}

        ok = add("Listed on DexScreener", pair is not None and v["price_usd"] is not None,
                 "priced" if pair else "no DexScreener pair yet")
        ok = ok and add("Pool age", c["min_pool_age_minutes"] <= age
                        <= c["max_pool_age_hours"] * 60, f"{age:.0f} min (need "
                        f"{c['min_pool_age_minutes']} min - {c['max_pool_age_hours']} h)")
        floor = pad.get("min_liquidity_usd", c["min_liquidity_usd"])
        ok = ok and add("Liquidity", (v["liquidity_usd"] or 0) >= floor,
                        f"{money(v['liquidity_usd'])} (need {money(floor)}+ on {pad['name']})")
        if ok:
            ok = self._market(v, add)
        if ok:
            ok = self._copycat(plan, now, cand, add)
        if ok:
            ok = self._goplus(plan, cand, add, budget)
        if ok and pad.get("holder_checks"):
            ok = self._holders(plan, cand, add, budget)
        cand["passed"] = ok and all(ch.status == PASS for ch in checks)
        cand["failed"] = [ch.name for ch in checks if ch.status != PASS]
        return cand

    def _market(self, v, add):
        """The main strategy's market checks, with this chain's numbers
        (DexScreener, the same pool; unknown counts as a fail): a market cap
        of at least min_market_cap_usd, not down more than
        max_drop_24h_pct in 24 hours, more buys than sells in the last hour."""
        c = self.c
        cap, change = v["market_cap_usd"], v["price_change_24h_pct"]
        buys, sells = v["buys_1h"], v["sells_1h"]
        ok = add("Market cap", cap is not None and cap >= c["min_market_cap_usd"],
                 f"{money(cap)} (need {money(c['min_market_cap_usd'])}+)"
                 if cap is not None else "unknown")
        ok = add(f"Not down >{c['max_drop_24h_pct']:g}% in 24h",
                 change is not None and change >= -c["max_drop_24h_pct"],
                 f"{change:+.0f}% in 24h" if change is not None else "unknown") and ok
        ok = add("More buys than sells (1h)", buys is not None and sells is not None
                 and buys > sells, f"{buys} buys vs {sells} sells"
                 if buys is not None and sells is not None else "unknown") and ok
        return ok

    def _copycat(self, plan, now, cand, add):
        """Other Pons and Pools.trade tokens with the same name or symbol
        (the launchpad tokens GeckoTerminal has listed, kept for
        copycat_window_days) make this token a copycat, except ones that
        graduated after it and clones whose liquidity is
        copycat_clone_liquidity_pct% or more of their market cap. Of the ones
        left, the earliest graduation is the original (copycat_of).
        Liquidity and market cap are DexScreener's when its search has them,
        else GeckoTerminal's."""
        c, v = self.c, cand["values"]
        token, pair = v["token_address"], cand["pair"] or {}
        base = pair.get("baseToken") or {}
        symbol = (base.get("symbol") or v["symbol"] or "").strip()
        title = (base.get("name") or "").strip()
        days = f"{c['copycat_window_days']:g}"
        if not symbol:
            return add("Not a copycat", False, "token has no symbol")
        keys = {name_key(symbol), name_key(title)} - {""}
        reg = plan["registry"]
        ours = _utc((reg.get(token) or {}).get("graduated") or cand["watch"]["created"])
        since = ours - timedelta(days=c["copycat_window_days"])
        rivals = {a: dict(r) for a, r in reg.items() if a != token
                  and keys & {name_key(r.get("symbol")), name_key(r.get("title"))}}
        rivals = {a: r for a, r in rivals.items()
                  if not r.get("graduated") or _utc(r["graduated"]) >= since}
        searched = ""
        if rivals:
            try:
                found = []
                for query in dict.fromkeys(q for q in (symbol, title) if q):
                    got = self._get(plan, "dexscreener", f"{DEXSCREENER}/latest/dex/search",
                                    {"q": query})
                    found += (got or {}).get("pairs") or []
                best = {}
                for p in found:
                    addr = ((p.get("baseToken") or {}).get("address") or "").lower()
                    liq = to_float((p.get("liquidity") or {}).get("usd"))
                    if p.get("chainId") == "robinhood" and addr in rivals and liq is not None \
                            and liq >= best.get(addr, (-1, None))[0]:
                        best[addr] = (liq, to_float(p.get("marketCap")) or to_float(p.get("fdv")))
                for addr, (liq, cap) in best.items():
                    rivals[addr].update(liquidity_usd=liq, market_cap_usd=cap)
            except ApiError as exc:
                searched = f" (DexScreener search failed, GeckoTerminal's numbers used: {exc})"
        later, clones, left = 0, 0, []
        share = c["copycat_clone_liquidity_pct"] / 100
        for addr, r in rivals.items():
            when = _utc(r.get("graduated"))
            liq, cap = r.get("liquidity_usd"), r.get("market_cap_usd")
            if when and when > ours:
                later += 1
            elif liq is not None and cap and liq >= share * cap:
                clones += 1
            else:
                left.append((when or datetime.max.replace(tzinfo=timezone.utc), addr))
        ignored = ", ".join(x for x in (
            f"{later} graduated later" if later else "",
            f"{clones} with liquidity {c['copycat_clone_liquidity_pct']:g}%+ of market cap"
            if clones else "") if x)
        ignored = f" (ignored: {ignored})" if ignored else ""
        if not left:
            v["copycat_of"] = ""
            return add("Not a copycat", True, f"no earlier Pons/Pools.trade token called "
                       f"{symbol} in the last {days} days{ignored}{searched}")
        when, first = min(left)
        v["copycat_of"] = first
        graduated = (f"graduated {(ours - when).total_seconds() / 3600:.1f} h before this one"
                     if when.year < 9999 else "graduation time unknown")
        return add("Not a copycat", False, f"{len(left)} earlier Pons/Pools.trade token(s) "
                   f"called {symbol} in the last {days} days; the first, {first}, "
                   f"{graduated}{ignored}{searched}")

    def _goplus(self, plan, cand, add, budget):
        v, token = cand["values"], cand["values"]["token_address"]
        if budget["goplus"] <= 0:
            return add("GoPlus security", False, "not checked: GoPlus limit for this run "
                       "reached (checked next run)")
        budget["goplus"] -= 1
        try:
            body = self._get(plan, "goplus", f"{GOPLUS}/token_security/{CHAIN_ID}",
                             {"contract_addresses": token})
        except ApiError as exc:
            return add("GoPlus security", False, f"unknown: {exc}")
        result = ((body or {}).get("result") or {}).get(token) or {}
        for key in GOPLUS_INFO:
            v[f"goplus_{key}"] = result.get(key)
        ok = True
        for key, name in GOPLUS_FLAGS:
            value = result.get(key)
            v[f"goplus_{key}"] = value
            if value in ("0", "1"):
                ok = add(name, value == "0", f"GoPlus {key} = {value}") and ok
            else:
                ok = add(name, False, f"unknown: GoPlus gave no {key}") and ok
        return ok

    def _holders(self, plan, cand, add, budget):
        c, v, token = self.c, cand["values"], cand["values"]["token_address"]
        if budget["holders"] <= 0:
            return add("Holders", False, "not checked: holder limit for this run reached")
        budget["holders"] -= 1
        try:
            logs, complete, mint = self._transfers(plan, token, _utc(cand["watch"]["created"]))
            creator = None
            if mint:
                tx = self._rpc(plan, "eth_getTransactionByHash", [mint["transactionHash"]])
                creator = ((tx or {}).get("from") or "").lower() or None
        except (ApiError, KeyError, TypeError, ValueError) as exc:  # odd RPC answers too
            v["holders_complete"] = False
            return add("Holders", False, f"unknown: couldn't read the token's transfers ({exc})")
        v["holders_complete"] = complete
        if not complete:
            return add("Holders", False, "unknown: couldn't read the token's whole history "
                       f"within {c['holder_rpc_calls']} RPC calls")
        balances, minted = balances_from_transfers(logs)
        first = topic_to_address((mint.get("topics") or [0, 0, 0])[2])
        pair_address = ((cand["pair"] or {}).get("pairAddress") or "").lower()
        exclude = self.exclude | {token, first, pair_address}
        s = holder_stats(balances, minted, exclude, creator, c)
        cand["top10"] = s["top10"]
        v.update(creator=creator, creator_pct=s["creator_pct"], top10_pct=s["top10_pct"],
                 holders=s["holders"], equal_group_size=s["equal_group_size"],
                 equal_group_pct=s["equal_group_pct"])
        ok = add("Creator share", s["creator_pct"] is not None
                 and s["creator_pct"] < c["max_creator_pct"],
                 f"{s['creator_pct']:.2f}% (need under {c['max_creator_pct']:g}%)"
                 if s["creator_pct"] is not None else "unknown: creator not found")
        ok = add("Top 10 holders", s["top10_pct"] < c["max_top10_pct"],
                 f"{s['top10_pct']:.1f}% (need under {c['max_top10_pct']:g}%; pools, "
                 "launchpad and burn addresses left out)") and ok
        size, share = s["equal_group_size"], s["equal_group_pct"]
        rule = (f"fails at {c['cluster_min_size']}+ wallets holding "
                f"{c['cluster_min_share_pct']:g}%+ together")
        ok = add("No equal-balance cluster", size < c["cluster_min_size"]
                 or share < c["cluster_min_share_pct"],
                 f"{size} wallets hold the same amount ({share:.1f}% together; {rule})"
                 if size > 1 else f"none ({rule})") and ok
        return ok

    def _clock(self, plan):
        """The latest block, and (once a run) seconds per block over the
        last 10,000 blocks."""
        head = hex_int(self._rpc(plan, "eth_blockNumber", []))
        if "block_time" not in plan:
            now_block = self._rpc(plan, "eth_getBlockByNumber", [hex(head), False])
            old_block = self._rpc(plan, "eth_getBlockByNumber", [hex(head - 10_000), False])
            plan["block_time"] = ((hex_int(now_block["timestamp"])
                                   - hex_int(old_block["timestamp"])) / 10_000) or 0.1
            plan["head_time"] = hex_int(now_block["timestamp"])
            plan["head"] = head
        return head

    def _graduations(self, plan, now, max_calls, again=False):
        """Read-only: Pons graduations on the chain in the last
        graduation_count_hours (the graduation event's logs, one token each),
        with when each happened (from its block). The first time, the whole
        window is read (at most graduation_rpc_calls eth_getLogs calls; an
        unfinished read carries on next run); after that only the blocks
        since the last read, at most every graduation_scan_minutes (usually
        one call). Kept in the state between runs. A 429 isn't waited for
        (the holder checks need the RPC's patience more): the read just
        carries on next run. again=True: only to finish this run's read,
        within max_calls in all."""
        c = self.c
        g = plan["graduations"]
        if again:
            if g.get("complete", True) or g.get("at") != now.isoformat() or \
                    plan.get("graduation_error"):
                return
        elif g.get("at") and now - _utc(g["at"]) < timedelta(
                minutes=c["graduation_scan_minutes"]):
            return
        max_calls -= plan.get("graduation_calls", 0)
        flt = {"address": c["pons_graduation_contract"], "topics": [c["pons_graduation_topic"]]}
        slot = c["pons_graduation_token_topic"]
        seen = dict(g.get("seen") or {})          # token -> when it graduated
        try:
            head = self._clock(plan)
        except (ApiError, KeyError, TypeError, ValueError) as exc:
            plan["notes"].append(f"Pons graduations on chain: couldn't read them ({exc})")
            return
        bt = plan["block_time"]
        window_start = max(head - int(c["graduation_count_hours"] * 3600 / bt), 0)
        scanned = g.get("scanned_to")
        start = scanned + 1 if "seen" in g and scanned is not None and scanned >= window_start \
            else window_start
        calls, step, error = 0, head - start + 1, None
        while start <= head and calls < max_calls:
            stop = min(start + step - 1, head)
            calls += 1
            try:
                got = self._rpc(plan, "eth_getLogs", [dict(flt, fromBlock=hex(start),
                                                           toBlock=hex(stop))], retry=False)
            except RateLimited as exc:
                error = exc                         # keep what was read; go on next run
                break
            except ApiError as exc:
                if step <= 1000:
                    error = exc
                    break
                step //= 2
                continue
            for log in got or []:
                topics = log.get("topics") or []
                token = topic_to_address(topics[slot]) if len(topics) > slot else None
                block = hex_int(log.get("blockNumber"))
                if token and token != ZERO and block is not None:
                    # head_time is the time of the run's first head block.
                    when = datetime.fromtimestamp(
                        plan["head_time"] - (plan["head"] - block) * bt, timezone.utc)
                    seen.setdefault(token, when.isoformat())
            start = stop + 1
        plan["graduation_calls"] = plan.get("graduation_calls", 0) + calls
        if error is not None:
            plan["graduation_error"] = True
            plan["notes"].append(f"Pons graduations on chain: read up to block {start - 1} "
                                 f"of {head} this run ({error})")
        oldest = now - timedelta(hours=c["graduation_count_hours"])
        seen = {t: w for t, w in seen.items() if _utc(w) >= oldest}
        plan["graduations"] = {"at": now.isoformat(), "hours": c["graduation_count_hours"],
                               "seen": seen, "tokens": sorted(seen), "scanned_to": start - 1,
                               "complete": start > head}

    def _name_onchain(self, plan, now):
        """The Pons graduations read from the chain that aren't in the
        launchpad registry yet, looked up on DexScreener (30 a call, at most
        onchain_lookups_per_run calls): their name, symbol, liquidity and
        market cap go into the registry (for the copycat check), with the
        graduation time from the chain. A token DexScreener doesn't list yet
        is looked up again after onchain_lookup_retry_minutes."""
        c = self.c
        retry = timedelta(minutes=c.get("onchain_lookup_retry_minutes", 30))
        looked = plan["lookups"]
        seen = plan["graduations"].get("seen") or {}
        todo = [t for t, _ in sorted(seen.items(), key=lambda x: x[1], reverse=True)
                if t not in plan["registry"]
                and (t not in looked or now - _utc(looked[t]) >= retry)]
        todo = todo[:30 * c.get("onchain_lookups_per_run", 2)]
        if not todo:
            return
        try:
            pairs = self._dex_pairs(plan, todo)
        except ApiError as exc:
            plan["notes"].append(f"Pons graduations on chain: couldn't look up their names ({exc})")
            return
        named = 0
        for token in todo:
            looked[token] = now.isoformat()
            pair = pick_pair(pairs, token)
            if not pair:
                continue
            base = pair.get("baseToken") or {}
            self._register(plan, {
                "token": token, "dex": "pons-v2-dex", "name": (base.get("symbol") or "").strip(),
                "title": (base.get("name") or "").strip(), "created": seen[token],
                "liquidity_usd": to_float((pair.get("liquidity") or {}).get("usd")),
                "market_cap_usd": to_float(pair.get("marketCap")) or to_float(pair.get("fdv")),
                "source": "chain"}, now)
            named += 1
        plan["lookups"] = {t: w for t, w in looked.items() if t in seen}
        if named:
            plan["notes"].append(f"Pons graduations on chain: {named} named from DexScreener")

    def _discover_onchain(self, plan, now):
        """The Pons graduations read from the chain that GeckoTerminal's lists
        haven't shown, onto the watchlist as well (so every graduation is
        checked), named from DexScreener when it lists them (_name_onchain).
        Their pool is DexScreener's when they're checked; the checks are the
        same as for every other pool."""
        self._name_onchain(plan, now)
        hi = timedelta(hours=self.c["max_pool_age_hours"])
        watched = {w["token"] for w in plan["watch"].values()}
        added = 0
        for token, when in (plan["graduations"].get("seen") or {}).items():
            if token in watched or now - _utc(when) > hi:
                continue
            name = (plan["registry"].get(token) or {}).get("symbol") or "?"
            plan["watch"][ONCHAIN + token] = {"pool": None, "dex": "pons-v2-dex",
                                              "token": token, "name": name, "created": when,
                                              "source": "chain"}
            added += 1
        for w in plan["watch"].values():         # named since it was added
            if w.get("source") == "chain" and w.get("name") in (None, "", "?"):
                w["name"] = (plan["registry"].get(w["token"]) or {}).get("symbol") or "?"
        if added:
            plan["notes"].append(f"Pons graduations on chain: {added} new token(s) GeckoTerminal "
                                 "hasn't listed, added to the watchlist")

    def _transfers(self, plan, token, created):
        """Every Transfer of the token since it was minted: backwards from the
        pool's creation until the mint, then forwards to now. Returns (logs,
        complete, the first mint log)."""
        c = self.c
        head = self._clock(plan)
        bt = plan["block_time"]
        start_block = min(head - int((plan["head_time"] - created.timestamp()) / bt), head)
        floor = max(start_block - int(c["holder_lookback_hours"] * 3600 / bt), 0)
        calls, logs, mint = 0, [], None
        flt = {"address": token, "topics": [TRANSFER]}
        step, end = c["rpc_log_blocks"], start_block
        while end >= floor and mint is None and calls < c["holder_rpc_calls"]:
            begin = max(end - step + 1, floor)
            calls += 1
            try:
                got = self._rpc(plan, "eth_getLogs", [dict(flt, fromBlock=hex(begin),
                                                           toBlock=hex(end))])
            except RateLimited:
                raise
            except ApiError:
                if step <= 100:
                    raise
                step //= 2
                continue
            got = got or []
            logs += got
            mints = [x for x in got if (x.get("topics") or [0, 0])[1] == topic_address(ZERO)]
            if mints:
                mint = min(mints, key=lambda x: (hex_int(x.get("blockNumber")) or 0,
                                                 hex_int(x.get("logIndex")) or 0))
            end = begin - 1
        if mint is None:
            return logs, False, None        # never found where the token was minted
        start = start_block + 1
        while start <= head and calls < c["holder_rpc_calls"]:
            stop = min(start + step - 1, head)
            calls += 1
            try:
                got = self._rpc(plan, "eth_getLogs", [dict(flt, fromBlock=hex(start),
                                                           toBlock=hex(stop))])
            except RateLimited:
                raise
            except ApiError:
                if step <= 100:
                    raise
                step //= 2
                continue
            logs += got or []
            start = stop + 1
        return logs, mint is not None and start > head, mint

    # ---- apply: trade and save ----

    def apply(self, plan, out=print):
        trader, now = self.trader, plan["now"]
        st = trader.state
        st["watch"], st["checked"] = plan["watch"], plan["checked"]
        st["launchpad_tokens"] = plan["registry"]
        st["graduations"] = plan["graduations"]
        st["onchain_lookups"] = plan["lookups"]
        st.pop("names", None)             # the old copycat memory
        sources = {}
        for name in SOURCES:
            s = plan["sources"].get(name)
            if s is None:
                sources[name] = dict((st.get("sources") or {}).get(name) or {},
                                     used_this_run=False)
                continue
            sources[name] = dict(s, ok=s["calls"] > s["errors"], at=now.isoformat(),
                                 used_this_run=True)
        st["sources"] = sources
        # GeckoTerminal over the last 24 hours, per hour: runs that used it,
        # runs that got a 429, and runs that missed a list because of one.
        g = plan["sources"].get("geckoterminal")
        if g:
            hours = st.setdefault("gecko_hours", {})
            row = hours.setdefault(now.strftime("%Y-%m-%d %H:00"), [0, 0, 0])
            row[0] += 1
            row[1] += g["rate_limited"] > 0
            row[2] += bool(plan.get("gecko_missed"))
            st["gecko_hours"] = dict(sorted(hours.items())[-24:])

        for note in plan["notes"]:
            out(f"  ({note})")
        out(f"  {self.graduation_line(plan)}")
        for name in SOURCES:
            s = plan["sources"].get(name)
            if s:
                extra = f", {s['rate_limited']} rate-limited" if s["rate_limited"] else ""
                out(f"  {name:<14} {s['calls']} call(s), {s['errors']} failed{extra}"
                    + (f": {s['error']}" if s.get("error") else ""))
        out("")

        for s in trader.update(plan["prices"], when=now):
            out(f"  SELL {s['symbol']:<10} {s['reason']:<45} P&L ${s['pnl_usd']:+.2f}")
            if s["closed"] and s["position"].get("issue_details"):
                st.setdefault("issues_to_close", []).append(s["position"])

        bought = []
        for cand in plan["candidates"]:
            v = cand["values"]
            out(f"[{'PASS' if cand['passed'] else 'FAIL'}] {v['symbol']} ({cand['pad']['name']}) "
                f"{v['token_address']}")
            for ch in cand["checks"]:
                out(f"   {'  ok ' if ch.status == PASS else ' FAIL'}  {ch.name:<28} {ch.detail}")
            self._log(now, cand)
            if not cand["passed"]:
                continue
            if len(trader.open_positions) >= self.pt["max_open_positions"]:
                out(f"  skip {v['symbol']}: already {self.pt['max_open_positions']} open positions")
                continue
            pos = trader.buy_token(v["token_address"], v["symbol"], v["pool_address"],
                                   v["price_usd"], cand["pad"]["pool_fee_pct"], now, v)
            if pos:
                pos["issue_details"] = self._issue_details(cand, now)
                bought.append(pos)
                out(f"  BUY  {v['symbol']:<10} ${self.pt['buy_amount_usd']} at "
                    f"${v['price_usd']:.10g}")
        if not plan["candidates"]:
            out("  No pool due a check this run.")
        elif not bought:
            out("  No candidate passed every check, so nothing was bought.")
        trader.save()
        return bought

    def graduation_line(self, plan):
        """How many Pons graduations the chain had, how many of them
        GeckoTerminal's lists showed, and how many only the chain did (those
        are put on the watchlist from the chain, so all of them are checked)."""
        g = plan["graduations"]
        if not g.get("at"):
            return "Pons graduations on chain: not read yet"
        seen = {t for t, r in plan["registry"].items()
                if r.get("dex") == "pons-v2-dex" and r.get("source") != "chain"}
        tokens = g["tokens"]
        chain_only = [t for t in tokens if t not in seen]
        age = (plan["now"] - _utc(g["at"])).total_seconds() / 60
        text = (f"Pons graduations on chain, last {g['hours']:g} h: {len(tokens)}"
                f"{'' if g['complete'] else '+ (still reading)'}; listed by GeckoTerminal: "
                f"{len(tokens) - len(chain_only)}; found only on chain (checked from the "
                f"chain): {len(chain_only)} (read {age:.0f} min ago)")
        if chain_only:
            text += (f"\n    found only on chain: {', '.join(chain_only[:10])}"
                     f"{' ...' if len(chain_only) > 10 else ''}")
        return text

    def _log(self, now, cand):
        """candidates.csv: every check result, when it differs from the last
        time this pool was logged."""
        v = cand["values"]
        result = "PASS" if cand["passed"] else "FAIL"
        failed = "; ".join(f"{ch.name}: {ch.detail}" for ch in cand["checks"]
                           if ch.status != PASS)
        logged = self.trader.state.setdefault("logged", {})
        key = cand["pool"]
        if logged.get(key) == f"{result}|{failed}":
            return
        logged[key] = f"{result}|{failed}"
        watch = self.trader.state.get("watch") or {}
        for k in [k for k in logged if k not in watch]:
            logged.pop(k)
        row = dict(v, time_utc=now.strftime("%Y-%m-%d %H:%M:%S"), result=result,
                   failed_checks=failed)
        append_row(self.candidates_path, CANDIDATE_COLUMNS,
                   [cell(row.get(k)) for k in CANDIDATE_COLUMNS])

    def _issue_details(self, cand, now):
        v, pair = cand["values"], cand["pair"] or {}
        by = {ch.name: ch.detail for ch in cand["checks"]}
        extra = [
            ("Chain", "Robinhood Chain (4663)"),
            ("Launchpad", cand["pad"]["name"]),
            ("Pool age", f"{v['pool_age_minutes']:.0f} min"),
            ("Buys / sells (1h)", f"{cell(v['buys_1h']) or '?'} / {cell(v['sells_1h']) or '?'}"),
        ]
        extra += [(name, by[name]) for name in by
                  if name == "Market cap" or name.startswith("Not down >")]
        extra += [(name, by[name]) for _, name in GOPLUS_FLAGS if name in by]
        for name in ("Creator share", "Top 10 holders", "No equal-balance cluster"):
            if name in by:
                extra.append((name, by[name]))
        extra.append(("Costs (paper)", f"{cand['pad']['pool_fee_pct']:g}% pool fee + "
                      f"{self.pt['slippage_pct']:g}% slippage per trade, "
                      f"${self.pt['gas_usd_per_trade']:g} gas per transaction"))
        details = {
            "extra": [list(r) for r in extra],
            "name": (pair.get("baseToken") or {}).get("name") or v["symbol"],
            "url": pair.get("url"), "passed_at": now.isoformat(),
            "address_label": "Contract address (Robinhood Chain)",
            "market_cap_usd": v["market_cap_usd"], "liquidity_usd": v["liquidity_usd"],
            "change_24h_pct": to_float((pair.get("priceChange") or {}).get("h24")),
        }
        if cand["pad"].get("holder_checks"):
            details["top_holders"] = cand["top10"]
        return details


def dry_run(argv=None):
    """`python -m screener.robinhood`: one run against the real sources, with
    results in a temporary folder that's deleted afterwards (nothing saved).
    `--holders TOKEN` only runs the holder check on one Pons token."""
    import argparse
    import tempfile

    from run import load_config
    parser = argparse.ArgumentParser(description=dry_run.__doc__.splitlines()[0])
    parser.add_argument("--holders", metavar="TOKEN", help="only check this token's holders")
    args = parser.parse_args(argv)
    cfg = load_config()
    with tempfile.TemporaryDirectory() as folder:
        strategy = RobinhoodStrategy(cfg, folder)
        print("Dry run: real data, results in a temporary folder (nothing is saved).\n")
        if not args.holders:
            strategy.apply(strategy.fetch(), print)
            return 0
        now = now_utc()
        token = args.holders.lower()
        plan = {"now": now, "sources": {}}
        cand = {"values": dict.fromkeys(VALUE_COLUMNS, None), "pair": None, "top10": [],
                "watch": {"created": now.isoformat()}}
        cand["values"]["token_address"] = token
        checks = []
        strategy._holders(plan, cand, lambda n, ok, d: checks.append((n, ok, d)) or ok,
                          {"holders": 1})
        for name, ok, detail in checks:
            print(f"  {'ok  ' if ok else 'FAIL'}  {name:<26} {detail}")
        v = cand["values"]
        print(f"  creator {v['creator']}, holders {v['holders']}, complete "
              f"{v['holders_complete']}, RPC calls {plan['sources'].get('rpc', {})}")
        print(f"  top 10: {cand['top10']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(dry_run())
