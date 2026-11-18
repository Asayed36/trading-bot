"""Look up the saved market prices (Bitcoin, Ethereum, Solana) minute by minute.

    python market_prices.py --at "2026-11-18 19:00" --minutes 60

prints one line per minute from that UTC time to 60 minutes later, with each
price and its change in percent from the first line. The prices come from the
once-a-minute log the server saves in data/market/prices-YYYY-MM-DD.csv
(screener/market_prices.py) and pushes every hour: run "git pull" first on your
own computer. Blank = that minute's price is not known.

Read-only: it only reads the saved files. It asks no website anything.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

from screener.market_prices import FOLDER, PRICE_COLUMNS, read_rows
from screener.settings import HERE, load_config

NAMES = {"btc_usd": "BTC", "eth_usd": "ETH", "sol_usd": "SOL"}


def lines(folder, start, minutes):
    """The printed lines for start .. start + minutes (UTC, naive datetimes)."""
    end = start + timedelta(minutes=minutes)
    rows = read_rows(folder, start, end)
    first = {}
    for c in PRICE_COLUMNS:          # the first known price of each coin is the 0 %
        for i in range(minutes + 1):
            value = (rows.get(f"{start + timedelta(minutes=i):%Y-%m-%d %H:%M}") or {}).get(c)
            if value is not None:
                first[c] = value
                break
    out = [f"Market prices in USD (Binance, USDT pairs), {start:%Y-%m-%d %H:%M} to "
           f"{end:%Y-%m-%d %H:%M} UTC; change from the first line",
           "time (UTC)        " + "".join(f"{NAMES[c]:>14} {'change':>8}" for c in PRICE_COLUMNS)]
    found = 0
    for i in range(minutes + 1):
        minute = f"{start + timedelta(minutes=i):%Y-%m-%d %H:%M}"
        row = rows.get(minute)
        if row is None:
            out.append(f"{minute}  no row saved")
            continue
        found += 1
        cells = []
        for c in PRICE_COLUMNS:
            value = row.get(c)
            if value is None:
                cells.append(f"{'-':>14} {'':>8}")
            else:
                change = (value / first[c] - 1) * 100
                cells.append(f"{value:>14,.2f} {change:>+7.2f}%")
        out.append(f"{minute}  " + "".join(cells))
    if not found:
        out.append(f"No saved prices in this time range ({folder}). The server saves one row a "
                   "minute and pushes them every hour: run \"git pull\" first.")
    else:
        late = [c for c in PRICE_COLUMNS
                if first.get(c) is not None and rows.get(f"{start:%Y-%m-%d %H:%M}", {}).get(c) is None]
        if late:
            out.append("Note: the first line has no price for " + ", ".join(NAMES[c] for c in late)
                       + "; its change is from the first minute that has one.")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--at", required=True, metavar='"YYYY-MM-DD HH:MM"',
                        help="the first minute, in UTC")
    parser.add_argument("--minutes", type=int, default=60,
                        help="how many minutes after it to show (default 60)")
    parser.add_argument("--folder", help="where the price files are (default data/market)")
    args = parser.parse_args(argv)
    try:
        start = datetime.strptime(args.at.strip().replace("T", " "), "%Y-%m-%d %H:%M")
    except ValueError:
        parser.error('--at must look like "2026-11-18 19:00" (UTC)')
    if not 0 <= args.minutes <= 10080:
        parser.error("--minutes must be between 0 and 10080 (one week)")
    folder = args.folder or os.path.join(HERE, load_config()["files"]["data_folder"], FOLDER)
    print("\n".join(lines(folder, start, args.minutes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
