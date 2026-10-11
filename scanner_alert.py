"""Scanner alerts: opens a GitHub issue labelled "scanner-alert" for a new exchange
listing or a news item the news AI check flagged (screener/scanner_alert.py).

    python scanner_alert.py --dry-run                     <- read the feeds, print, change nothing
    python scanner_alert.py --dry-run --fake Coinbase:TESTCOIN   <- a made-up listing, printed
    python scanner_alert.py --polls 13                    <- what the "Scanner alert" workflow runs

ALERTS ONLY: it trades nothing and uses no wallet or key. It needs only the
workflow's GITHUB_TOKEN (and GITHUB_REPOSITORY), and reads public feeds.
"""

import argparse
import os
import sys

from screener.news import NewsHttp
from screener.scanner_alert import Gh, Scanner
from screener.settings import load_config


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--polls", type=int, default=1, help="how many times to read the feeds")
    p.add_argument("--interval", type=int, default=60, help="seconds between two reads")
    p.add_argument("--dry-run", action="store_true",
                   help="print the issues that would be opened; open and save nothing")
    p.add_argument("--fake", default="", help='a made-up event: "Coinbase:TESTCOIN" '
                   'or "news:TESTCOIN" (goes through every rule, then really opens the issue '
                   "unless --dry-run)")
    args = p.parse_args(argv)
    cfg = load_config()
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    gh = Gh(token, repo, label="scanner-alert") if token and repo and not args.dry_run else None
    if not args.dry_run and gh is None:
        print("GITHUB_TOKEN and GITHUB_REPOSITORY are needed (or use --dry-run).")
        return 2
    scanner = Scanner(cfg, NewsHttp(cfg["api"]["timeout_seconds"]), gh, gh,
                      out=lambda s: print(s, flush=True))
    lines = scanner.run(polls=args.polls, interval=args.interval, fake=args.fake or None,
                        dry_run=args.dry_run, fetch_news=bool(gh))
    print("Sources, as seen from this machine:")
    for line in lines:
        print("  " + line)
    status = [line for line in lines if not line.startswith("WARNING")]
    if status and all(line.startswith("FAIL") for line in status):
        print("::warning::every exchange feed failed from this machine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
