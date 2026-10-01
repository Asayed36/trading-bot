"""Solana memecoin screener with PAPER trading (pretend money only).

How to run it:
    python run.py            <- real data from DexScreener + RugCheck
    python run.py --demo     <- made-up example data, to see how it works offline
    python run.py --github-issues   <- also open/close GitHub issues for tokens
                                       that pass (used by the GitHub workflow)

Each run paper-trades four strategies side by side: "main" (the filters in
[filters]), "early" (young tokens bought on a pullback, see [early] and
screener/early.py), "convergence" (3+ proven traders buying the same
token, see [convergence] and screener/convergence.py; needs a free Helius
API key in the HELIUS_API_KEY environment variable) and "news" (official
news about established coins, see [news] and screener/news.py; a free
CoinGecko key in COINGECKO_API_KEY is recommended). Compare them with
`python compare.py`.

This program is READ-ONLY. It never connects to a wallet or exchange, never
asks for keys or seed phrases, and never places a real order.
"""

import argparse
import json
import os
import sys
import tomllib

from screener.api import ApiError, PublicApi, RateLimited
from screener.filters import best_pair, evaluate, find_candidates, format_report, market_checks
from screener.convergence import ConvergenceStrategy
from screener.early import EarlyStrategy
from screener.github_issues import GitHubIssues, issue_details, sync
from screener.news import NewsHttp, NewsStrategy
from screener.paper_trader import PaperTrader, now_utc

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


def record_schedule(data_folder, every, now, out=print):
    """Remember when the workflow schedule changed, in data/schedule.json.
    Adds an entry the first time a run happens with a new interval."""
    path = os.path.join(data_folder, "schedule.json")
    data = {"history": []}
    if os.path.exists(path):
        with open(path) as fh:
            data = json.load(fh)
    history = data.setdefault("history", [])
    if history and history[-1]["every_minutes"] == every:
        return
    history.append({"every_minutes": every, "since": now.isoformat()})
    os.makedirs(data_folder, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
    out(f"\n(Schedule change recorded: every {every} minutes since {now:%Y-%m-%d %H:%M} UTC)")


def run(api, cfg, data_folder, out=print, issues=None, helius_key=None, rpc_factory=None,
        news_http=None, coingecko_key=None):
    f, pt = cfg["filters"], cfg["paper_trading"]
    trader = PaperTrader(pt, data_folder)

    # Fetch everything from the internet BEFORE changing any paper trades, so
    # a failed or rate-limited run leaves positions and journal untouched.
    prices = current_prices(api, trader.open_positions, f["allowed_dexes"])
    screen_lines = []
    results = screen(api, cfg, screen_lines.append)

    # The "early" strategy fetches its own data. If that fails (including a
    # rate limit from one of its sources), only the early strategy skips this
    # run; the main strategy carries on as normal.
    early, early_plan, early_skipped = None, None, None
    if cfg.get("early", {}).get("enabled"):
        early = EarlyStrategy(cfg, data_folder)
        try:
            early_plan = early.fetch(api)
        except ApiError as exc:
            early_skipped = f"{exc}"

    # Same for "convergence". Its Helius credit count is saved even when a
    # later step of its own fails (see ConvergenceStrategy.fetch).
    conv, conv_plan, conv_skipped = None, None, None
    if cfg.get("convergence", {}).get("enabled"):
        conv = ConvergenceStrategy(cfg, data_folder, helius_key, rpc_factory)
        try:
            conv_plan = conv.fetch(api)
        except ApiError as exc:
            conv_skipped = f"{exc}"

    # And "news" (official news about established coins). It only runs when
    # given a way to read the web (news_http): main() passes the real one,
    # the demo a fake one.
    news, news_plan, news_skipped = None, None, None
    if cfg.get("news", {}).get("enabled") and news_http is not None:
        news = NewsStrategy(cfg, data_folder, news_http, coingecko_key)
        try:
            news_plan = news.fetch()
        except ApiError as exc:
            news_skipped = f"{exc}"

    # ---- Step 1: check the pretend trades we already hold ----
    out(LINE)
    out(f"STEP 1: Updating {len(trader.open_positions)} open paper position(s)")
    out(LINE)
    for s in trader.update(prices):
        out(f"  SELL {s['symbol']:<10} {s['reason']:<45} P&L ${s['pnl_usd']:+.2f}")
        if s["closed"] and s["position"].get("issue_details"):
            # Its GitHub issue gets the result comment and is closed below.
            trader.state.setdefault("issues_to_close", []).append(s["position"])
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
            pos = trader.position(r.address)  # still held: it can get an issue too
        if pos and not pos.get("issue_details"):
            pos["issue_details"] = issue_details(r, now_utc())
    trader.save()

    # ---- Step 4: GitHub issues for tokens that passed ----
    if issues:
        out("")
        out(LINE)
        out("STEP 4: GitHub issues")
        out(LINE)
        sync(issues, trader, pt, cfg["github_issues"]["note"], out)
        trader.save()

    # ---- Step 5: the "early" strategy ----
    if early:
        out("")
        out(LINE)
        out("STEP 5: Early strategy (young tokens, pullback entry)")
        out(LINE)
        if early_skipped:
            out(f"  Skipped this run, nothing changed: {early_skipped}")
        else:
            early.apply(early_plan, issue_details, out)
            if issues:
                out("")
                out("  GitHub issues (early):")
                sync(issues, early.trader, early.pt, cfg["github_issues"]["note"], out,
                     strategy="early")
                early.trader.save()

    # ---- Step 6: the "convergence" strategy ----
    if conv:
        out("")
        out(LINE)
        out("STEP 6: Convergence strategy (3+ proven traders buying the same token)")
        out(LINE)
        if conv_skipped:
            out(f"  Skipped this run, nothing changed: {conv_skipped}")
        else:
            conv.apply(conv_plan, out)

    # ---- Step 7: the "news" strategy ----
    if news:
        out("")
        out(LINE)
        out("STEP 7: News strategy (official news about established coins)")
        out(LINE)
        if news_skipped:
            out(f"  Skipped this run, nothing changed: {news_skipped}")
        else:
            news.apply(news_plan, issue_details, out)
            if issues:
                out("")
                out("  GitHub issues (news):")
                sync(issues, news.trader, news.pt, cfg["github_issues"]["note"], out,
                     strategy="news")
                news.trader.save()

    # ---- Summary ----
    out("")
    out(LINE)
    out("SUMMARY (main strategy)")
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
    if early:
        et = early.trader
        out("")
        out("SUMMARY (early strategy)" + ("  - skipped this run" if early_skipped else ""))
        out(f"  Open paper positions: {len(et.open_positions)}")
        for pos in et.open_positions:
            change = (pos["last_price"] / pos["entry_price"] - 1) * 100
            out(f"    {pos['symbol']:<10} entry ${pos['entry_price']:.10g}  now {change:+.1f}%  "
                f"holding {pos['remaining_fraction'] * 100:.0f}%")
        out(f"  Total realized paper P&L: ${et.state['running_total_pnl_usd']:+.2f}")
        out(f"  Journal: {et.journal_path}")
    if conv:
        ct = conv.trader
        out("")
        out("SUMMARY (convergence strategy)" + ("  - skipped this run" if conv_skipped else ""))
        out(f"  Open paper positions: {len(ct.open_positions)}")
        for pos in ct.open_positions:
            change = (pos["last_price"] / pos["entry_price"] - 1) * 100
            out(f"    {pos['symbol']:<10} entry ${pos['entry_price']:.10g}  now {change:+.1f}%  "
                f"holding {pos['remaining_fraction'] * 100:.0f}%")
        out(f"  Total realized paper P&L: ${ct.state['running_total_pnl_usd']:+.2f}")
        out(f"  Journal: {ct.journal_path}")
    if news:
        nt = news.trader
        out("")
        out("SUMMARY (news strategy)" + ("  - skipped this run" if news_skipped else ""))
        out(f"  Open paper positions: {len(nt.open_positions)}")
        for pos in nt.open_positions:
            change = (pos["last_price"] / pos["entry_price"] - 1) * 100
            out(f"    {pos['symbol']:<10} entry ${pos['entry_price']:.10g}  now {change:+.1f}%  "
                f"holding {pos['remaining_fraction'] * 100:.0f}%")
        out(f"  Total realized paper P&L: ${nt.state['running_total_pnl_usd']:+.2f}")
        out(f"  Journal: {nt.journal_path}")
        out(f"  Candidates: {news.candidates_path}")
    if cfg.get("schedule"):
        record_schedule(data_folder, cfg["schedule"]["run_every_minutes"], now_utc(), out)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true",
                        help="use made-up example data instead of the internet")
    parser.add_argument("--github-issues", action="store_true",
                        help="open a GitHub issue for each token that passes, and close it "
                             "when the paper position closes (needs GITHUB_TOKEN and "
                             "GITHUB_REPOSITORY, which GitHub Actions provides)")
    args = parser.parse_args()
    cfg = load_config()

    issues = None
    if args.github_issues and not args.demo:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if token and repo:
            issues = GitHubIssues(token, repo, cfg["github_issues"]["label"])
        else:
            print("--github-issues needs GITHUB_TOKEN and GITHUB_REPOSITORY; "
                  "skipping GitHub issues.\n")

    helius_key, rpc_factory = os.environ.get("HELIUS_API_KEY") or None, None
    coingecko_key = os.environ.get("COINGECKO_API_KEY") or None
    if args.demo:
        from screener.demo import DemoApi, DemoNewsHttp, demo_rpc_factory
        print("*** DEMO MODE: all tokens, wallets, news and prices below are MADE UP. ***\n")
        api, folder = DemoApi(), os.path.join(HERE, "demo_data")
        helius_key, rpc_factory = None, demo_rpc_factory()
        news_http, coingecko_key = DemoNewsHttp(), None
    else:
        api = PublicApi(cfg["api"]["timeout_seconds"], cfg["api"]["rugcheck_delay_seconds"])
        folder = os.path.join(HERE, cfg["files"]["data_folder"])
        news_http = NewsHttp(cfg["api"]["timeout_seconds"])

    try:
        run(api, cfg, folder, issues=issues, helius_key=helius_key, rpc_factory=rpc_factory,
            news_http=news_http, coingecko_key=coingecko_key)
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
