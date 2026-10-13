"""A timing report: when tokens were launched, and what happened to them afterwards.

REPORT ONLY. It reads data/main-1min/candidates.csv and the paper journals and
writes data/main-1min/timing_report.md. It changes no bot, rule or setting, and
makes no request.

Buckets: each UTC hour (0-23), each weekday, four 6-hour blocks, all by the
token's CREATION time (its pool's creation, see token_record.launch_times).
Every number is shown with its sample size n ("42% (n=120)"); a bucket with
fewer than MIN_N tokens is marked "too few to judge", and a number with fewer
than MIN_N behind it carries a dagger. A missing value (no price, no
liquidity, no BTC reading) is left out of that number's n, never counted as 0.

How each measure is worked out:
  alive          asked at the checkpoint (1h / 6h / 24h) and DexScreener still has a
                 pair with liquidity at or above the config threshold. A token it no
                 longer has a pair for counts as not alive. A token whose liquidity is
                 blank (a pump.fun token still on its bonding curve has none) is left out.
  price change   checkpoint price / price at the first check - 1. A blank price is missing
                 (so a token that vanished is left out of the medians).
  up > 50%       any of the 1h / 6h / 24h prices at least 50% above the first price
                 (of the tokens with at least one price).
  passed         verdict PASS in candidates.csv (main's filter).
  graduated      DEX is not pump.fun's own bonding curve (of tokens whose DEX is known).
"""

import csv
import os
import statistics
from datetime import datetime, timezone

from screener.token_record import TIME, row_launch_times

MIN_N = 30
DAYS_NEEDED = 7
CHECKPOINTS = ("1h", "6h", "24h")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BLOCKS = ["00-05", "06-11", "12-17", "18-23"]
BTC_BINS = [("below -1%", lambda v: v < -1), ("-1% to +1%", lambda v: -1 <= v <= 1),
            ("above +1%", lambda v: v > 1)]
# strategy name -> journal path (relative to the data folder's parent)
STRATEGIES = [
    ("B", os.path.join("main-1min", "b", "journal.csv")),
    ("C", os.path.join("main-1min", "c", "journal.csv")),
    ("convergence", os.path.join("convergence", "journal.csv")),
    ("robinhood", os.path.join("robinhood", "journal.csv")),
    ("news (listings)", os.path.join("news-listings", "journal.csv")),
]


# ---------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------

def read_csv(path):
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def to_time(text):
    try:
        return datetime.strptime(text, TIME)
    except (TypeError, ValueError):
        return None


def prepare(row):
    """One candidates.csv row as numbers: launch times, the checkpoint changes
    and liquidity (None = missing)."""
    first = num(row.get("price_usd"))
    launch = row_launch_times(row)
    out = {"row": row, "hour": None, "weekday": None, "changes": {}, "alive": {}}
    if launch.get("created_hour_utc") not in (None, ""):
        out["hour"], out["weekday"] = int(launch["created_hour_utc"]), int(launch["created_weekday"])
    for cp in CHECKPOINTS:
        if not row.get(f"time_{cp}_utc"):
            continue                                   # not asked (yet)
        price = num(row.get(f"price_{cp}_usd"))
        if price is not None and first:
            out["changes"][cp] = (price / first - 1) * 100
        if price is None:
            out["alive"][cp] = False                   # asked, DexScreener has no pair
        else:
            out["alive"][cp] = None if row.get(f"liquidity_{cp}_usd") in (None, "") else \
                num(row.get(f"liquidity_{cp}_usd"))
    return out


# ---------------------------------------------------------------------
# measures
# ---------------------------------------------------------------------

def share(hits, n):
    return (hits / n * 100, n) if n else (None, 0)


def measures(tokens, min_liquidity):
    """{measure: (value, n)} for a list of prepared tokens (value None when n = 0)."""
    out = {"tokens": (len(tokens), len(tokens))}
    for cp in CHECKPOINTS:
        known = [t["alive"][cp] for t in tokens if t["alive"].get(cp) is not False
                 and t["alive"].get(cp) is not None]
        dead = sum(1 for t in tokens if t["alive"].get(cp) is False)
        out[f"alive_{cp}"] = share(sum(1 for liq in known if liq is not None and liq >= min_liquidity),
                                   len(known) + dead)
        changes = [t["changes"][cp] for t in tokens if cp in t["changes"]]
        out[f"median_{cp}"] = (statistics.median(changes), len(changes)) if changes else (None, 0)
    with_price = [t for t in tokens if t["changes"]]
    out["up50"] = share(sum(1 for t in with_price if any(c > 50 for c in t["changes"].values())),
                        len(with_price))
    verdicts = [t["row"].get("verdict") for t in tokens if t["row"].get("verdict")]
    out["passed"] = share(sum(1 for v in verdicts if v == "PASS"), len(verdicts))
    dexes = [t["row"].get("dex_id") for t in tokens if t["row"].get("dex_id")]
    out["graduated"] = share(sum(1 for d in dexes if d != "pumpfun"), len(dexes))
    return out


MEASURE_COLUMNS = [
    ("alive_1h", "alive 1h", "pct"), ("alive_6h", "alive 6h", "pct"), ("alive_24h", "alive 24h", "pct"),
    ("median_1h", "median 1h", "chg"), ("median_6h", "median 6h", "chg"),
    ("median_24h", "median 24h", "chg"),
    ("up50", "up >50% at any", "pct"), ("passed", "passed main filter", "pct"),
    ("graduated", "graduated", "pct"),
]


def fmt(value, n, kind):
    if value is None or not n:
        return f"– (n={n})"
    text = f"{value:.0f}%" if kind == "pct" else f"{value:+.1f}%"
    return f"{text} (n={n}){'†' if n < MIN_N else ''}"


def table(title_col, buckets, min_liquidity):
    """A markdown table; buckets = [(label, [prepared tokens])]."""
    head = [title_col, "tokens"] + [c[1] for c in MEASURE_COLUMNS] + ["note"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for label, tokens in buckets:
        m = measures(tokens, min_liquidity)
        cells = [fmt(*m[key], kind) for key, _, kind in MEASURE_COLUMNS]
        note = "too few to judge" if len(tokens) < MIN_N else ""
        lines.append("| " + " | ".join([str(label), f"n={len(tokens)}"] + cells + [note]) + " |")
    return "\n".join(lines)


def block_of(hour):
    return hour // 6


def split(tokens, key, labels):
    return [(labels[i], [t for t in tokens if key(t) == i]) for i in range(len(labels))]


# ---------------------------------------------------------------------
# paper buys
# ---------------------------------------------------------------------

def buys_by_hour(journal):
    """({hour: [buys, closed pnl_usd]}, unattributed sells) from a journal: each
    SELL's P&L (after costs) belongs to the hour of the BUY it closes."""
    per, last_buy, lost = {}, {}, 0
    for r in journal:
        when = to_time(r.get("time_utc"))
        if not when:
            continue
        token = r.get("token_address")
        if r.get("action") == "BUY":
            last_buy[token] = when.hour
            per.setdefault(when.hour, [0, 0.0])[0] += 1
        elif r.get("action") == "SELL":
            pnl = num(r.get("pnl_usd"))
            if pnl is None:
                continue
            if token in last_buy:
                per.setdefault(last_buy[token], [0, 0.0])[1] += pnl
            else:
                lost += 1
    return per, lost


def paper_tables(data_root):
    lines, lost_total = [], 0
    results = {}
    for name, rel in STRATEGIES:
        journal = read_csv(os.path.join(data_root, rel))
        results[name] = buys_by_hour(journal)
        lost_total += results[name][1]
    names = [n for n, _ in STRATEGIES]

    def cell(buys, pnl):
        if not buys:
            return "–"
        return f"{buys} buys, {pnl:+.2f}$ (n={buys}){'†' if buys < MIN_N else ''}"

    def build(label, groups):
        head = [label] + names
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for text, hours in groups:
            row = [text]
            for name in names:
                per = results[name][0]
                buys = sum(per.get(h, [0, 0.0])[0] for h in hours)
                pnl = sum(per.get(h, [0, 0.0])[1] for h in hours)
                row.append(cell(buys, pnl))
            out.append("| " + " | ".join(row) + " |")
        return "\n".join(out)

    lines.append("By 6-hour block of the buy (UTC):\n")
    lines.append(build("block", [(BLOCKS[i], range(i * 6, i * 6 + 6)) for i in range(4)]))
    lines.append("\nBy UTC hour of the buy:\n")
    lines.append(build("hour", [(f"{h:02d}", [h]) for h in range(24)]))
    total = {n: sum(v[0] for v in results[n][0].values()) for n in names}
    lines.append("\nBuys in each journal: " + ", ".join(f"{n} {total[n]}" for n in names) + ".")
    if lost_total:
        lines.append(f"{lost_total} sell(s) had no earlier buy in the journal and are not counted.")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------

HOW_TO_READ = (
    "These tables describe past data, nothing more. A good-looking hour or weekday is a lead "
    "to test on later days, not a rule: with only a few days of data a pattern is usually luck "
    "(look at every n, and at the buckets marked \"too few to judge\"). Nothing in this report "
    "changes the bot: no buy, sell, filter or setting reads it.")


def build_report(data_root, min_liquidity, folder="main-1min"):
    rows = read_csv(os.path.join(data_root, folder, "candidates.csv"))
    tokens = [prepare(r) for r in rows]
    times = sorted(t for t in (to_time(r.get("first_checked_utc")) for r in rows) if t)
    out = ["# Timing report (main, 1 minute)", ""]
    if times:
        days = (times[-1] - times[0]).total_seconds() / 86400
        out.append(f"Data: {len(rows)} candidate rows, first checks from {times[0]:%Y-%m-%d %H:%M} "
                   f"to {times[-1]:%Y-%m-%d %H:%M} UTC ({days:.1f} days).")
        if days < DAYS_NEEDED:
            out += ["", f"**Not enough data:** only {days:.1f} days of rows so far (at least "
                        f"{DAYS_NEEDED} days are needed before any pattern is worth a second look)."]
    else:
        out += ["No candidate rows yet.", "", f"**Not enough data:** 0 days of rows so far (at least "
                                             f"{DAYS_NEEDED} days are needed)."]
    out += ["", "## How to read this", "", HOW_TO_READ, ""]

    dated = [t for t in tokens if t["hour"] is not None]
    out += [f"Tokens are placed by the UTC time their pool was created. {len(rows) - len(dated)} of "
            f"{len(rows)} rows have no creation time and are left out of the hour, weekday and "
            f"block tables. \"Alive\" needs liquidity of at least ${min_liquidity:,.0f} "
            f"(config.toml [filters] min_liquidity_usd). A token DexScreener no longer has a pair for "
            f"has no price and is left out of the medians, so the medians describe tokens still "
            f"listed (and flatter the real picture). † = fewer than {MIN_N} behind that number.",
            "", "## By UTC hour of creation", "",
            table("hour", [(f"{h:02d}", [t for t in dated if t["hour"] == h]) for h in range(24)],
                  min_liquidity),
            "", "## By weekday of creation (UTC)", "",
            table("weekday", split(dated, lambda t: t["weekday"], WEEKDAYS), min_liquidity),
            "", "## By 6-hour block of creation (UTC)", "",
            table("block", split(dated, lambda t: block_of(t["hour"]), BLOCKS), min_liquidity),
            "", "## Backdrop", "",
            "The same measures, split by Bitcoin's price change at the moment we first checked "
            "the token (candidates.csv btc_change_1h_pct / btc_change_24h_pct, recorded since "
            "2026-10-13; older rows have none and are left out)."]
    for column, name in (("btc_change_1h_pct", "Bitcoin 1 h change"),
                         ("btc_change_24h_pct", "Bitcoin 24 h change")):
        have = [(num(t["row"].get(column)), t) for t in tokens]
        have = [(v, t) for v, t in have if v is not None]
        buckets = [(label, [t for v, t in have if test(v)]) for label, test in BTC_BINS]
        out += ["", f"### {name}", "",
                f"{len(have)} of {len(tokens)} rows have this reading.", "",
                table("BTC", buckets, min_liquidity)]
    out += ["", "## Our own paper buys", "",
            "Buys and profit/loss after costs (closed sells only; a position still open has no "
            "P&L yet), by the UTC time of the buy, per strategy. Each journal covers its own "
            "dates, so the strategies are not over the same period. † = fewer than "
            f"{MIN_N} buys.", "", paper_tables(data_root), ""]
    return "\n".join(out)


def main(data_root, min_liquidity, out_path=None):
    text = build_report(data_root, min_liquidity)
    out_path = out_path or os.path.join(data_root, "main-1min", "timing_report.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(text)
    return out_path
