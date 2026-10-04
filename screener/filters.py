"""The PASS/FAIL checks.

Each check returns a Check with a status:
  PASS - good
  FAIL - bad, the token will NOT be bought
  WARN - worth knowing, but doesn't block a buy
  SKIP - not checked (e.g. we skipped the safety lookup to save time)

Golden rule: if data is missing or unclear, the check FAILS. We never
assume a token is safe just because we couldn't find out.
"""

from dataclasses import dataclass, field

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class Result:
    address: str
    symbol: str
    name: str
    pair: dict | None
    checks: list = field(default_factory=list)
    top_holders: list = field(default_factory=list)  # the 10 biggest real wallets
    insider: dict | None = None  # insider_status(report), saved at buy time

    @property
    def passed(self):
        return bool(self.checks) and all(c.status in (PASS, WARN) for c in self.checks)

    @property
    def price(self):
        return to_float((self.pair or {}).get("priceUsd"))


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def money(x):
    return "unknown" if x is None else f"${x:,.0f}"


# ---------------------------------------------------------------------
# Finding candidates
# ---------------------------------------------------------------------

def find_candidates(profiles, boosts):
    """Solana token addresses from the 'latest profiles' and 'boosts' lists."""
    seen = []
    for item in list(profiles or []) + list(boosts or []):
        if item.get("chainId") == "solana":
            addr = item.get("tokenAddress")
            if addr and addr not in seen:
                seen.append(addr)
    return seen


def best_pair(pairs, address, allowed_dexes):
    """A token can trade in several pools. Pick the one with the most money in
    it, preferring pools on the allowed exchanges."""
    mine = [p for p in pairs if (p.get("baseToken") or {}).get("address") == address]
    if not mine:
        return None

    def liquidity(p):
        return to_float((p.get("liquidity") or {}).get("usd")) or 0.0

    allowed = [p for p in mine if p.get("dexId") in allowed_dexes]
    return max(allowed or mine, key=liquidity)


# ---------------------------------------------------------------------
# Market checks (from DexScreener)
# ---------------------------------------------------------------------

def market_checks(pair, f):
    if pair is None:
        return [Check("Market data", FAIL, "DexScreener has no trading pair for this token")]

    checks = []
    dex = pair.get("dexId", "unknown")
    checks.append(Check(
        "Migrated (PumpSwap/Raydium)",
        PASS if dex in f["allowed_dexes"] else FAIL,
        f"trades on '{dex}'",
    ))

    mcap = to_float(pair.get("marketCap")) or to_float(pair.get("fdv"))
    ok = mcap is not None and f["min_market_cap_usd"] <= mcap <= f["max_market_cap_usd"]
    checks.append(Check(
        "Market cap in range", PASS if ok else FAIL,
        f"{money(mcap)} (need {money(f['min_market_cap_usd'])} to {money(f['max_market_cap_usd'])})",
    ))

    liq = to_float((pair.get("liquidity") or {}).get("usd"))
    ok = liq is not None and liq >= f["min_liquidity_usd"]
    checks.append(Check(
        "Liquidity", PASS if ok else FAIL,
        f"{money(liq)} (need at least {money(f['min_liquidity_usd'])})",
    ))

    change = to_float((pair.get("priceChange") or {}).get("h24"))
    ok = change is not None and change <= f["max_price_change_24h_pct"]
    checks.append(Check(
        f"Not up >{f['max_price_change_24h_pct']:g}% in 24h",
        PASS if ok else FAIL,
        "unknown" if change is None else f"{change:+.0f}% in 24h",
    ))

    tx = (pair.get("txns") or {}).get("h24") or {}
    buys, sells = tx.get("buys"), tx.get("sells")
    if buys is None or sells is None:
        checks.append(Check("24h activity", FAIL, "no transaction data"))
    else:
        total = buys + sells
        checks.append(Check(
            "24h transactions", PASS if total >= f["min_txns_24h"] else FAIL,
            f"{total:,} trades (need {f['min_txns_24h']:,})",
        ))
        if f["require_more_buys_than_sells"]:
            checks.append(Check(
                "More buys than sells", PASS if buys > sells else FAIL,
                f"{buys:,} buys vs {sells:,} sells",
            ))
    return checks


# ---------------------------------------------------------------------
# Safety checks (from RugCheck)
# ---------------------------------------------------------------------

def _pool_accounts(report, pair):
    """Wallets that belong to trading pools (not real people)."""
    pools = set()
    for addr, info in (report.get("knownAccounts") or {}).items():
        if (info or {}).get("type") == "AMM":
            pools.add(addr)
    for m in report.get("markets") or []:
        # RugCheck gives the pool's vault addresses as strings in liquidityA/B,
        # and the parsed vault accounts (a dict whose "owner" is the pool) in
        # liquidityAAccount/BAccount. Only ever collect plain address strings.
        for key in ("pubkey", "liquidityA", "liquidityB",
                    "liquidityAAccount", "liquidityBAccount"):
            value = m.get(key)
            if isinstance(value, dict):
                value = value.get("owner")
            if isinstance(value, str) and value:
                pools.add(value)
    if pair and pair.get("pairAddress"):
        pools.add(pair["pairAddress"])
    return pools


def real_holders(report, pair, f):
    """RugCheck's top holders, biggest first, minus pool wallets (if configured)."""
    holders = report.get("topHolders") or []
    if f.get("exclude_pools_from_holders", True):
        pools = _pool_accounts(report, pair)
        holders = [h for h in holders
                   if h.get("address") not in pools and h.get("owner") not in pools]
    return holders


def safety_checks(report, pair, f):
    if not report:
        return [Check("Safety data", FAIL, "RugCheck has no report for this token")]

    checks = []
    token = report.get("token") or {}

    for label, key in (("Mint authority revoked", "mintAuthority"),
                       ("Freeze authority revoked", "freezeAuthority")):
        value = token.get(key, report.get(key))
        checks.append(Check(
            label, PASS if not value else FAIL,
            "revoked" if not value else f"still active ({value[:8]}...)",
        ))

    holders = real_holders(report, pair, f)
    if not holders:
        checks.append(Check("Top 10 holders", FAIL, "no holder data"))
    else:
        top10 = sum(to_float(h.get("pct")) or 0.0 for h in holders[:10])
        checks.append(Check(
            "Top 10 holders", PASS if top10 < f["max_top10_holders_pct"] else FAIL,
            f"own {top10:.1f}% (need under {f['max_top10_holders_pct']}%)",
        ))

    checks.append(_creator_check(report, holders, f))
    checks.append(_lp_check(report, pair, f))
    checks.append(_insider_check(report, f))
    return checks


def _creator_check(report, holders, f):
    limit = f["max_creator_pct"]
    name = "Creator holds little"
    creator = report.get("creator")

    pct = None
    supply = to_float((report.get("token") or {}).get("supply"))
    balance = to_float(report.get("creatorBalance"))
    if balance is not None and supply:
        pct = balance / supply * 100
    elif creator:
        for h in holders:
            if creator in (h.get("owner"), h.get("address")):
                pct = to_float(h.get("pct"))
                break
        else:
            # Creator isn't in the top-holder list, so they own less than the
            # smallest holder on it. If that's under the limit, we're fine.
            smallest = min((to_float(h.get("pct")) or 0.0 for h in holders), default=None)
            if len(holders) >= 10 and smallest is not None and smallest < limit:
                return Check(name, PASS, f"not a top holder (under {smallest:.1f}%)")

    if pct is None:
        return Check(name, FAIL, "couldn't determine creator's share")
    return Check(name, PASS if pct < limit else FAIL, f"{pct:.1f}% (need under {limit}%)")


def _lp_check(report, pair, f):
    name = "LP locked/burned"
    markets = [m for m in report.get("markets") or [] if m.get("lp")]
    if not markets:
        return Check(name, FAIL, "no liquidity pool data")
    # Only the pool we'd actually trade in counts. Another pool being locked
    # says nothing about this one, so if RugCheck doesn't list it, we FAIL.
    pair_addr = (pair or {}).get("pairAddress")
    matching = [m for m in markets if pair_addr and m.get("pubkey") == pair_addr]
    if not matching:
        return Check(name, FAIL, "RugCheck has no data for the pool this token trades in")
    locked = max(to_float(m["lp"].get("lpLockedPct")) or 0.0 for m in matching)
    return Check(
        name, PASS if locked >= f["min_lp_locked_pct"] else FAIL,
        f"{locked:.0f}% locked or burned (need {f['min_lp_locked_pct']}%)",
    )


def insider_status(report):
    """Insider-network numbers from a RugCheck report (None if no report).
    Only recorded for later analysis; the checks use their own logic."""
    if not report:
        return None
    networks = report.get("insiderNetworks") or []
    linked = report.get("graphInsidersDetected") or 0
    flagged = sum(1 for h in report.get("topHolders") or [] if h.get("insider"))
    return {"networks": len(networks), "linked_wallets": linked,
            "insider_top_holders": flagged}


def _insider_check(report, f):
    networks = report.get("insiderNetworks") or []
    detected = report.get("graphInsidersDetected") or 0
    flagged = sum(1 for h in report.get("topHolders") or [] if h.get("insider"))
    if not (networks or detected or flagged):
        return Check("Insider networks", PASS, "none detected")
    status = FAIL if f.get("insider_networks_are_fail") else WARN
    bits = []
    if networks:
        bits.append(f"{len(networks)} network(s)")
    if detected:
        bits.append(f"{detected} linked wallet(s)")
    if flagged:
        bits.append(f"{flagged} insider top holder(s)")
    return Check("Insider networks", status, ", ".join(bits))


# ---------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------

def evaluate(address, pair, report, f, safety_skipped=False):
    base = (pair or {}).get("baseToken") or {}
    result = Result(address, base.get("symbol", "?"), base.get("name", "?"), pair)
    result.checks = market_checks(pair, f)
    if safety_skipped:
        result.checks.append(Check("Safety checks", SKIP, "skipped because market checks failed"))
    else:
        result.checks.extend(safety_checks(report, pair, f))
        if report:
            result.top_holders = real_holders(report, pair, f)[:10]
            result.insider = insider_status(report)
    return result


def format_report(result):
    icon = {PASS: "  ok ", FAIL: " FAIL", WARN: " WARN", SKIP: " skip"}
    verdict = "PASS" if result.passed else "FAIL"
    lines = [
        f"[{verdict}] {result.symbol} ({result.name})",
        f"       {result.address}",
    ]
    if result.pair and result.pair.get("url"):
        lines.append(f"       {result.pair['url']}")
    for c in result.checks:
        lines.append(f"   {icon[c.status]}  {c.name:<30} {c.detail}")
    return "\n".join(lines)


def current_prices(api, positions, allowed_dexes):
    """Latest price for each open position, from the same pool we 'bought' in."""
    if not positions:
        return {}
    pairs = api.pairs_for_tokens([p["address"] for p in positions])
    prices = {}
    for pos in positions:
        pair = next((p for p in pairs if p.get("pairAddress") == pos["pair_address"]), None)
        pair = pair or best_pair(pairs, pos["address"], allowed_dexes)
        try:
            prices[pos["address"]] = float(pair["priceUsd"])
        except (TypeError, KeyError, ValueError):
            pass
    return prices
