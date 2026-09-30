"""Solana memecoin screener with PAPER trading (pretend money only).

How to run it:
    python run.py            <- real data from DexScreener + RugCheck
    python run.py --demo     <- made-up example data, to see how it works offline

This program is READ-ONLY. It never connects to a wallet or exchange, never
asks for keys or seed phrases, and never places a real order.
"""

import argparse
import os
import sys
import tomllib

from screener.api import ApiError, PublicApi, RateLimited
from screener.filters import best_pair, evaluate, find_candidates, format_report, market_checks
from screener.paper_trader import PaperTrader

HERE = os.path.dirname(os.path.abspath(__file__))
LINE = "=" * 78

# Exit code for "rate limited, run skipped" (EX_TEMPFAIL). The GitHub workflow
# treats it as a skipped run, not a failure, and saves nothing.
EXIT_RATE_LIMITED = 75


def load_config(path=os.path.join(HERE, "config.toml")):
    with open(path, "rb") as fh:
        return tomllib.load(fh)


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


def screen(api, cfg, out):
    """Find new tokens and run every check on them. Network only: this never
    touches the paper positions or the journal."""
    f = cfg["filters"]
    addresses = find_candidates(api.latest_profiles(), api.latest_boosts())
    out(f"Found {len(addresses)} Solana candidates in DexScreener's latest profiles + boosts.\n")
    pairs = api.pairs_for_tokens(addresses) if addresses else []

    results = []
    for addr in addresses:
        pair = best_pair(pairs, addr, f["allowed_dexes"])
        market_ok = all(c.status == "PASS" for c in market_checks(pair, f))
        skip = cfg["api"]["skip_safety_if_market_fails"] and not market_ok
        report = None
        if not skip:
            try:
                report = api.rugcheck_report(addr)
            except RateLimited:
                raise  # skip the whole run rather than screen with gaps
            except ApiError as exc:
                out(f"  (RugCheck failed for {addr}: {exc})")
        result = evaluate(addr, pair, report, f, safety_skipped=skip)
        results.append(result)
        out(format_report(result))
        out("")
    return results


def run(api, cfg, data_folder, out=print):
    f, pt = cfg["filters"], cfg["paper_trading"]
    trader = PaperTrader(pt, data_folder)

    # Fetch everything from the internet BEFORE changing any paper trades, so
    # a failed or rate-limited run leaves positions and journal untouched.
    prices = current_prices(api, trader.open_positions, f["allowed_dexes"])
    screen_lines = []
    results = screen(api, cfg, screen_lines.append)

    # ---- Step 1: check the pretend trades we already hold ----
    out(LINE)
    out(f"STEP 1: Updating {len(trader.open_positions)} open paper position(s)")
    out(LINE)
    for s in trader.update(prices):
        out(f"  SELL {s['symbol']:<10} {s['reason']:<45} P&L ${s['pnl_usd']:+.2f}")
    for pos in trader.open_positions:
        if pos["address"] not in prices:
            out(f"  (no price for {pos['symbol']} this run - will retry next time)")
    trader.save()

    # ---- Step 2: new tokens and their PASS/FAIL report ----
    out("")
    out(LINE)
    out("STEP 2: Screening new tokens")
    out(LINE)
    for line in screen_lines:
        out(line)

    # ---- Step 3: pretend-buy anything that passed everything ----
    out(LINE)
    out("STEP 3: Paper buys")
    out(LINE)
    passed = [r for r in results if r.passed]
    if not passed:
        out("  No token passed every filter this run, so nothing was bought.")
    for r in passed:
        pos = trader.buy(r)
        if pos:
            out(f"  BUY  {r.symbol:<10} ${pt['buy_amount_usd']} at ${r.price:.10g}")
        else:
            out(f"  skip {r.symbol:<10} already bought before")
    trader.save()

    # ---- Summary ----
    out("")
    out(LINE)
    out("SUMMARY")
    out(LINE)
    out(f"  Tokens checked: {len(results)}   passed: {len(passed)}   "
        f"failed: {len(results) - len(passed)}")
    out(f"  Open paper positions: {len(trader.open_positions)}")
    for pos in trader.open_positions:
        change = (pos["last_price"] / pos["entry_price"] - 1) * 100
        out(f"    {pos['symbol']:<10} entry ${pos['entry_price']:.10g}  now {change:+.1f}%  "
            f"holding {pos['remaining_fraction'] * 100:.0f}%")
    out(f"  Total realized paper P&L: ${trader.state['running_total_pnl_usd']:+.2f}")
    out(f"  Journal: {trader.journal_path}")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true",
                        help="use made-up example data instead of the internet")
    args = parser.parse_args()
    cfg = load_config()

    if args.demo:
        from screener.demo import DemoApi
        print("*** DEMO MODE: all tokens and prices below are MADE UP. ***\n")
        api, folder = DemoApi(), os.path.join(HERE, "demo_data")
    else:
        api = PublicApi(cfg["api"]["timeout_seconds"], cfg["api"]["rugcheck_delay_seconds"])
        folder = os.path.join(HERE, cfg["files"]["data_folder"])

    try:
        run(api, cfg, folder)
    except RateLimited as exc:
        print(f"\nRate limited: {exc}")
        print("Skipping this run. Nothing was traded; try again later.")
        return EXIT_RATE_LIMITED
    except ApiError as exc:
        print(f"\nCould not get data: {exc}")
        print("Check your internet connection and try again. Nothing was traded.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
