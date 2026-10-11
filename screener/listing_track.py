"""A record of what happens to the price after every exchange-listing signal.

data/news-listings/listing_track.csv has ONE row per listing signal (bought
or not, passed or failed): who listed it, when the exchange announced it (when
the source says), when we detected it, CoinGecko's price at that moment, and
then CoinGecko's price about 1, 5, 15 and 60 minutes and 6 hours later.

It only RECORDS. It never decides anything: no buy, sell, filter or exit reads
this file, and it is written after the trading of each run is saved.

Where the prices come from: the detection price is the one the run had already
fetched to check the listing. The later ones come from CoinGecko's /coins/markets
call (the same call, same free plan and same monthly count as the open
positions' prices): one call per run, only when a checkpoint is due, for all
the due coins at once; a coin the run had already priced (a held one) costs no
call. A checkpoint missed for longer than its grace time (the bot was down,
CoinGecko failed or the monthly count was short) stays BLANK: blank means "not
saved", never zero.

The file is its own memory: a checkpoint is pending while its cells are blank
and it is not yet past its grace time.

PAPER TRADING ONLY: read-only GET requests, nothing signed or sent.
"""

import csv
import os
from datetime import datetime, timedelta

# (name, minutes after detection, grace in seconds: later than this and the
# checkpoint stays blank rather than being filled with a much later price)
CHECKPOINTS = (("1m", 1, 150), ("5m", 5, 150), ("15m", 15, 300),
               ("60m", 60, 900), ("6h", 360, 1800))
# Tracking calls are skipped when fewer than this many of the month's CoinGecko
# calls are left: the open positions' prices come first.
KEEP_CALLS = 500

BASE_COLUMNS = ["detected_utc", "source", "announced_utc", "announced_basis", "delay_seconds",
                "title", "coin_id", "symbol", "verdict", "bought", "note",
                "price_at_detection", "price_time_utc"]
COLUMNS = BASE_COLUMNS + [c for name, _, _ in CHECKPOINTS
                          for c in (f"price_{name}", f"time_{name}")]
TIME = "%Y-%m-%d %H:%M:%S"


def _parse(text):
    return datetime.strptime(text, TIME).replace(tzinfo=None)


def _naive(when):
    return when.replace(tzinfo=None) if when.tzinfo else when


class ListingTrack:
    def __init__(self, folder):
        self.path = os.path.join(folder, "listing_track.csv")

    # -- the file -------------------------------------------------------

    def rows(self):
        try:
            with open(self.path, newline="") as fh:
                return list(csv.DictReader(fh))
        except OSError:
            return []

    def _write(self, rows):
        tmp = self.path + ".tmp"
        with open(tmp, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, self.path)

    # -- new signals ----------------------------------------------------

    def signal_row(self, now, source, item, coins, passed, bought, fetched_at):
        """One row for a listing signal. `coins` are CoinGecko's matches (none,
        one, or several); only a single clear match has a price to follow."""
        coin = coins[0] if len(coins) == 1 else None
        published = item.get("published")
        market_list = source.get("format") == "markets"
        if market_list:
            # The coin appeared in the exchange's public market list: that is
            # when WE first saw it, so the real announcement time is unknown.
            announced, basis, delay = "", "not known (first seen in the exchange's market list)", ""
        elif published:
            announced = _naive(published).strftime(TIME)
            basis = "exchange"
            delay = str(int(round((_naive(now) - _naive(published)).total_seconds())))
        else:
            announced, basis, delay = "", "not given by the source", ""
        note = ""
        if not coins:
            note = "no coin matched, so no price"
        elif coin is None:
            note = "several coins matched: " + ";".join(x["id"] for x in coins[:5])
        price = coin.get("price") if coin else None
        verdict = "" if not coins else ("PASS" if passed else "FAIL")
        return {
            "detected_utc": _naive(now).strftime(TIME), "source": source["name"],
            "announced_utc": announced, "announced_basis": basis, "delay_seconds": delay,
            "title": item["title"][:200], "coin_id": coin["id"] if coin else "",
            "symbol": coin["symbol"] if coin else "", "verdict": verdict,
            "bought": "" if not coins else ("yes" if bought else "no"), "note": note,
            "price_at_detection": f"{price:.10g}" if price else "",
            "price_time_utc": (_naive(fetched_at or now).strftime(TIME) if price else ""),
        }

    def add(self, new_rows):
        """Append rows not already in the file (same time, source and title)."""
        if not new_rows:
            return
        rows = self.rows()
        have = {(r["detected_utc"], r["source"], r["title"], r["coin_id"]) for r in rows}
        rows += [r for r in new_rows
                 if (r["detected_utc"], r["source"], r["title"], r["coin_id"]) not in have]
        self._write(rows)

    # -- the later prices -----------------------------------------------

    def due(self, now):
        """{coin id: [(row index, checkpoint name)]} for every checkpoint that is
        due now: blank, past its time and not past its grace time."""
        now, out = _naive(now), {}
        for i, row in enumerate(self.rows()):
            if not row.get("coin_id") or not row.get("price_at_detection"):
                continue
            start = _parse(row["detected_utc"])
            for name, minutes, grace in CHECKPOINTS:
                if row.get(f"price_{name}"):
                    continue
                due = start + timedelta(minutes=minutes)
                if due <= now <= due + timedelta(seconds=grace):
                    out.setdefault(row["coin_id"], []).append((i, name))
        return out

    def fill(self, due, prices, fetched_at):
        """Save the prices (and when each was fetched: {coin id: time}) for the
        due checkpoints. A coin with no price stays blank for now, and is
        tried again until its grace time ends."""
        rows, changed = self.rows(), False
        for coin, checkpoints in due.items():
            price = prices.get(coin)
            if not price:
                continue
            stamp = _naive(fetched_at[coin]).strftime(TIME)
            for i, name in checkpoints:
                rows[i][f"price_{name}"] = f"{price:.10g}"
                rows[i][f"time_{name}"] = stamp
                changed = True
        if changed:
            self._write(rows)
        return changed
