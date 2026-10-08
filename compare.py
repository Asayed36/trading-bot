"""Compare the paper strategies' results, for one day and all time.

How to run it:
    python compare.py                    <- today so far (UTC)
    python compare.py --date yesterday   <- a full day
    python compare.py --date 2026-10-01

With --github-issue (used by the daily GitHub workflow) it also posts the
comparison as an issue labelled "daily-comparison", closing the previous one.
Read-only apart from that: it never trades and never touches a wallet.
"""

import argparse
import os
import sys
from datetime import timedelta

from run import HERE, load_config
from screener.compare import (MARKER, actual_intervals, helius_lines, report,
                              schedule_lines)
from screener.github_issues import GitHubError, GitHubIssues
from screener.health import RUN_EVENTS, health_lines
from screener.paper_trader import now_utc

LABEL = "daily-comparison"
TITLE = "Daily comparison: {}"


def pick_day(text):
    today = now_utc().date()
    if text in (None, "today"):
        return today.isoformat()
    if text == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return text


def post_issue(gh, day, body):
    """Open the comparison issue for `day` (once) and close older ones.
    An issue already there for that day (found by its title or its marker,
    open or closed) means it was posted: GitHub's schedule and the server's
    backup trigger can both start a run for the same day."""
    gh.ensure_label(LABEL, "5319e7", "Daily comparison of the paper strategies")
    title = TITLE.format(day)
    already, older = None, []
    for issue in gh.issues_with_label():
        if issue.get("title") == title or MARKER.format(day) in (issue.get("body") or ""):
            already = issue["number"]
        elif issue.get("state") == "open":
            older.append(issue["number"])
    if already:
        print(f"Comparison for {day} already posted as issue #{already}.")
        return
    number = gh.create(title, body)
    print(f"Posted comparison as issue #{number}.")
    for n in older:
        gh.close(n)


def stopped(cfg, name):
    """True for a strategy with stopped = true in config.toml: no new buys,
    its last positions finishing under their exits."""
    if name in ("main", "early", "robinhood"):
        return bool(cfg.get(name, {}).get("stopped"))
    if name == "main (1 min)":
        return bool(cfg.get("main_1min", {}).get("stopped"))
    for v in cfg.get("main_1min", {}).get("versions", []):
        if name == (v.get("label") or f"main (1 min) {v['name']}"):
            return bool(v.get("stopped"))
    if name.startswith("launch "):
        return bool(cfg.get("launch", {}).get("stopped"))
    if name.startswith("momentum "):
        return any(v.get("stopped") for v in cfg.get("momentum", {}).get("variants", [])
                   if name == f"momentum {v['name']}")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default="today",
                        help="'today' (default), 'yesterday' or YYYY-MM-DD, in UTC")
    parser.add_argument("--github-issue", action="store_true",
                        help="also post it as a GitHub issue (needs GITHUB_TOKEN and "
                             "GITHUB_REPOSITORY, which GitHub Actions provides)")
    args = parser.parse_args()
    cfg = load_config()
    day = pick_day(args.date)

    folder = os.path.join(HERE, cfg["files"]["data_folder"])
    strategies = [("main", folder, cfg["paper_trading"]["round_trip_cost_pct"])]
    if cfg.get("early", {}).get("enabled"):
        strategies.append(("early", os.path.join(folder, "early"),
                           cfg["early"]["paper_trading"]["round_trip_cost_pct"]))
    extra = []
    if cfg.get("convergence", {}).get("enabled"):
        conv = os.path.join(folder, "convergence")
        strategies.append(("convergence", conv,
                           cfg["convergence"]["paper_trading"]["round_trip_cost_pct"]))
    # Health checks that ask GitHub (failed runs, real run intervals, the
    # launch bot's last push) need GITHUB_TOKEN and GITHUB_REPOSITORY; without
    # them they say so.
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    gh = GitHubIssues(token, repo, LABEL) if token and repo else None
    # The workflow's schedule change only affected these strategies (news
    # always checks every 15 minutes).
    schedule_path = os.path.join(folder, "schedule.json")
    actual = {}
    if gh is not None:
        workflow = cfg.get("health", {}).get("workflow", "screener.yml")
        try:
            actual = actual_intervals(
                schedule_path, lambda a, b: sum(gh.count_runs(workflow, a, b, event=e)
                                                for e in RUN_EVENTS), now_utc())
        except GitHubError as exc:
            print(f"(Couldn't get the real run intervals from GitHub: {exc})", file=sys.stderr)
    extra += schedule_lines(strategies, schedule_path, actual) + [""]
    if cfg.get("main_1min", {}).get("enabled"):
        # Main's checks every minute, on your server (pushed about once an
        # hour): next to main. Not in the schedule split above, which is
        # about the GitHub schedule.
        strategies.insert(1, ("main (1 min)", os.path.join(folder, cfg["main_1min"]["folder"]),
                              cfg["paper_trading"]["round_trip_cost_pct"]))
        # Its paper versions (extra entry rules, same exits and costs): next to it.
        for i, v in enumerate(v for v in cfg["main_1min"].get("versions", [])
                              if v.get("enabled", True)):
            strategies.insert(2 + i, (v.get("label") or f"main (1 min) {v['name']}",
                                      os.path.join(folder, v["folder"]),
                                      cfg["paper_trading"]["round_trip_cost_pct"]))
    if cfg.get("news", {}).get("enabled"):
        strategies.append(("news", os.path.join(folder, "news"),
                           cfg["news"]["paper_trading"]["round_trip_cost_pct"]))
    if cfg.get("news", {}).get("enabled") and cfg.get("news_listings", {}).get("enabled"):
        # The exchange listings, checked every minute on your server (pushed
        # about once an hour), with news's checks, costs and exits: next to news.
        strategies.append(("news (listings)",
                           os.path.join(folder, cfg["news_listings"]["folder"]),
                           cfg["news"]["paper_trading"]["round_trip_cost_pct"]))
        fast = cfg["news_listings"].get("fast") or {}
        if fast.get("enabled"):
            # The same signals at the same moment, exits within hours: next to it.
            strategies.append((fast.get("label", "news (listings) fast"),
                               os.path.join(folder, cfg["news_listings"]["folder"],
                                            fast["folder"]),
                               fast["paper_trading"]["round_trip_cost_pct"]))
    if cfg.get("robinhood", {}).get("enabled"):
        # Open positions are valued after selling costs: slippage plus the
        # higher of the launchpads' pool fees.
        rc = cfg["robinhood"]
        sell_cost = rc["paper_trading"]["slippage_pct"] + max(
            (lp["pool_fee_pct"] for lp in rc["launchpads"]), default=0)
        strategies.append(("robinhood", os.path.join(folder, "robinhood"), sell_cost))
    if cfg.get("launch", {}).get("enabled"):
        # Runs on your own server and pushes here about once an hour.
        lp = cfg["launch"]["paper_trading"]
        for speed in cfg["launch"]["speeds"]:
            sell_cost = lp["bot_fee_pct"] + lp["platform_fee_pct"] + speed["extra_slippage_pct"]
            strategies.append((f"launch {speed['name']}",
                               os.path.join(folder, "launch", speed["name"]), sell_cost))
    if cfg.get("momentum", {}).get("enabled"):
        # Runs on your server too: the launch bot's costs, one column per variant.
        lp, m = cfg["launch"]["paper_trading"], cfg["momentum"]
        speed = next(s for s in cfg["launch"]["speeds"] if s["name"] == m["costs_like_speed"])
        sell_cost = lp["bot_fee_pct"] + lp["platform_fee_pct"] + speed["extra_slippage_pct"]
        for v in m["variants"]:
            strategies.append((f"momentum {v['name']}",
                               os.path.join(folder, m["folder"], v["name"]), sell_cost))
    if cfg.get("convergence", {}).get("enabled"):
        extra += helius_lines(os.path.join(folder, "convergence"), day)
    strategies = [(name + (" (stopped)" if stopped(cfg, name) else ""), path, cost)
                  for name, path, cost in strategies]
    health = health_lines(folder, cfg, now_utc(), gh)
    body = report(strategies, day, extra, health)
    print(body)

    if args.github_issue:
        if gh is None:
            print("\n--github-issue needs GITHUB_TOKEN and GITHUB_REPOSITORY.")
            return 1
        try:
            post_issue(gh, day, body)
        except GitHubError as exc:
            print(f"\nCould not post to GitHub: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
