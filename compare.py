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
from screener.compare import MARKER, report
from screener.github_issues import GitHubError, GitHubIssues
from screener.paper_trader import now_utc

LABEL = "daily-comparison"


def pick_day(text):
    today = now_utc().date()
    if text in (None, "today"):
        return today.isoformat()
    if text == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return text


def post_issue(gh, day, body):
    """Open the comparison issue for `day` (once) and close older ones."""
    gh.ensure_label(LABEL, "5319e7", "Daily comparison of the paper strategies")
    already, older = None, []
    for issue in gh.issues_with_label():
        if MARKER.format(day) in (issue.get("body") or ""):
            already = issue["number"]
        elif issue.get("state") == "open":
            older.append(issue["number"])
    if already:
        print(f"Comparison for {day} already posted as issue #{already}.")
        return
    number = gh.create(f"Daily comparison: {day}", body)
    print(f"Posted comparison as issue #{number}.")
    for n in older:
        gh.close(n)


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
    body = report(strategies, day)
    print(body)

    if args.github_issue:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not (token and repo):
            print("\n--github-issue needs GITHUB_TOKEN and GITHUB_REPOSITORY.")
            return 1
        try:
            post_issue(GitHubIssues(token, repo, LABEL), day, body)
        except GitHubError as exc:
            print(f"\nCould not post to GitHub: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
