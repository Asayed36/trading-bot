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

Sources:
  - DexScreener: Robinhood pairs from searches, the latest token profiles and
    boosts, and whether brand-new launchpad tokens are listed (curve stage?)
  - GeckoTerminal: new pools and DEXes on the "robinhood" network
  - Blockscout (robinhoodchain.blockscout.com): who created new tokens, which
    contract created them (the launchpads), their holders and event names
  - the public RPC: chain id, block time, and the launchpad contracts' events
  - GoPlus token security for chain 4663, without a key and with one
"""

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
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

LAUNCHPADS = ("pons", "pools", "robinlaunch", "launchhood")
SEARCHES = ("pons", "pools", "robin", "hood", "cat", "dog", "pepe", "ai", "trump", "meme",
            "moon", "stock", "usdg", "frog", "inu")
GECKO_PAGES = 2
SAMPLE_TOKENS = 15      # new tokens whose creator and creating contract are looked up
HOLDER_TOKENS = 5       # tokens whose holders are checked
GOPLUS_TOKENS = 5
LOG_MINUTES = 30        # how far back to read launchpad events on the RPC


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


def holder_summary(holders, total_supply, skip=()):
    """Top-10 share and equal-balance groups from Blockscout holder items,
    leaving out `skip` addresses (pools, hooks, burn)."""
    rows = []
    for h in holders:
        a = addr(h.get("address"))
        try:
            value = int(h.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if a and a not in skip:
            rows.append((a, value, bool((h.get("address") or {}).get("is_contract"))))
    rows.sort(key=lambda r: -r[1])
    supply = int(total_supply or 0) or sum(r[1] for r in rows) or 1
    return {
        "holders_returned": len(holders),
        "top10_pct": round(100 * sum(r[1] for r in rows[:10]) / supply, 2),
        "contracts_in_top10": sum(r[2] for r in rows[:10]),
        "equal_balance_groups": equal_groups([r[1] for r in rows])[:5],
    }


def topic_counts(logs):
    return Counter((log.get("topics") or ["(none)"])[0] for log in logs)


def goplus_sign(app_key, app_secret, now):
    return hashlib.sha1(f"{app_key}{now}{app_secret}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

class Probe:
    def __init__(self, http=None, env=None, now=None):
        self.http = http or Http()
        self.env = os.environ if env is None else env
        self.now = now or time.time()
        self.r = {"started_utc": datetime.fromtimestamp(self.now, timezone.utc).isoformat()}
        self.new_tokens = {}       # address -> where we saw it
        self.factories = Counter()  # contract that created a sample token -> count
        self.names = {}            # address -> Blockscout name
        self.skip = {"0x0000000000000000000000000000000000000000",
                     "0x000000000000000000000000000000000000dead"}

    def run(self):
        for step in (self.dexscreener, self.gecko, self.blockscout_search,
                     self.token_origins, self.rpc_and_events, self.curve_stage,
                     self.holders, self.goplus):
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
        for p in listing[:SAMPLE_TOKENS]:
            self.new_tokens.setdefault(p["baseToken"]["address"].lower(), "dexscreener")
        out = {
            "pairs_found": len(pairs),
            "by_dex": Counter(f"{p.get('dexId')} {','.join(p.get('labels') or [])}".strip()
                              for p in pairs.values()).most_common(15),
            "by_quote": Counter(p["quoteToken"]["symbol"] for p in pairs.values()).most_common(8),
            "newest": [self._pair_sample(p) for p in listing[:5]],
            "errors": errors[:5],
        }
        for kind in ("token-profiles", "token-boosts"):
            status, body, err = self.http.get(f"{DEXSCREENER}/{kind}/latest/v1")
            items = body if isinstance(body, list) else []
            out[kind] = {"status": status, "total": len(items),
                         "robinhood": sum(x.get("chainId") == "robinhood" for x in items),
                         "error": err}
        self.r["dexscreener"] = out

    def _pair_sample(self, p):
        return {"symbol": p["baseToken"].get("symbol"), "token": p["baseToken"]["address"],
                "dex": p.get("dexId"), "labels": p.get("labels"),
                "quote": p["quoteToken"].get("symbol"),
                "age_h": age_hours(p.get("pairCreatedAt"), self.now),
                "liquidity_usd": (p.get("liquidity") or {}).get("usd"),
                "price_usd": p.get("priceUsd"), "url": p.get("url")}

    # ---- GeckoTerminal ----

    def gecko(self):
        out = {"pages": []}
        status, body, err = self.http.get(f"{GECKO}/networks/robinhood/dexes", gap=2.2)
        out["dexes"] = {"status": status, "error": err,
                        "ids": [d.get("id") for d in (body or {}).get("data") or []]}
        pools = []
        for page in range(1, GECKO_PAGES + 1):
            status, body, err = self.http.get(
                f"{GECKO}/networks/robinhood/new_pools",
                {"page": page, "include": "base_token,dex"}, gap=2.2)
            out["pages"].append({"page": page, "status": status, "error": err})
            pools += (body or {}).get("data") or []
        dex_count, samples = Counter(), []
        for pool in pools:
            a = pool.get("attributes") or {}
            rel = pool.get("relationships") or {}
            dex = ((rel.get("dex") or {}).get("data") or {}).get("id")
            base = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
            dex_count[dex] += 1
            token = base.split("_", 1)[-1].lower()
            if token.startswith("0x"):
                self.new_tokens.setdefault(token, "geckoterminal")
            if len(samples) < 5:
                samples.append({"name": a.get("name"), "dex": dex, "token": token,
                                "created": a.get("pool_created_at"),
                                "reserve_usd": a.get("reserve_in_usd"),
                                "pool": a.get("address")})
        created = sorted(a for a in ((p.get("attributes") or {}).get("pool_created_at")
                                     for p in pools) if a)
        out.update({"new_pools": len(pools), "by_dex": dex_count.most_common(15),
                    "created_range": [created[0], created[-1]] if created else None,
                    "samples": samples})
        self.r["geckoterminal"] = out

    # ---- Blockscout: launchpad contracts ----

    def blockscout_search(self):
        found = {}
        for pad in LAUNCHPADS:
            status, body, err = self.http.get(f"{BLOCKSCOUT}/search", {"q": pad})
            items = (body or {}).get("items") or []
            found[pad] = {"status": status, "error": err, "items": [
                {"type": i.get("type"), "name": i.get("name"), "address": i.get("address")
                 or i.get("address_hash"), "verified": i.get("is_smart_contract_verified")}
                for i in items[:8]]}
            for i in items:
                a = addr(i.get("address") or i.get("address_hash"))
                if a and i.get("type") in ("contract", "address") and launchpad_of(i.get("name")):
                    self.names[a] = i.get("name")
        self.r["blockscout_search"] = found

    def token_origins(self):
        """For new tokens: who created them and which contract did it. The
        most common creating contracts are the launchpads' factories."""
        rows = []
        for token in list(self.new_tokens)[:SAMPLE_TOKENS * 2]:
            status, info, err = self.http.get(f"{BLOCKSCOUT}/addresses/{token}")
            if err or not info:
                rows.append({"token": token, "error": f"HTTP {status} {err}"})
                continue
            tx = info.get("creation_transaction_hash") or info.get("creation_tx_hash")
            row = {"token": token, "token_name": (info.get("token") or {}).get("name"),
                   "creator": addr(info.get("creator_address_hash")), "creation_tx": tx}
            if tx:
                status, t, err = self.http.get(f"{BLOCKSCOUT}/transactions/{tx}")
                to = (t or {}).get("to") or {}
                row.update({"created_by_contract": addr(to), "contract_name": to.get("name"),
                            "method": (t or {}).get("method"),
                            "timestamp": (t or {}).get("timestamp")})
                if addr(to):
                    self.factories[addr(to)] += 1
                    if to.get("name"):
                        self.names.setdefault(addr(to), to.get("name"))
            rows.append(row)
            if sum("creator" in x for x in rows) >= SAMPLE_TOKENS:
                break
        self.r["token_origins"] = {
            "looked_up": len(rows),
            "creating_contracts": [{"address": a, "name": self.names.get(a), "tokens": n,
                                    "launchpad": launchpad_of(self.names.get(a))}
                                   for a, n in self.factories.most_common(10)],
            "samples": rows[:8]}

    def _launchpad_contracts(self):
        """Contracts to read events from: those that created sample tokens,
        plus contracts Blockscout names after a launchpad."""
        picks = [a for a, _ in self.factories.most_common(6)]
        picks += [a for a, n in self.names.items() if launchpad_of(n) and a not in picks]
        return picks[:10]

    # ---- the public RPC ----

    def rpc_and_events(self):
        out = {}
        chain, err = self.http.rpc("eth_chainId", [])
        out["chain_id"] = hex_int(chain) if chain else err
        head, err = self.http.rpc("eth_blockNumber", [])
        head = hex_int(head)
        out["block_number"] = head if head is not None else err
        self.r["rpc"] = out
        if head is None:
            return
        latest, _ = self.http.rpc("eth_getBlockByNumber", [hex(head), False])
        older, _ = self.http.rpc("eth_getBlockByNumber", [hex(max(head - 10_000, 0)), False])
        block_time = None
        if latest and older:
            span = hex_int(latest["timestamp"]) - hex_int(older["timestamp"])
            block_time = span / 10_000 if span > 0 else None
        out["seconds_per_block"] = block_time
        window = int(LOG_MINUTES * 60 / block_time) if block_time else 5_000
        events = []
        for contract in self._launchpad_contracts():
            events.append(self._contract_events(contract, head, window))
        out["launchpad_events"] = events

    def _contract_events(self, contract, head, window):
        """eth_getLogs over the last `window` blocks, halving the window if the
        RPC refuses a range that big; event names from Blockscout."""
        row = {"contract": contract, "name": self.names.get(contract),
               "launchpad": launchpad_of(self.names.get(contract))}
        logs, err, tries = None, None, 0
        while tries < 6 and window >= 50:
            logs, err = self.http.rpc("eth_getLogs", [{
                "address": contract, "fromBlock": hex(head - window), "toBlock": hex(head)}])
            if logs is not None:
                break
            window //= 2
            tries += 1
        row.update({"blocks_read": window, "error": None if logs is not None else err})
        if logs is not None:
            counts = topic_counts(logs)
            row["logs"] = len(logs)
            row["by_topic"] = counts.most_common(8)
            row["sample_log"] = logs[0] if logs else None
        status, body, err = self.http.get(f"{BLOCKSCOUT}/addresses/{contract}/logs")
        names = Counter()
        for item in (body or {}).get("items") or []:
            decoded = item.get("decoded") or {}
            topic0 = (item.get("topics") or [None])[0]
            names[f"{decoded.get('method_call') or '(not decoded)'} [{(topic0 or '')[:10]}]"] += 1
        row["blockscout_event_names"] = names.most_common(8) if names else f"HTTP {status} {err}"
        # Tokens this contract created recently (curve-stage candidates).
        status, body, err = self.http.get(f"{BLOCKSCOUT}/addresses/{contract}/internal-transactions")
        created = [addr(i.get("created_contract")) for i in (body or {}).get("items") or []
                   if i.get("created_contract")]
        row["recently_created"] = len(created)
        row["created_sample"] = created[:5]
        row.setdefault("created", created)
        return row

    # ---- curve stage: are brand-new launchpad tokens on DexScreener? ----

    def curve_stage(self):
        fresh = []
        for row in (self.r.get("rpc") or {}).get("launchpad_events") or []:
            fresh += [a for a in row.pop("created", []) if a and a not in fresh]
        fresh = fresh[:30]
        out = {"fresh_tokens_checked": len(fresh)}
        if fresh:
            status, body, err = self.http.get(
                f"{DEXSCREENER}/tokens/v1/robinhood/{','.join(fresh)}")
            pairs = body if isinstance(body, list) else []
            listed = {p["baseToken"]["address"].lower() for p in pairs}
            out.update({
                "status": status, "error": err,
                "listed_on_dexscreener": len(listed & set(fresh)),
                "by_dex": Counter(f"{p.get('dexId')} {','.join(p.get('labels') or [])}".strip()
                                  for p in pairs).most_common(10),
                "samples": [self._pair_sample(p) for p in pairs[:5]]})
            status, body, err = self.http.get(
                f"{GECKO}/networks/robinhood/tokens/multi/{','.join(fresh)}", gap=2.2)
            out["listed_on_geckoterminal"] = len((body or {}).get("data") or [])
            out["geckoterminal_status"] = status if not err else f"{status} {err}"
        self.r["curve_stage"] = out
        for a in fresh[:5]:
            self.new_tokens.setdefault(a, "launchpad")

    # ---- Blockscout holders ----

    def holders(self):
        pro_key = self.env.get("BLOCKSCOUT_API_KEY")
        rows = []
        for token in list(self.new_tokens)[:HOLDER_TOKENS]:
            status, info, err = self.http.get(f"{BLOCKSCOUT}/tokens/{token}")
            status_h, body, err_h = self.http.get(f"{BLOCKSCOUT}/tokens/{token}/holders")
            row = {"token": token, "symbol": (info or {}).get("symbol"),
                   "holders_count": (info or {}).get("holders_count")
                   or (info or {}).get("holders"),
                   "status": status_h, "error": err_h}
            if body:
                row.update(holder_summary(body.get("items") or [],
                                          (info or {}).get("total_supply"), self.skip))
                row["sample_keys"] = sorted((body.get("items") or [{}])[0].keys())
            if pro_key:
                status_p, _, err_p = self.http.get(f"{BLOCKSCOUT_PRO}/tokens/{token}/holders",
                                                   {"apikey": pro_key})
                row["pro_api"] = f"HTTP {status_p}" + (f" {err_p}" if err_p else "")
            rows.append(row)
        self.r["blockscout_holders"] = {"keyless": rows,
                                        "pro_key": "set" if pro_key else "not set"}

    # ---- GoPlus ----

    def goplus(self):
        tokens = list(self.new_tokens)[:GOPLUS_TOKENS]
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
                "holder_count", "lp_holder_count", "creator_percent", "dex")
        return {"token": token, "status": status, "code": (body or {}).get("code"),
                "message": (body or {}).get("message"), "error": err,
                "fields_returned": len(result),
                "values": {k: result[k] for k in keep if k in result},
                "top_holder_pct": [h.get("percent") for h in (result.get("holders") or [])[:5]],
                "lp_locked": [h.get("is_locked") for h in (result.get("lp_holders") or [])[:3]]}


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
    L += ["", "## GeckoTerminal", f"- DEXes on the network: {_j(g.get('dexes'))}",
          f"- new pools: **{g.get('new_pools')}** (pages: {_j(g.get('pages'))})",
          f"- by DEX: {_j(g.get('by_dex'))}", f"- created between: {_j(g.get('created_range'))}"]
    L += [f"- sample: {_j(s)}" for s in g.get("samples") or []]
    L += ["", "## Blockscout: launchpad name search"]
    for pad, res in (r.get("blockscout_search") or {}).items():
        L.append(f"- {pad}: HTTP {res.get('status')} {res.get('error') or ''} "
                 f"{_j(res.get('items'))}")
    o = r.get("token_origins") or {}
    L += ["", "## Blockscout: which contracts create new tokens",
          f"- tokens looked up: {o.get('looked_up')}"]
    L += [f"- creating contract: {_j(c)}" for c in o.get("creating_contracts") or []]
    L += [f"- sample: {_j(s)}" for s in o.get("samples") or []]
    rpc = r.get("rpc") or {}
    L += ["", "## Public RPC", f"- chain id: {rpc.get('chain_id')}, block: "
          f"{rpc.get('block_number')}, seconds per block: {rpc.get('seconds_per_block')}"]
    for e in rpc.get("launchpad_events") or []:
        L.append(f"- {e.get('contract')} ({e.get('name')}, launchpad: {e.get('launchpad')}): "
                 f"{e.get('logs')} logs in the last {e.get('blocks_read')} blocks"
                 f"{'; error ' + str(e['error']) if e.get('error') else ''}; "
                 f"by topic {_j(e.get('by_topic'))}; names {_j(e.get('blockscout_event_names'))}; "
                 f"recently created tokens {e.get('recently_created')} {_j(e.get('created_sample'))}")
        if e.get("sample_log"):
            L.append(f"  - sample log: {_j(e['sample_log'])[:600]}")
    c = r.get("curve_stage") or {}
    L += ["", "## Curve stage: are brand-new launchpad tokens listed?", f"- {_j(c)}"]
    h = r.get("blockscout_holders") or {}
    L += ["", f"## Blockscout holders (Pro API key: {h.get('pro_key')})"]
    L += [f"- {_j(x)}" for x in h.get("keyless") or []]
    gp = r.get("goplus") or {}
    L += ["", "## GoPlus token security (chain 4663)", "### Without a key"]
    L += [f"- {_j(x)}" for x in gp.get("without_key") or []]
    L += ["### With a key", f"- login: {_j(gp.get('key_login'))}" if gp.get("key_login") else ""]
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
