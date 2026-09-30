"""The "early" paper strategy: young tokens, bought on a pullback.

It runs alongside the main screener with its own pretend positions and
journal (data/early/). Like everything here it is PAPER trading only: it never
connects to a wallet, never uses a private key and never places an order.

Where candidates come from:
  - DexScreener's latest token profiles and boosts (same as the main screener)
  - GeckoTerminal's newest Solana pools
  - every token still on the watchlist from earlier runs

A token is (pretend) bought only when ALL of these hold (numbers are in
[early] in config.toml):
  - it trades on PumpSwap or Raydium (graduated from pump.fun), and that pool
    was created at least 30 minutes ago
  - the token itself is at most 6 hours old
  - pullback entry: after a spike of at least 50%, the price is now 20-50%
    below the highest price seen, it isn't falling over the last 5 minutes,
    and buys outnumber sells over the last hour
  - there's enough liquidity to sell ($10k)
  - mint and freeze authority are revoked and the LP is locked or burned
  - the top 10 holders own under 20%
  - no insider networks or insider holders at all
  - no other token with the same name or symbol launched in the last 7 days
    has as much liquidity (the most liquid of same-named tokens is allowed)
  - the creator isn't known to have launched a token that died

The price history behind the pullback check comes from DexScreener's 6h/1h/5m
price changes the first time a token is seen, then one reading per run (every
15 minutes), so the peak it knows about is approximate.

"Creator has dead tokens" uses RugCheck's list of the creator's other tokens
when it has one (it usually doesn't), plus the bot's own memory: whenever a
watched token dies (market cap under $5k, or flagged as rugged), its creator
is remembered and their future tokens are skipped. That memory starts empty
and grows as the bot runs.
"""

import copy
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from screener.api import ApiError, RateLimited
from screener.filters import (FAIL, PASS, Check, Result, _lp_check, best_pair,
                              find_candidates, money, real_holders, to_float)
from screener.paper_trader import PaperTrader, now_utc

# Tokens that are the "money" side of a pool, never the memecoin itself.
QUOTE_MINTS = {
    "So11111111111111111111111111111111111111112",   # wrapped SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}
MAX_DEAD_CREATORS = 5000


class EarlyTrader(PaperTrader):
    """Same bookkeeping as the main trader, different exits:
      - take profit: sell half at 2x (handled by PaperTrader)
      - hard stop: sell everything left at -30%
      - time stop: sell everything after 45 minutes if take profit hasn't hit
      - after take profit, the rest rides until it falls 40% from its peak,
        or 24 hours have passed."""

    def close_reason(self, pos, change_pct, from_peak, hours):
        c = self.cfg
        if change_pct <= -c["stop_loss_pct"]:
            return f"hard stop: down {-change_pct:.0f}% from entry"
        if not pos["took_profit"]:
            if hours * 60 >= c["time_stop_minutes"]:
                return (f"time stop: no {1 + c['take_profit_pct'] / 100:g}x after "
                        f"{hours * 60:.0f} min ({change_pct:+.0f}%)")
            return None
        if from_peak <= -c["trailing_stop_pct"]:
            return f"trailing stop after profit: down {-from_peak:.0f}% from peak"
        if hours >= c["max_hold_hours"]:
            return f"max hold: {hours:.0f}h after entry"
        return None


# ---------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------

def gecko_tokens(pools):
    """Token addresses from GeckoTerminal pools (ids look like 'solana_<mint>')."""
    found = []
    for pool in pools or []:
        rel = (pool or {}).get("relationships") or {}
        for side in ("base_token", "quote_token"):
            tid = ((rel.get(side) or {}).get("data") or {}).get("id") or ""
            mint = tid.split("_", 1)[1] if tid.startswith("solana_") else ""
            if mint and mint not in QUOTE_MINTS and mint not in found:
                found.append(mint)
    return found


def from_ms(ms):
    ms = to_float(ms)
    return datetime.fromtimestamp(ms / 1000, timezone.utc) if ms else None


def from_iso(text):
    """Parse RugCheck times like 2026-09-30T03:13:46.809333095Z."""
    if not text:
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(text)).replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def hours_since(when, now):
    return (now - when).total_seconds() / 3600


def seed_prices(pair):
    """Rough price history, oldest first, from DexScreener's % changes."""
    price = to_float(pair.get("priceUsd"))
    if not price:
        return []
    points = []
    for window in ("h6", "h1", "m5"):
        change = to_float((pair.get("priceChange") or {}).get(window))
        if change is not None and change > -100:
            points.append(price / (1 + change / 100))
    return points + [price]


def observe(entry, prices):
    """Update a watchlist entry's peak and lows with new price readings."""
    for p in prices:
        if not p or p <= 0:
            continue
        if entry.get("peak") is None or p > entry["peak"]:
            entry["peak"] = p
            entry["low_before_peak"] = min(entry.get("low") or p, p)
        entry["low"] = p if entry.get("low") is None else min(entry["low"], p)


# ---------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------

def first_checks(pair, entry, e, now):
    """Checks that only need DexScreener data (cheap)."""
    checks = []
    dex = pair.get("dexId", "unknown")
    checks.append(Check("Graduated (PumpSwap/Raydium)",
                        PASS if dex in e["allowed_dexes"] else FAIL, f"trades on '{dex}'"))

    graduated = from_ms(pair.get("pairCreatedAt"))
    need = e["min_minutes_since_graduation"]
    if graduated is None:
        checks.append(Check(f"Graduated {need:g}+ min ago", FAIL, "pool creation time unknown"))
    else:
        mins = hours_since(graduated, now) * 60
        checks.append(Check(f"Graduated {need:g}+ min ago", PASS if mins >= need else FAIL,
                            f"{mins:.0f} min ago"))

    created = from_iso(entry.get("created_at")) or graduated
    limit = e["max_token_age_hours"]
    if created is None:
        checks.append(Check(f"Token under {limit:g}h old", FAIL, "age unknown"))
    else:
        age = hours_since(created, now)
        checks.append(Check(f"Token under {limit:g}h old", PASS if age <= limit else FAIL,
                            f"{age:.1f}h old"))

    liq = to_float((pair.get("liquidity") or {}).get("usd"))
    ok = liq is not None and liq >= e["min_liquidity_usd"]
    checks.append(Check("Liquidity", PASS if ok else FAIL,
                        f"{money(liq)} (need at least {money(e['min_liquidity_usd'])})"))
    checks.extend(pullback_checks(pair, entry, e))
    return checks


def pullback_checks(pair, entry, e):
    price = to_float(pair.get("priceUsd"))
    peak, base = entry.get("peak"), entry.get("low_before_peak")
    if not (price and peak and base):
        return [Check("Pullback after a spike", FAIL, "no price history")]
    spike = (peak / base - 1) * 100
    drop = (1 - price / peak) * 100
    lo, hi = e["pullback_min_pct"], e["pullback_max_pct"]
    if spike < e["min_spike_pct"]:
        pull = Check("Pullback after a spike", FAIL,
                     f"no spike yet (+{spike:.0f}% at most, need +{e['min_spike_pct']:g}%)")
    elif drop < lo:
        pull = Check("Pullback after a spike", FAIL,
                     f"only {max(drop, 0):.0f}% below the peak (need {lo:g}-{hi:g}%)")
    elif drop > hi:
        pull = Check("Pullback after a spike", FAIL,
                     f"{drop:.0f}% below the peak: a collapse, not a pullback")
    else:
        pull = Check("Pullback after a spike", PASS,
                     f"{drop:.0f}% below the peak after a +{spike:.0f}% spike")

    m5 = to_float((pair.get("priceChange") or {}).get("m5"))
    hold = Check("Holding (last 5 min)", PASS if m5 is not None and m5 >= 0 else FAIL,
                 "unknown" if m5 is None else f"{m5:+.1f}% in 5 min")

    tx = (pair.get("txns") or {}).get("h1") or {}
    buys, sells = tx.get("buys"), tx.get("sells")
    if buys is None or sells is None:
        flow = Check("More buys than sells (1h)", FAIL, "no transaction data")
    else:
        flow = Check("More buys than sells (1h)", PASS if buys > sells else FAIL,
                     f"{buys:,} buys vs {sells:,} sells")
    return [pull, hold, flow]


def safety_checks(report, pair, e, dead_creators, now):
    """Checks that need the RugCheck report."""
    if not report:
        return [Check("Safety data", FAIL, "RugCheck has no report for this token")]
    checks = []

    created = from_iso(report.get("detectedAt"))
    limit = e["max_token_age_hours"]
    if created is None:
        checks.append(Check(f"Token under {limit:g}h old (RugCheck)", FAIL, "age unknown"))
    else:
        age = hours_since(created, now)
        checks.append(Check(f"Token under {limit:g}h old (RugCheck)",
                            PASS if age <= limit else FAIL, f"created {age:.1f}h ago"))

    token = report.get("token") or {}
    for label, key in (("Mint authority revoked", "mintAuthority"),
                       ("Freeze authority revoked", "freezeAuthority")):
        value = token.get(key, report.get(key))
        checks.append(Check(label, PASS if not value else FAIL,
                            "revoked" if not value else f"still active ({value[:8]}...)"))
    checks.append(_lp_check(report, pair, e))

    holders = real_holders(report, pair, {"exclude_pools_from_holders": True})
    if not holders:
        checks.append(Check("Top 10 holders", FAIL, "no holder data"))
    else:
        top10 = sum(to_float(h.get("pct")) or 0.0 for h in holders[:10])
        limit = e["max_top10_holders_pct"]
        checks.append(Check("Top 10 holders", PASS if top10 < limit else FAIL,
                            f"own {top10:.1f}% (need under {limit:g}%)"))

    networks = report.get("insiderNetworks") or []
    linked = report.get("graphInsidersDetected") or 0
    flagged = sum(1 for h in report.get("topHolders") or [] if h.get("insider"))
    if networks or linked or flagged:
        checks.append(Check("No insider flags", FAIL,
                            f"{len(networks)} network(s), {linked} linked wallet(s), "
                            f"{flagged} insider top holder(s)"))
    else:
        checks.append(Check("No insider flags", PASS, "none detected"))

    checks.append(creator_check(report, e, dead_creators))
    return checks


def creator_check(report, e, dead_creators):
    name = "Creator has no dead tokens"
    creator = report.get("creator")
    if not creator:
        return Check(name, FAIL, "creator unknown")
    if creator in dead_creators:
        return Check(name, FAIL, "this creator launched a token that died")
    others = report.get("creatorTokens")
    if isinstance(others, list):
        dead = [t for t in others
                if (to_float((t or {}).get("marketCap")) or 0) < e["dead_token_max_mcap_usd"]]
        if dead:
            return Check(name, FAIL, f"{len(dead)} of the creator's {len(others)} other "
                                     f"token(s) are worth under {money(e['dead_token_max_mcap_usd'])}")
        return Check(name, PASS, f"their {len(others)} other token(s) are still alive")
    return Check(name, PASS, f"none known ({len(dead_creators)} bad creators remembered)")


def copycat_check(api, address, pair, e, now):
    name = "Not a copycat name"
    base = pair.get("baseToken") or {}
    symbol, title = (base.get("symbol") or "").strip(), (base.get("name") or "").strip()
    if not symbol:
        return Check(name, FAIL, "token has no symbol")
    pairs = []
    try:
        for query in dict.fromkeys(q for q in (symbol, title) if q):
            pairs.extend(api.search_pairs(query))
    except RateLimited:
        raise
    except ApiError as exc:
        return Check(name, FAIL, f"couldn't check for copycats ({exc})")
    since = now - timedelta(days=e["copycat_window_days"])
    days = f"{e['copycat_window_days']:g}"
    others = {}  # address -> highest liquidity seen for that token (0 if unknown)
    own = to_float((pair.get("liquidity") or {}).get("usd"))
    for p in pairs:
        other = p.get("baseToken") or {}
        liq = to_float((p.get("liquidity") or {}).get("usd"))
        if p.get("chainId") != "solana" or other.get("address") is None:
            continue
        if other["address"] == address:
            if liq is not None:
                own = max(own or 0.0, liq)
            continue
        same = ((other.get("symbol") or "").strip().lower() == symbol.lower()
                or (title and (other.get("name") or "").strip().lower() == title.lower()))
        created = from_ms(p.get("pairCreatedAt"))
        if same and (created is None or created >= since):  # unknown age counts as new
            others[other["address"]] = max(others.get(other["address"], 0.0), liq or 0.0)
    if not others:
        return Check(name, PASS, f"no other {symbol} in the last {days} days")
    # Same-named tokens are allowed only for the one with the most liquidity.
    top = max(others.values())
    if own is not None and own > top:
        return Check(name, PASS, f"most liquidity of {len(others) + 1} tokens called {symbol} "
                                 f"in the last {days} days ({money(own)} vs {money(top)})")
    return Check(name, FAIL, f"{len(others)} other token(s) called {symbol} in the last {days} "
                             f"days, one with more liquidity ({money(own)} vs {money(top)})")


# ---------------------------------------------------------------------
# The strategy
# ---------------------------------------------------------------------

class EarlyStrategy:
    name = "early"

    def __init__(self, cfg, data_folder):
        self.e = cfg["early"]
        self.pt = self.e["paper_trading"]
        self.trader = EarlyTrader(self.pt, os.path.join(data_folder, "early"))

    def fetch(self, api, now=None, out=print):
        """Everything from the internet, before any paper trade changes.
        Returns a plan for apply(). Raises ApiError/RateLimited on failure, in
        which case this strategy simply skips the run."""
        now = now or now_utc()
        e, trader = self.e, self.trader
        state = trader.state
        watch_before = state.get("watchlist") or {}
        dead_creators = set(state.get("dead_creators") or [])
        held = {p["address"] for p in trader.open_positions}

        from_dex = find_candidates(api.latest_profiles(), api.latest_boosts())
        from_gecko, gecko_note = [], None
        for page in range(1, e["gecko_pages"] + 1):
            try:
                from_gecko += [t for t in gecko_tokens(api.gecko_new_pools(page))
                               if t not in from_gecko]
            except RateLimited:
                raise
            except ApiError as exc:  # GeckoTerminal is an extra source; carry on without it
                gecko_note = f"GeckoTerminal unavailable this run: {exc}"
                break
        addresses = list(dict.fromkeys(list(held) + list(watch_before) + from_dex + from_gecko))
        pairs = api.pairs_for_tokens(addresses) if addresses else []

        # Prices for the positions we hold, from the pool we "bought" in.
        prices = {}
        for pos in trader.open_positions:
            pair = next((p for p in pairs if p.get("pairAddress") == pos["pair_address"]), None)
            pair = pair or best_pair(pairs, pos["address"], e["allowed_dexes"])
            price = to_float((pair or {}).get("priceUsd"))
            if price:
                prices[pos["address"]] = price

        watch, dead_add, waiting, results = {}, set(), Counter(), []
        new_lookups = 0
        for addr in addresses:
            if addr in held:
                continue
            pair = best_pair(pairs, addr, e["allowed_dexes"])
            if not pair or pair.get("dexId") not in e["allowed_dexes"]:
                continue  # not graduated yet; it'll show up again when it does
            entry = copy.deepcopy(watch_before.get(addr))
            if entry is None:
                graduated = from_ms(pair.get("pairCreatedAt"))
                if graduated and hours_since(graduated, now) > e["max_token_age_hours"]:
                    continue  # graduated too long ago to be a young token
                if new_lookups >= e["max_new_tokens_per_run"]:
                    waiting["too many new tokens this run, next run"] += 1
                    continue
                new_lookups += 1
                try:
                    report = api.rugcheck_report(addr)
                except RateLimited:
                    raise
                except ApiError:
                    report = None
                base = pair.get("baseToken") or {}
                entry = {"symbol": base.get("symbol", "?"), "first_seen": now.isoformat(),
                         "created_at": (report or {}).get("detectedAt"),
                         "creator": (report or {}).get("creator")}
                observe(entry, seed_prices(pair))
                if (report or {}).get("rugged"):
                    dead_add.add(entry["creator"])
                    continue
            else:
                observe(entry, [to_float(pair.get("priceUsd"))])

            created = from_iso(entry.get("created_at")) or from_ms(pair.get("pairCreatedAt"))
            if created and hours_since(created, now) > e["max_token_age_hours"]:
                continue  # too old now: drop it from the watchlist
            mcap = to_float(pair.get("marketCap")) or to_float(pair.get("fdv"))
            if mcap is not None and mcap < e["dead_token_max_mcap_usd"]:
                if entry.get("creator"):
                    dead_add.add(entry["creator"])
                continue  # it died: remember who made it
            watch[addr] = entry

            if not trader.can_buy(addr):
                continue
            checks = first_checks(pair, entry, e, now)
            failed = next((c for c in checks if c.status == FAIL), None)
            if failed:
                waiting[failed.name] += 1
                continue
            try:
                report = api.rugcheck_report(addr)
            except RateLimited:
                raise
            except ApiError:
                report = None  # fails the "Safety data" check below
            checks += safety_checks(report, pair, e, dead_creators | dead_add, now)
            if all(c.status == PASS for c in checks):
                checks.append(copycat_check(api, addr, pair, e, now))
            base = pair.get("baseToken") or {}
            result = Result(addr, base.get("symbol", "?"), base.get("name", "?"), pair, checks)
            if report:
                result.top_holders = real_holders(report, pair, {})[:10]
            result.entry = entry
            results.append(result)

        return {"now": now, "prices": prices, "watch": watch, "dead_add": dead_add,
                "results": results, "waiting": waiting, "gecko_note": gecko_note,
                "sources": {"DexScreener": len(from_dex), "GeckoTerminal": len(from_gecko),
                            "watchlist": len(watch_before)}}

    def apply(self, plan, issue_details, out=print):
        """Make the pretend trades. Returns the tokens that passed."""
        from screener.filters import format_report

        trader, state, now = self.trader, self.trader.state, plan["now"]
        state["watchlist"] = plan["watch"]
        dead = list(dict.fromkeys((state.get("dead_creators") or [])
                                  + sorted(c for c in plan["dead_add"] if c)))
        state["dead_creators"] = dead[-MAX_DEAD_CREATORS:]

        src = plan["sources"]
        out(f"  Sources: {src['DexScreener']} from DexScreener, {src['GeckoTerminal']} from "
            f"GeckoTerminal, {src['watchlist']} already on the watchlist")
        if plan["gecko_note"]:
            out(f"  ({plan['gecko_note']})")
        out(f"  Watching {len(plan['watch'])} young graduated token(s).")
        if plan["waiting"]:
            out("  Not ready yet: " + ", ".join(f"{n} {why}" for why, n
                                                 in plan["waiting"].most_common()))
        out("")

        for s in trader.update(plan["prices"], when=now):
            out(f"  SELL {s['symbol']:<10} {s['reason']:<45} P&L ${s['pnl_usd']:+.2f}")
            if s["closed"] and s["position"].get("issue_details"):
                state.setdefault("issues_to_close", []).append(s["position"])

        for r in plan["results"]:
            out(format_report(r))
            out("")
        passed = [r for r in plan["results"] if r.passed]
        for r in passed:
            pos = trader.buy(r, when=now)
            if not pos:
                continue
            out(f"  BUY  {r.symbol:<10} ${self.pt['buy_amount_usd']} at ${r.price:.10g}")
            created = from_iso(r.entry.get("created_at"))
            graduated = from_ms(r.pair.get("pairCreatedAt"))
            pull = next(c.detail for c in r.checks if c.name == "Pullback after a spike")
            pos["issue_details"] = issue_details(r, now, extra=[
                ("Token age", f"{hours_since(created, now):.1f}h" if created else "unknown"),
                ("Graduated", f"{hours_since(graduated, now) * 60:.0f} min ago"
                 if graduated else "unknown"),
                ("Pullback", pull),
            ])
        if not passed:
            out("  No young token was in a clean pullback this run, so nothing was bought.")
        trader.save()
        return passed
