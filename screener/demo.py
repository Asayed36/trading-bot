"""MADE-UP example data, so you can see how the screener behaves without the
internet. None of these tokens exist. Used by `python run.py --demo` and by
the automated tests.
"""

import copy
from datetime import datetime, timedelta, timezone

GOOD = "DEMOgood1111111111111111111111111111111111"


def _ms_ago(**ago):
    return (datetime.now(timezone.utc) - timedelta(**ago)).timestamp() * 1000


def _pair(addr, symbol, dex="pumpswap", mcap=800_000, liq=60_000, change=45.0,
          buys=900, sells=600, price="0.0008", created_ms=None, m5=None, h1=None,
          h6=None, buys_1h=None, sells_1h=None):
    return {
        "chainId": "solana", "dexId": dex, "pairAddress": f"POOL-{symbol}",
        "url": f"https://dexscreener.com/solana/pool-{symbol.lower()} (fake)",
        "baseToken": {"address": addr, "symbol": symbol, "name": f"Demo {symbol}"},
        "priceUsd": price, "marketCap": mcap, "fdv": mcap,
        "liquidity": {"usd": liq},
        "priceChange": {"m5": m5, "h1": h1, "h6": h6, "h24": change},
        "txns": {"h1": {"buys": buys_1h, "sells": sells_1h},
                 "h24": {"buys": buys, "sells": sells}},
        "pairCreatedAt": created_ms if created_ms is not None else _ms_ago(days=3),
    }


def _report(symbol, mint=None, freeze=None, whale_pct=2.0, creator_pct=1.0,
            lp_locked=100, insiders=0, creator="CREATOR", detected=None):
    holders = [{"address": f"POOLACCT-{symbol}", "owner": "AMM-AUTH", "pct": 18.0}]
    holders.append({"address": "whale", "owner": "whale", "pct": whale_pct})
    holders += [{"address": f"h{i}", "owner": f"h{i}", "pct": 1.5} for i in range(12)]
    return {
        "creator": creator, "creatorBalance": creator_pct * 10_000,
        "detectedAt": detected,
        "token": {"mintAuthority": mint, "freezeAuthority": freeze, "supply": 1_000_000},
        "topHolders": holders,
        "knownAccounts": {"AMM-AUTH": {"name": "Pump Fun AMM", "type": "AMM"}},
        "markets": [{"pubkey": f"POOL-{symbol}", "lp": {"lpLockedPct": lp_locked}}],
        "graphInsidersDetected": insiders,
        "insiderNetworks": [{"id": "net1"}] if insiders else None,
    }


# Each demo token is built to show off one particular check.
TOKENS = {
    GOOD: (_pair(GOOD, "GOODCAT"), _report("GOODCAT")),
    "DEMOcurve": (_pair("DEMOcurve", "CURVE", dex="pumpfun", mcap=40_000, liq=10_000), None),
    "DEMOwhale": (_pair("DEMOwhale", "WHALE"), _report("WHALE", whale_pct=25.0)),
    "DEMOmint": (_pair("DEMOmint", "MINTY"), _report("MINTY", mint="Mint1234567890")),
    "DEMOpump": (_pair("DEMOpump", "ROCKET", change=450.0), _report("ROCKET")),
    "DEMOsell": (_pair("DEMOsell", "DUMPY", buys=300, sells=700), _report("DUMPY")),
    "DEMOinsider": (_pair("DEMOinsider", "FRENS", price="0.002"), _report("FRENS", insiders=7)),
    "DEMOrug": (_pair("DEMOrug", "RUGGY"), _report("RUGGY", lp_locked=0, creator_pct=12.0)),
}


def _early(addr, symbol, grad_min=90, age_h=3.0, h6=100.0, h1=-30.0, m5=2.0,
           buys_1h=400, sells_1h=300, whale_pct=2.0, insiders=0, liq=25_000):
    """A young token for the "early" strategy. The defaults make a clean
    pullback: +100% over 6h, then down 30% from the peak and holding."""
    detected = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat()
    pair = _pair(addr, symbol, mcap=120_000, liq=liq, change=h6, price="0.0006",
                 created_ms=_ms_ago(minutes=grad_min), m5=m5, h1=h1, h6=h6,
                 buys_1h=buys_1h, sells_1h=sells_1h)
    report = _report(symbol, whale_pct=whale_pct, insiders=insiders,
                     creator=f"DEV-{symbol}", detected=detected)
    return pair, report


# Young tokens for the "early" strategy, found through GeckoTerminal's newest
# pools. Only EARLYgood passes; each other one fails a single early rule.
EARLY_GOOD = "EARLYgood111111111111111111111111111111111"
EARLY_TOKENS = {
    EARLY_GOOD: _early(EARLY_GOOD, "PULLY"),
    "EARLYfresh": _early("EARLYfresh", "FRESHY", grad_min=10),         # graduated 10 min ago
    "EARLYchase": _early("EARLYchase", "CHASEY", h6=150, h1=40, m5=5),  # still at its peak
    "EARLYcopy": _early("EARLYcopy", "DOGGO"),                         # another DOGGO exists
    "EARLYinsider": _early("EARLYinsider", "INSIDY", insiders=3),      # insider wallets
    "EARLYwhale": _early("EARLYwhale", "WHALY", whale_pct=8.0),        # top 10 own 21.5%
}
# A different, older DOGGO that makes EARLYcopy a copycat.
OTHER_DOGGO = _pair("OTHERdoggo", "DOGGO", created_ms=_ms_ago(days=2))


class DemoApi:
    """Pretends to be the real websites. `price_moves` lets tests change prices,
    e.g. {GOOD: 1.6} means GOODCAT's price is now 1.6x the original."""

    def __init__(self, price_moves=None):
        self.price_moves = price_moves or {}

    def latest_profiles(self):
        items = [{"chainId": "solana", "tokenAddress": a} for a in list(TOKENS)[:5]]
        return items + [{"chainId": "ethereum", "tokenAddress": "0xnotsolana"}]

    def latest_boosts(self):
        return [{"chainId": "solana", "tokenAddress": a} for a in list(TOKENS)[3:]]

    def gecko_new_pools(self, page=1):
        if page > 1:
            return []
        return [{"id": f"solana_POOL-{a}", "type": "pool", "relationships": {
                    "base_token": {"data": {"id": f"solana_{a}", "type": "token"}},
                    "quote_token": {"data": {"id": "solana_So11111111111111111111111111111111111111112",
                                             "type": "token"}},
                    "dex": {"data": {"id": "pumpswap", "type": "dex"}}}}
                for a in EARLY_TOKENS]

    def search_pairs(self, query):
        q = query.lower()
        pairs = [p for p, _ in list(TOKENS.values()) + list(EARLY_TOKENS.values())] + [OTHER_DOGGO]
        return [copy.deepcopy(p) for p in pairs
                if q in (p["baseToken"]["symbol"].lower(), p["baseToken"]["name"].lower())]

    def pairs_for_tokens(self, addresses):
        pairs = []
        for a in addresses:
            known = TOKENS.get(a) or EARLY_TOKENS.get(a)
            if known:
                pair = copy.deepcopy(known[0])
                move = self.price_moves.get(a, 1.0)
                pair["priceUsd"] = str(float(pair["priceUsd"]) * move)
                pair["marketCap"] = pair["fdv"] = pair["marketCap"] * move
                pairs.append(pair)
        return pairs

    def gecko_pool_trades(self, pool):
        return []  # no demo trades: the demo list is built from holders

    def rugcheck_report(self, address):
        known = TOKENS.get(address) or EARLY_TOKENS.get(address) or (None, None)
        return copy.deepcopy(known[1])


# ---------------------------------------------------------------------
# A pretend Helius for the "convergence" strategy
# ---------------------------------------------------------------------

def _swap(mint, side, sol, tokens, when):
    return {"mint": mint, "side": side, "sol": sol, "tokens": tokens,
            "time": int(when.timestamp())}


def demo_trader_history(now=None):
    """Made-up swap histories. The top holders 'whale', 'h0' and 'h1' of the
    demo ROCKET token are profitable traders; the other holders never traded."""
    now = now or datetime.now(timezone.utc)
    history = {}
    for n, wallet in enumerate(("whale", "h0", "h1")):
        swaps = []
        for i in range(6):
            when = now - timedelta(days=10 - i, hours=n)
            mint = f"PASTWIN{i}"
            swaps.append(_swap(mint, "buy", 1.0, 1000.0, when))
            # five winners (2x) and one loser (-50%)
            swaps.append(_swap(mint, "sell", 2.0 if i else 0.5, 1000.0, when + timedelta(hours=2)))
        history[wallet] = swaps
    return history


class DemoRpc:
    """Pretends to be Helius: serves made-up transactions and spends made-up
    credits on the strategy's credit meter, 10 per call like the real one."""

    per_call = 10
    name = "demo Helius"

    def __init__(self, meter=None, history=None, live=None):
        self.meter = meter
        self.history = history if history is not None else demo_trader_history()
        self.live = live if live is not None else {}
        self.calls = 0
        self._txs = {}

    def _spend(self):
        if self.meter is not None:
            self.meter.spend(self.per_call)
        self.calls += 1

    def signatures(self, wallet, limit, until=None):
        self._spend()
        swaps = self.history.get(wallet, []) + self.live.get(wallet, [])
        sigs = []
        for i, swap in enumerate(swaps):
            sig = f"{wallet}-{i}"
            self._txs[sig] = (wallet, swap)
            sigs.append({"signature": sig, "blockTime": swap["time"], "err": None})
        sigs.reverse()  # newest first, like the real API
        if until:
            cut = next((k for k, s in enumerate(sigs) if s["signature"] == until), len(sigs))
            sigs = sigs[:cut]
        return sigs[:limit]

    def transaction(self, signature):
        self._spend()
        wallet, s = self._txs[signature]
        lamports = int(s["sol"] * 1e9)
        before, after = (0.0, s["tokens"]) if s["side"] == "buy" else (s["tokens"], 0.0)
        sol_after = 50 * 10**9 - lamports if s["side"] == "buy" else 50 * 10**9 + lamports

        def bal(amount):
            return [{"owner": wallet, "mint": s["mint"],
                     "uiTokenAmount": {"uiAmountString": str(amount)}}]
        return {"blockTime": s["time"],
                "transaction": {"message": {"accountKeys": [{"pubkey": wallet}]}},
                "meta": {"err": None, "preBalances": [50 * 10**9], "postBalances": [sol_after],
                         "preTokenBalances": bal(before), "postTokenBalances": bal(after)}}


def demo_rpc_factory(history=None, live=None):
    """For ConvergenceStrategy(rpc_factory=...): one fake for Helius and live."""
    def make(meter):
        rpc = DemoRpc(meter, history, live)
        return rpc, rpc
    return make
