"""Robinhood Chain data probe: what do the free data sources actually return?

    python robinhood_probe.py                  <- print a report (Markdown)
    python robinhood_probe.py --json out.json  <- also save everything as JSON

Step one before any Robinhood Chain paper strategy: it asks each free source
a few questions and reports counts, errors and samples, so we build on what
the sources really return (the launch bot's PumpPortal trade feed looked fine
in code and sent nothing for days). It runs on GitHub Actions
(.github/workflows/robinhood-probe.yml), which can reach sites the
development sandbox can't.

READ-ONLY. It never connects a wallet, never uses a private key, never signs
or sends a transaction and never trades. It only makes GET requests to public
websites and read-only JSON-RPC calls (the four in RPC_METHODS). The optional
GoPlus and Blockscout keys are free sign-up keys with no wallet involved; with
none set, those checks are only run without a key.

What it checks:
  - DexScreener: Robinhood pairs from searches, the latest token profiles and
    boosts, and whether brand-new launchpad (curve-stage) tokens are listed
  - GeckoTerminal: the network's DEXes (launchpads show up as DEXes, e.g.
    "pons-v2" for the Pons curve), its newest pools, and each launchpad's pools
  - the public RPC: chain id and block time; for new launchpad tokens, every
    contract that logged an event naming the token around its creation (the
    launchpad's contracts), those contracts' recent events, and holders
    rebuilt from the token's own Transfer events
  - Blockscout: whether its holder API answers without a key (and with one)
  - GoPlus token security for chain 4663, without a key and with one
"""

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import requests

CHAIN_ID = 4663
DEXSCREENER = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"
BLOCKSCOUT = "https://robinhoodchain.blockscout.com/api/v2"
BLOCKSCOUT_PRO = f"https://api.blockscout.com/{CHAIN_ID}/api/v2"
RPC = "https://rpc.mainnet.chain.robinhood.com"
GOPLUS = "https://api.gopluslabs.io/api/v1"

HEADERS = {"User-Agent": "memecoin-screener/1.0 (read-only paper trading research)"}
# The only JSON-RPC calls this program makes (all read-only).
RPC_METHODS = {"eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "eth_getLogs"}
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "0" * 40

LAUNCHPADS = ("pons", "pools", "robinlaunch", "launchhood")
# GeckoTerminal DEX ids that look like launchpads (reported, not all probed).
LAUNCHPAD_WORDS = ("pons", "pools-trade", "robinlaunch", "launchhood", "launch", "fun",
                   "kickstart", "clank", "bankr", "pad", "mint-club", "virtuals")
SEARCHES = ("pons", "pools", "robin", "hood", "cat", "dog", "pepe", "ai", "trump", "meme",
            "moon", "stock", "usdg", "frog", "inu")
GECKO_PAGES = 3
GECKO_GAP = 6.5           # seconds between GeckoTerminal calls (it said 429 at 2.2)
TOKENS_PER_LAUNCHPAD = 3   # new tokens per launchpad traced on the RPC
CREATION_BLOCKS = 600      # blocks either side of a pool's creation time to search
EVENT_MINUTES = 5          # recent events read from each launchpad contract
MAX_LOG_CALLS = 30         # eth_getLogs calls allowed per scan
HOLDER_TOKENS = 4
GOPLUS_TOKENS = 6


def rpc_request(method, params, request_id=1):
    """A JSON-RPC request, refusing anything that isn't a read-only call."""
    if method not in RPC_METHODS:
        raise ValueError(f"{method} is not an allowed read-only RPC call")
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


class Http:
    """GET (and JSON-RPC POST) with a short record of every call."""

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.calls = Counter()
        self._last = {}

    def _pace(self, host, gap):
        wait = self._last.get(host, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()

    def get(self, url, params=None, headers=None, gap=0.3):
        """(status, json or None, error text or None)."""
        host = url.split("/")[2]
        self._pace(host, gap)
        self.calls[host] += 1
        try:
            resp = requests.get(url, params=params, timeout=self.timeout,
                                headers=dict(HEADERS, **(headers or {})))
        except requests.RequestException as exc:
            return None, None, str(exc)[:200]
        try:
            body = resp.json()
        except ValueError:
            body = None
        error = None if resp.status_code == 200 else (resp.text or "")[:200]
        return resp.status_code, body, error

    def post_json(self, url, payload, gap=0.2):
        host = url.split("/")[2]
        self._pace(host, gap)
        self.calls[host] += 1
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout, headers=HEADERS)
        except requests.RequestException as exc:
            return None, None, str(exc)[:200]
        try:
            body = resp.json()
        except ValueError:
            body = None
        error = None if resp.status_code == 200 else (resp.text or "")[:200]
        return resp.status_code, body, error

    def rpc(self, method, params):
        status, body, error = self.post_json(RPC, rpc_request(method, params))
        if body and "error" in body:
            return None, str(body["error"])[:200]
        if body and "result" in body:
            return body["result"], None
        return None, error or f"HTTP {status}"


# ---------------------------------------------------------------------------
# Small helpers (tested in tests/test_robinhood_probe.py)
# ---------------------------------------------------------------------------

def hex_int(value):
    return int(value, 16) if isinstance(value, str) and value.startswith("0x") else None


def addr(value):
    """A lower-case 0x address from a Blockscout field (a string or {hash})."""
    if isinstance(value, dict):
        value = value.get("hash")
    return value.lower() if isinstance(value, str) and value.startswith("0x") else None


def age_hours(created_ms, now):
    return None if not created_ms else round((now - created_ms / 1000) / 3600, 2)


def launchpad_of(name):
    """Which launchpad a contract or DEX name belongs to, if any."""
    text = (name or "").lower().replace(".", "").replace(" ", "")
    for pad in LAUNCHPADS:
        if pad in text:
            return pad
    return None


def equal_groups(balances, tolerance=0.005):
    """Sizes of groups of holders with near-identical balances (within
    `tolerance`), largest first: bundles often buy exactly the same amount."""
    values = sorted(b for b in balances if b > 0)
    groups, current = [], []
    for v in values:
        if current and v - current[0] <= current[0] * tolerance:
            current.append(v)
        else:
            if len(current) > 1:
                groups.append(len(current))
            current = [v]
    if len(current) > 1:
        groups.append(len(current))
    return sorted(groups, reverse=True)


def topic_counts(logs):
    return Counter((log.get("topics") or ["(none)"])[0] for log in logs)


def goplus_sign(app_key, app_secret, now):
    return hashlib.sha1(f"{app_key}{now}{app_secret}".encode()).hexdigest()

def topic_address(address):
    """An address as a 32-byte log topic."""
    return "0x" + "0" * 24 + address.lower()[2:]


def topic_to_address(topic):
    return ("0x" + topic[-40:]).lower() if isinstance(topic, str) and len(topic) == 66 else None


def balances_from_transfers(logs):
    """Token balances rebuilt from ERC-20 Transfer logs (from, to, amount)."""
    bal = defaultdict(int)
    for log in logs:
        topics = log.get("topics") or []
        if len(topics) < 3 or topics[0] != TRANSFER:
            continue
        amount = hex_int(log.get("data") or "0x0") or 0
        bal[topic_to_address(topics[1])] -= amount
        bal[topic_to_address(topics[2])] += amount
    bal.pop(ZERO, None)
    return {a: v for a, v in bal.items() if v > 0}


def concentration(balances, skip=()):
    """Share of the largest holder, the top 10 and equal-balance groups,
    leaving out `skip` (the curve or pool contract holding unsold supply)."""
    total = sum(balances.values()) or 1
    rows = sorted(((a, v) for a, v in balances.items() if a not in skip), key=lambda r: -r[1])
    return {"holders": len(rows),
            "skipped_pct": round(100 * sum(balances.get(a, 0) for a in skip) / total, 2),
            "largest_pct": round(100 * rows[0][1] / total, 2) if rows else None,
            "top10_pct": round(100 * sum(v for _, v in rows[:10]) / total, 2),
            "equal_balance_groups": equal_groups([v for _, v in rows])[:5]}



# ---------------------------------------------------------------------------
# The probe


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

def _ts(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


class Probe:
    def __init__(self, http=None, env=None, now=None):
        self.http = http or Http()
        self.env = os.environ if env is None else env
        self.now = now or time.time()
        self.r = {"started_utc": datetime.fromtimestamp(self.now, timezone.utc).isoformat()}
        self.pools = []            # GeckoTerminal pools: dex, launchpad, token, pool, created
        self.ds_tokens = []        # tokens of the newest DexScreener pairs
        self.head = None
        self.head_time = None
        self.block_time = None
        self.traced = []           # launchpad tokens traced on the RPC

    def run(self):
        for step in (self.dexscreener, self.gecko, self.gecko_launchpads, self.rpc_basics,
                     self.launchpad_contracts, self.curve_stage, self.holders, self.goplus):
            try:
                step()
            except Exception as exc:  # one broken source mustn't hide the others
                self.r.setdefault("crashes", []).append(f"{step.__name__}: {exc!r}"[:300])
        self.r["calls_per_host"] = dict(self.http.calls)
        return self.r

    # ---- DexScreener ----

    def dexscreener(self):
        pairs, errors = {}, []
        for q in SEARCHES:
            status, body, err = self.http.get(f"{DEXSCREENER}/latest/dex/search", {"q": q})
            if err:
                errors.append(f"search {q}: HTTP {status} {err}")
                continue
            for p in (body or {}).get("pairs") or []:
                if p.get("chainId") == "robinhood":
                    pairs[p["pairAddress"]] = p
        listing = sorted(pairs.values(), key=lambda p: -(p.get("pairCreatedAt") or 0))
        self.ds_tokens = [p["baseToken"]["address"].lower() for p in listing[:10]]
        out = {
            "pairs_found": len(pairs),
            "by_dex": Counter(self._dex_label(p) for p in pairs.values()).most_common(15),
            "by_quote": Counter(p["quoteToken"]["symbol"] for p in pairs.values()).most_common(8),
            "newest": [self._pair_sample(p) for p in listing[:3]],
            "errors": errors[:5],
        }
        for kind in ("token-profiles", "token-boosts"):
            status, body, err = self.http.get(f"{DEXSCREENER}/{kind}/latest/v1")
            items = body if isinstance(body, list) else []
            out[kind] = {"status": status, "total": len(items),
                         "robinhood": sum(x.get("chainId") == "robinhood" for x in items),
                         "error": err}
        self.r["dexscreener"] = out

    @staticmethod
    def _dex_label(p):
        return f"{p.get('dexId')} {','.join(p.get('labels') or [])}".strip()

    def _pair_sample(self, p):
        return {"symbol": p["baseToken"].get("symbol"), "token": p["baseToken"]["address"],
                "dex": p.get("dexId"), "labels": p.get("labels"),
                "quote": p["quoteToken"].get("symbol"),
                "age_h": age_hours(p.get("pairCreatedAt"), self.now),
                "liquidity_usd": (p.get("liquidity") or {}).get("usd"),
                "price_usd": p.get("priceUsd"), "url": p.get("url")}

    # ---- GeckoTerminal ----

    def _gecko_pools(self, url, params):
        status, body, err = self.http.get(url, params, gap=GECKO_GAP)
        pools = []
        for pool in (body or {}).get("data") or []:
            a = pool.get("attributes") or {}
            rel = pool.get("relationships") or {}
            dex = ((rel.get("dex") or {}).get("data") or {}).get("id")
            base = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
            pools.append({"dex": dex, "launchpad": launchpad_of(dex),
                          "token": base.split("_", 1)[-1].lower(), "name": a.get("name"),
                          "pool": (a.get("address") or "").lower(),
                          "created": a.get("pool_created_at"),
                          "reserve_usd": a.get("reserve_in_usd")})
        return status, err, pools

    def gecko(self):
        out = {"pages": []}
        status, body, err = self.http.get(f"{GECKO}/networks/robinhood/dexes",
                                          {"page": 1}, gap=GECKO_GAP)
        ids = [d.get("id") for d in (body or {}).get("data") or []]
        out["dexes"] = {"status": status, "error": err, "count": len(ids), "ids": ids}
        out["launchpad_like_dexes"] = [i for i in ids if any(w in i for w in LAUNCHPAD_WORDS)]
        for page in range(1, GECKO_PAGES + 1):
            status, err, pools = self._gecko_pools(f"{GECKO}/networks/robinhood/new_pools",
                                                   {"page": page, "include": "base_token,dex"})
            out["pages"].append({"page": page, "status": status, "error": err})
            self.pools += pools
        created = sorted(p["created"] for p in self.pools if p["created"])
        out.update({"new_pools": len(self.pools),
                    "by_dex": Counter(p["dex"] for p in self.pools).most_common(15),
                    "created_range": [created[0], created[-1]] if created else None,
                    "samples": self.pools[:4]})
        self.r["geckoterminal"] = out

    def gecko_launchpads(self):
        """Each launchpad's own pools (GeckoTerminal lists launchpads as DEXes)."""
        ids = (self.r.get("geckoterminal") or {}).get("dexes", {}).get("ids") or []
        out = {}
        for pad in LAUNCHPADS:
            dexes = [i for i in ids if launchpad_of(i) == pad]
            out[pad] = {"dex_ids": dexes,
                        "new_pools": sum(p["launchpad"] == pad for p in self.pools)}
            for dex in dexes:
                status, err, pools = self._gecko_pools(
                    f"{GECKO}/networks/robinhood/dexes/{dex}/pools",
                    {"page": 1, "include": "base_token,dex"})
                out[pad][dex] = {"status": status, "error": err, "pools": len(pools),
                                 "samples": pools[:2]}
                known = {p["pool"] for p in self.pools}
                self.pools += [p for p in pools if p["pool"] not in known]
        self.r["launchpads_on_geckoterminal"] = out

    # ---- the public RPC ----

    def rpc_basics(self):
        out = {}
        chain, err = self.http.rpc("eth_chainId", [])
        out["chain_id"] = hex_int(chain) if chain else err
        head, err = self.http.rpc("eth_blockNumber", [])
        self.head = hex_int(head)
        out["block_number"] = self.head if self.head is not None else err
        if self.head is not None:
            latest = self._block_time_of(self.head)
            older = self._block_time_of(max(self.head - 10_000, 0))
            if latest and older and latest > older:
                self.block_time = (latest - older) / 10_000
                self.head_time = latest
        out["seconds_per_block"] = self.block_time
        self.r["rpc"] = out

    def _block_time_of(self, number):
        block, _ = self.http.rpc("eth_getBlockByNumber", [hex(number), False])
        return hex_int((block or {}).get("timestamp"))

    def _block_at(self, when):
        """The block number at a unix time (estimate, refined twice)."""
        number = self.head - int((self.head_time - when) / self.block_time)
        for _ in range(2):
            ts = self._block_time_of(max(number, 0))
            if ts is None:
                break
            number += int((when - ts) / self.block_time)
        return max(min(number, self.head), 0)

    def get_logs(self, flt, start, end):
        """eth_getLogs over [start, end], splitting the range when the RPC
        refuses it. Returns (logs, calls, error or None, complete?)."""
        logs, calls, step, error = [], 0, end - start + 1, None
        while start <= end and calls < MAX_LOG_CALLS:
            stop = min(start + step - 1, end)
            got, err = self.http.rpc("eth_getLogs", [dict(flt, fromBlock=hex(start),
                                                          toBlock=hex(stop))])
            calls += 1
            if got is None:
                error = err
                if step <= 25:
                    break
                step //= 2
                continue
            logs += got
            start = stop + 1
        return logs, calls, error, start > end

    def launchpad_contracts(self):
        """For new tokens of each launchpad: every contract that logged an
        event naming the token (as a topic) around the pool's creation. The
        ones seen for every token are the launchpad's contracts; then read
        their recent events."""
        if not self.block_time:
            self.r["launchpad_contracts"] = "skipped: no block time from the RPC"
            return
        out = {}
        for pad in LAUNCHPADS:
            pools = sorted((p for p in self.pools if p["launchpad"] == pad and p["created"]
                            and p["token"].startswith("0x")),
                           key=lambda p: p["created"], reverse=True)[:TOKENS_PER_LAUNCHPAD]
            emitters, tokens = Counter(), []
            for p in pools:
                block = self._block_at(_ts(p["created"]))
                found = Counter()
                for position in (1, 2, 3):
                    topics = [None] * position + [topic_address(p["token"])]
                    logs, calls, err, done = self.get_logs(
                        {"topics": topics}, block - CREATION_BLOCKS, block + CREATION_BLOCKS)
                    for log in logs:
                        emitter = (log.get("address") or "").lower()
                        if emitter != p["token"]:
                            found[(emitter, (log.get("topics") or [""])[0])] += 1
                mints, _, _, _ = self.get_logs(
                    {"address": p["token"], "topics": [TRANSFER, topic_address(ZERO)]},
                    block - CREATION_BLOCKS, block + CREATION_BLOCKS)
                for emitter in {e for e, _ in found}:
                    emitters[emitter] += 1
                row = {"token": p["token"], "dex": p["dex"], "pool": p["pool"],
                       "created": p["created"], "creation_block": block,
                       "events_naming_token": [[e, t, n] for (e, t), n in found.most_common(8)],
                       "minted_to": sorted({topic_to_address((m.get("topics") or [0, 0, 0])[2])
                                            for m in mints})[:5]}
                tokens.append(row)
                self.traced.append(dict(row, launchpad=pad))
            contracts = []
            for contract, seen in emitters.most_common(4):
                start = self.head - int(EVENT_MINUTES * 60 / self.block_time)
                logs, calls, err, done = self.get_logs({"address": contract}, start, self.head)
                contracts.append({"contract": contract, "seen_for_tokens": seen,
                                  "events_last_minutes": EVENT_MINUTES, "logs": len(logs),
                                  "complete": done, "error": err,
                                  "by_topic": topic_counts(logs).most_common(6),
                                  "sample": logs[0] if logs else None})
            out[pad] = {"tokens_traced": len(tokens), "tokens": tokens,
                        "contracts": contracts}
        self.r["launchpad_contracts"] = out

    # ---- curve stage: are brand-new launchpad tokens on DexScreener? ----

    def curve_stage(self):
        out = {}
        for pad in LAUNCHPADS:
            fresh = list(dict.fromkeys(p["token"] for p in self.pools if p["launchpad"] == pad
                                       and p["token"].startswith("0x")))[:30]
            if not fresh:
                out[pad] = "no new launchpad tokens found on GeckoTerminal"
                continue
            status, body, err = self.http.get(
                f"{DEXSCREENER}/tokens/v1/robinhood/{','.join(fresh)}")
            pairs = body if isinstance(body, list) else []
            listed = {p["baseToken"]["address"].lower() for p in pairs}
            out[pad] = {"tokens_checked": len(fresh), "status": status, "error": err,
                        "listed_on_dexscreener": len(listed & set(fresh)),
                        "by_dex": Counter(self._dex_label(p) for p in pairs).most_common(8),
                        "gecko_dexes": Counter(p["dex"] for p in self.pools
                                               if p["token"] in fresh).most_common(5),
                        "samples": [self._pair_sample(p) for p in pairs[:3]]}
        self.r["curve_stage"] = out

    # ---- holders ----

    def holders(self):
        tokens = [t["token"] for t in self.traced][:HOLDER_TOKENS] or self.ds_tokens[:2]
        out = {"blockscout": {}, "from_transfer_logs": []}
        if tokens:
            sample = tokens[0]
            status, _, err = self.http.get(f"{BLOCKSCOUT}/tokens/{sample}/holders")
            out["blockscout"]["keyless_instance_api"] = f"HTTP {status}" + (
                f" {err[:80]}" if err else "")
            status, _, err = self.http.get(f"{BLOCKSCOUT_PRO}/tokens/{sample}/holders")
            out["blockscout"]["pro_api_without_key"] = f"HTTP {status}" + (
                f" {err[:80]}" if err else "")
            key = self.env.get("BLOCKSCOUT_API_KEY")
            if key:
                status, body, err = self.http.get(f"{BLOCKSCOUT_PRO}/tokens/{sample}/holders",
                                                  {"apikey": key})
                out["blockscout"]["pro_api_with_key"] = {
                    "status": status, "error": err and err[:80],
                    "items": len((body or {}).get("items") or [])}
            else:
                out["blockscout"]["pro_api_with_key"] = "not tested: BLOCKSCOUT_API_KEY not set"
        if not self.block_time:
            self.r["holders"] = out
            return
        for t in self.traced[:HOLDER_TOKENS]:
            logs, calls, err, done = self.get_logs(
                {"address": t["token"], "topics": [TRANSFER]},
                t["creation_block"] - CREATION_BLOCKS, self.head)
            bal = balances_from_transfers(logs)
            skip = {a for a in [t["pool"]] + t["minted_to"] if a}
            row = {"token": t["token"], "launchpad": t["launchpad"], "transfers": len(logs),
                   "rpc_calls": calls, "complete": done, "error": err}
            row.update(concentration(bal, skip))
            out["from_transfer_logs"].append(row)
        self.r["holders"] = out

    # ---- GoPlus ----

    def goplus(self):
        traced = [t["token"] for t in self.traced]
        tokens = list(dict.fromkeys(traced[:3] + self.ds_tokens))[:GOPLUS_TOKENS]
        out = {"without_key": [self._goplus_one(t, None) for t in tokens]}
        key, secret = self.env.get("GOPLUS_APP_KEY"), self.env.get("GOPLUS_APP_SECRET")
        if key and secret:
            now = int(time.time())
            status, body, err = self.http.post_json(f"{GOPLUS}/token", {
                "app_key": key, "time": now, "sign": goplus_sign(key, secret, now)})
            token = ((body or {}).get("result") or {}).get("access_token")
            out["key_login"] = {"status": status, "code": (body or {}).get("code"),
                                "message": (body or {}).get("message"), "error": err}
            if token:
                out["with_key"] = [self._goplus_one(t, token) for t in tokens]
        else:
            out["with_key"] = "not tested: GOPLUS_APP_KEY / GOPLUS_APP_SECRET secrets not set"
        self.r["goplus"] = out

    def _goplus_one(self, token, access_token):
        headers = {"Authorization": access_token} if access_token else None
        status, body, err = self.http.get(f"{GOPLUS}/token_security/{CHAIN_ID}",
                                          {"contract_addresses": token}, headers, gap=2.1)
        result = ((body or {}).get("result") or {}).get(token) or {}
        keep = ("is_honeypot", "cannot_sell_all", "buy_tax", "sell_tax", "is_mintable",
                "hidden_owner", "owner_address", "can_take_back_ownership",
                "owner_change_balance", "is_blacklisted", "is_open_source",
                "holder_count", "lp_holder_count", "creator_percent")
        return {"token": token, "launchpad": next((t["launchpad"] for t in self.traced
                                                   if t["token"] == token), None),
                "status": status, "code": (body or {}).get("code"),
                "message": (body or {}).get("message"), "error": err and err[:120],
                "fields_returned": len(result),
                "values": {k: result[k] for k in keep if k in result},
                "holders_listed": len(result.get("holders") or []),
                "lp_holders_listed": len(result.get("lp_holders") or []),
                "dex": [d.get("name") for d in result.get("dex") or []]}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _j(value):
    return json.dumps(value, default=str)


def report(r):
    L = [f"# Robinhood Chain data probe ({r['started_utc'][:16]} UTC)", "",
         "Read-only: GET requests and read-only RPC calls only.", ""]
    d = r.get("dexscreener") or {}
    L += ["## DexScreener", f"- Robinhood pairs from {len(SEARCHES)} searches: "
          f"**{d.get('pairs_found')}**",
          f"- by DEX: {_j(d.get('by_dex'))}", f"- by quote token: {_j(d.get('by_quote'))}",
          f"- latest token profiles: {_j(d.get('token-profiles'))}",
          f"- latest boosts: {_j(d.get('token-boosts'))}"]
    L += [f"- newest: {_j(p)}" for p in d.get("newest") or []]
    L += [f"- error: {e}" for e in d.get("errors") or []]
    g = r.get("geckoterminal") or {}
    dexes = g.get("dexes") or {}
    L += ["", "## GeckoTerminal",
          f"- DEXes on the network: {dexes.get('count')} (HTTP {dexes.get('status')})",
          f"- launchpad-like DEX ids: {_j(g.get('launchpad_like_dexes'))}",
          f"- new pools: **{g.get('new_pools')}** (pages: {_j(g.get('pages'))})",
          f"- by DEX: {_j(g.get('by_dex'))}", f"- created between: {_j(g.get('created_range'))}"]
    L += [f"- sample: {_j(s)}" for s in g.get("samples") or []]
    L += ["", "## Launchpads on GeckoTerminal"]
    for pad, res in (r.get("launchpads_on_geckoterminal") or {}).items():
        L.append(f"- **{pad}**: {_j(res)}")
    rpc = r.get("rpc") or {}
    L += ["", "## Public RPC", f"- chain id: {rpc.get('chain_id')}, block: "
          f"{rpc.get('block_number')}, seconds per block: {rpc.get('seconds_per_block')}",
          "", "## Launchpad contracts (from events naming new tokens)"]
    lc = r.get("launchpad_contracts")
    if isinstance(lc, str):
        L.append(f"- {lc}")
    for pad, res in (lc or {}).items() if isinstance(lc, dict) else []:
        L.append(f"### {pad}: {res['tokens_traced']} new token(s) traced")
        for t in res["tokens"]:
            L.append(f"- token {t['token']} ({t['dex']}, created {t['created']}, block "
                     f"{t['creation_block']}): minted to {_j(t['minted_to'])}; events naming it "
                     f"[emitter, topic0, count]: {_j(t['events_naming_token'])}")
        for c in res["contracts"]:
            L.append(f"- contract {c['contract']} (seen for {c['seen_for_tokens']} token(s)): "
                     f"{c['logs']} logs in the last {c['events_last_minutes']} min"
                     f"{'' if c['complete'] else ' (incomplete)'}"
                     f"{'; error ' + str(c['error']) if c['error'] else ''}; "
                     f"by topic {_j(c['by_topic'])}")
            if c.get("sample"):
                L.append(f"  - sample log: {_j(c['sample'])[:500]}")
    L += ["", "## Curve stage: are brand-new launchpad tokens on DexScreener?"]
    for pad, res in (r.get("curve_stage") or {}).items():
        L.append(f"- **{pad}**: {_j(res)}")
    h = r.get("holders") or {}
    L += ["", "## Holders", f"- Blockscout: {_j(h.get('blockscout'))}"]
    L += [f"- from Transfer logs: {_j(x)}" for x in h.get("from_transfer_logs") or []]
    gp = r.get("goplus") or {}
    L += ["", "## GoPlus token security (chain 4663)", "### Without a key"]
    L += [f"- {_j(x)}" for x in gp.get("without_key") or []]
    L += ["### With a key"]
    if gp.get("key_login"):
        L.append(f"- login: {_j(gp['key_login'])}")
    wk = gp.get("with_key")
    L += [f"- {_j(x)}" for x in wk] if isinstance(wk, list) else [f"- {wk}"]
    L += ["", f"Calls per host: {_j(r.get('calls_per_host'))}"]
    L += [f"- CRASH {x}" for x in r.get("crashes") or []]
    return "\n".join(L) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", metavar="FILE", help="also save the raw results as JSON")
    args = parser.parse_args(argv)
    results = Probe().run()
    text = report(results)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(text)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
