"""Runs the "trend" paper strategy once (screener/trend.py): fetches the daily candles
that are missing, then processes every day not yet processed. Idempotent.

    python trend_bot.py                  <- what the "Trend forward test" workflow runs
    python trend_bot.py --now 2026-10-12T00:10:00+00:00   <- as if it were then (testing)

PAPER ONLY: virtual money, public daily prices, no wallet, no key, no order.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from screener.settings import HERE, load_config
from screener.trend import Trend


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--now", default=None, help="ISO time to act as 'now' (default: the real time)")
    p.add_argument("--data", default=None, help="the data folder (default: data/trend)")
    args = p.parse_args(argv)
    cfg = load_config()
    if not cfg.get("trend", {}).get("enabled"):
        print("The trend strategy is turned off ([trend] enabled = false).")
        return 0
    folder = args.data or os.path.join(HERE, cfg["files"]["data_folder"], "trend")
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = Trend(cfg, folder).run(now)
    print(f"trend: {len(days)} day(s) processed" + (f" ({days[0]} to {days[-1]})" if days else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
