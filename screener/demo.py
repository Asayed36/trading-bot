"""MADE-UP example data, so you can see how the screener behaves without the
internet. None of these tokens exist. Used by `python run.py --demo` and by
the automated tests.
"""

import copy

GOOD = "DEMOgood1111111111111111111111111111111111"


def _pair(addr, symbol, dex="pumpswap", mcap=800_000, liq=60_000, change=45.0,
          buys=900, sells=600, price="0.0008"):
    return {
        "chainId": "solana", "dexId": dex, "pairAddress": f"POOL-{symbol}",
        "url": f"https://dexscreener.com/solana/pool-{symbol.lower()} (fake)",
        "baseToken": {"address": addr, "symbol": symbol, "name": f"Demo {symbol}"},
        "priceUsd": price, "marketCap": mcap, "fdv": mcap,
        "liquidity": {"usd": liq}, "priceChange": {"h24": change},
        "txns": {"h24": {"buys": buys, "sells": sells}},
    }


def _report(symbol, mint=None, freeze=None, whale_pct=2.0, creator_pct=1.0,
            lp_locked=100, insiders=0):
    holders = [{"address": f"POOLACCT-{symbol}", "owner": "AMM-AUTH", "pct": 18.0}]
    holders.append({"address": "whale", "owner": "whale", "pct": whale_pct})
    holders += [{"address": f"h{i}", "owner": f"h{i}", "pct": 1.5} for i in range(12)]
    return {
        "creator": "CREATOR", "creatorBalance": creator_pct * 10_000,
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

    def pairs_for_tokens(self, addresses):
        pairs = []
        for a in addresses:
            if a in TOKENS:
                pair = copy.deepcopy(TOKENS[a][0])
                pair["priceUsd"] = str(float(pair["priceUsd"]) * self.price_moves.get(a, 1.0))
                pairs.append(pair)
        return pairs

    def rugcheck_report(self, address):
        return copy.deepcopy(TOKENS.get(address, (None, None))[1])
