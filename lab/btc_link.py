"""Which coins follow Bitcoin least: a one-off MEASUREMENT, not a trading rule. It changes no bot,
strategy, setting or paper version and is not counted as a lab idea (lab/results/history.csv is
not touched). It writes lab/results/btc_link.csv and lab/results/btc_link.md.

    python lab/btc_link.py                 <- refresh (about 10 minutes; reads Binance's public
                                              daily files)
    python lab/btc_link.py --days 365 --top 100

Data: Binance spot daily candles from data.binance.vision (Binance's public daily and monthly
files; data-api.binance.vision is tried first and used where it answers). The coins: the top
--top Binance spot USDT pairs by the last full UTC day's quote volume (the daily files have no
live 24-hour ticker), plus EXTRA when listed; no stablecoins (by name, or a price that never
leaves $0.98-1.02), fiat, leveraged tokens, wrapped Bitcoin or tokenized stocks and funds. A pair
counts as listed when it has a daily file for the last full day.

Per coin, against BTC (daily close-to-close returns on the days both have):
  corr_1y, corr_90d      correlation of daily returns (0: on its own, 1: with BTC)
  beta_1y, beta_90d      the coin's average daily move for each 1% BTC move
  btc_down_days ...      on days BTC fell more than 3%: days the coin rose, its average move
  btc_up_days ...        on days BTC rose more than 3%: the same
  total_change_pct, max_drawdown_pct   over the period
  days, avg_daily_volume_usdt          (base volume x close)
Coins with less than MIN_FULL_DAYS (120) days: the 1-year figures (everything but the 90-day
ones, the days and the volume) are left blank.
"""

import argparse
import csv
import io
import math
import os
import re
import statistics
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

RESULTS = os.path.join(HERE, "lab", "results")
LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DAILY_FILE = ("https://data.binance.vision/data/spot/daily/klines/{symbol}/1d/"
              "{symbol}-1d-{day}.zip")
EXTRA = ["DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "PENGU", "TRUMP", "BOME", "NEIRO",
         "PNUT", "MEME", "TURBO", "QNT", "HBAR", "KAVA", "ARB", "ZRO", "KAITO", "JUP", "ICP",
         "TON", "TRX", "XLM", "NEAR", "ATOM", "ONDO", "PAXG"]
# Stablecoins and fiat (never measured).
STABLE = {"U", "RWUSD", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USDE", "USD1", "PYUSD", "USDS",
          "RLUSD", "FRAX", "LUSD", "GUSD", "USDD", "XUSD", "BFUSD", "USDB", "AEUR", "EUR", "EURI",
          "GBP", "AUD", "BRL", "TRY", "SUSD", "UST", "USTC", "USDJ", "PAX", "EURC", "EUROC"}
# Binance's leveraged tokens: a coin's name followed by UP, DOWN, BULL or BEAR (BTCUP, ETHDOWN).
# Not every name ending in UP: JUP and SYRUP are coins.
LEVERAGED_OF = {"BTC", "ETH", "BNB", "XRP", "ADA", "DOT", "LINK", "TRX", "EOS", "XTZ", "LTC",
                "FIL", "SXP", "YFI", "SUSHI", "AAVE", "UNI", "1INCH", "XLM", "BCH"}
LEVERAGED = re.compile(r"^(" + "|".join(sorted(LEVERAGED_OF, key=len, reverse=True))
                       + r")(UP|DOWN|BULL|BEAR)$")
# Binance's tokenized stocks and stock funds (not crypto coins; several are 3x leveraged funds),
# and wrapped Bitcoin (Bitcoin itself). Left out and named in the summary. A new tokenized stock
# must be added here by hand.
TOKENIZED = {"AVGOB", "BNCB", "CRCLB", "DRAMB", "GOOGLB", "INTCB", "KORUB", "MSTRB", "MUB",
             "NBISB", "NVDAB", "QQQB", "SKHYB", "SNDKB", "SNXXB", "SOXLB", "SOXSB", "SPCXB",
             "SPYB", "TQQQB", "TSLAB", "BMNRB", "AMDB", "COINB", "MRVLB", "INTWB"}
WRAPPED_BTC = {"WBTC", "BTCB"}
# A coin whose daily close never leaves this band around $1 is a dollar stablecoin (left out,
# whatever its name: U and RWUSD were not in the list above).
PEG_BAND = (0.98, 1.02)
# Memecoins, from a fixed list (marked in the results; a memecoin missing here is not marked).
MEMECOINS = {"DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "PENGU", "TRUMP", "BOME", "NEIRO",
             "PNUT", "MEME", "TURBO", "1000SATS", "1MBABYDOGE", "PEOPLE", "DOGS", "ACT",
             "1000CHEEMS", "1000CAT", "BROCCOLI714", "MUBARAK", "TUT", "NOT", "HIPPO", "MOODENG",
             "POPCAT", "SPX", "FARTCOIN", "GOAT", "PUMP", "BANANAS31", "WLFI", "PNUTS", "CHEEMS",
             "牛来"}
MIN_FULL_DAYS = 120
RECENT_DAYS = 90
BIG_MOVE_PCT = 3.0
COLUMNS = ["rank", "coin", "symbol", "memecoin", "days", "first_day", "last_day",
           "avg_daily_volume_usdt", "corr_1y", "corr_90d", "beta_1y", "beta_90d",
           "btc_down_days", "coin_rose_on_btc_down_days", "avg_move_on_btc_down_days_pct",
           "btc_up_days", "coin_rose_on_btc_up_days", "avg_move_on_btc_up_days_pct",
           "total_change_pct", "max_drawdown_pct", "short_history"]


# ---------------------------------------------------------------------
# the coins
# ---------------------------------------------------------------------

def base_of(symbol):
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def wanted(base):
    """False for stablecoins, fiat, leveraged tokens, tokenized stocks and funds, and BTC
    itself (wrapped included)."""
    return (base not in STABLE and base != "BTC" and base not in WRAPPED_BTC
            and base not in TOKENIZED and not LEVERAGED.match(base))


def pegged(closes):
    """True for a dollar stablecoin: every close inside PEG_BAND."""
    return bool(closes) and all(PEG_BAND[0] <= c <= PEG_BAND[1] for c in closes.values())


def choose(volumes, top, extra=EXTRA):
    """The coins to measure: the `top` largest quote volumes (base -> volume), then `extra`
    when listed (in `volumes`). Never stablecoins, fiat, leveraged tokens or BTC."""
    ranked = sorted((b for b in volumes if wanted(b)), key=lambda b: -volumes[b])
    chosen = ranked[:top]
    chosen += [b for b in extra if b in volumes and wanted(b) and b not in chosen]
    return chosen


# ---------------------------------------------------------------------
# the numbers
# ---------------------------------------------------------------------

def returns(closes):
    """{day: daily return} from {day: close}, for each day whose day before has a close."""
    days = sorted(closes)
    out = {}
    for prev, day in zip(days, days[1:]):
        if (date.fromisoformat(day) - date.fromisoformat(prev)).days == 1 and closes[prev] > 0:
            out[day] = closes[day] / closes[prev] - 1
    return out


def corr_beta(xs, ys):
    """(correlation, beta of ys on xs); None when it can't be measured."""
    if len(xs) < 20:
        return None, None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None, None
    return cov / math.sqrt(vx * vy), cov / vx


def max_drawdown(closes):
    peak, worst = None, 0.0
    for day in sorted(closes):
        c = closes[day]
        peak = c if peak is None else max(peak, c)
        worst = min(worst, c / peak - 1)
    return worst


def measure(coin_closes, btc_closes, recent=RECENT_DAYS, big=BIG_MOVE_PCT,
            min_full=MIN_FULL_DAYS):
    """Every number for one coin (see the module text). Values are None when not measurable."""
    cr, br = returns(coin_closes), returns(btc_closes)
    both = sorted(d for d in cr if d in br)
    days = len(coin_closes)
    out = {"days": days, "first_day": min(coin_closes) if coin_closes else None,
           "last_day": max(coin_closes) if coin_closes else None,
           "short_history": days < min_full}
    last = both[-recent:]
    out["corr_90d"], out["beta_90d"] = corr_beta([br[d] for d in last], [cr[d] for d in last])
    full = {k: None for k in ("corr_1y", "beta_1y", "btc_down_days", "coin_rose_on_btc_down_days",
                              "avg_move_on_btc_down_days_pct", "btc_up_days",
                              "coin_rose_on_btc_up_days", "avg_move_on_btc_up_days_pct",
                              "total_change_pct", "max_drawdown_pct")}
    if not out["short_history"]:
        full["corr_1y"], full["beta_1y"] = corr_beta([br[d] for d in both], [cr[d] for d in both])
        for side, test in (("down", lambda r: r < -big / 100), ("up", lambda r: r > big / 100)):
            moves = [cr[d] for d in both if test(br[d])]
            full[f"btc_{side}_days"] = len(moves)
            full[f"coin_rose_on_btc_{side}_days"] = sum(1 for m in moves if m > 0)
            full[f"avg_move_on_btc_{side}_days_pct"] = (statistics.fmean(moves) * 100
                                                         if moves else None)
        days_sorted = sorted(coin_closes)
        first, final = coin_closes[days_sorted[0]], coin_closes[days_sorted[-1]]
        full["total_change_pct"] = (final / first - 1) * 100 if first > 0 else None
        full["max_drawdown_pct"] = max_drawdown(coin_closes) * 100
    out.update(full)
    return out


# ---------------------------------------------------------------------
# the files
# ---------------------------------------------------------------------

def _fmt(v, digits=3):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def write_csv(rows, path):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in COLUMNS])


def _pct(v, digits=1):
    return "–" if v is None else f"{v:+.{digits}f}%"


def _num(v, digits=2):
    return "–" if v is None else f"{v:.{digits}f}"


def summary_lines(rows, first, last, btc):
    """The plain-English summary: the 10 least BTC-linked coins (90-day correlation) and how
    each behaved on BTC's worst days."""
    ordered = sorted((r for r in rows if r.get("corr_90d") is not None),
                     key=lambda r: r["corr_90d"])
    ten = ordered[:10]
    lines = [
        "# Which coins follow Bitcoin least",
        "",
        f"A measurement only, not a trading rule (`lab/btc_link.py`). Daily closes from "
        f"{first} to {last} UTC (Binance spot USDT pairs); {len(rows)} coins. A correlation of "
        "0 means a coin moved on its own, 1 that it moved with Bitcoin; beta is its average move "
        "for each 1% Bitcoin move.",
        "",
        f"Bitcoin itself: {_pct(btc.get('total_change_pct'))} over the period, biggest fall from "
        f"a peak {_pct(btc.get('max_drawdown_pct'))}; it fell more than {BIG_MOVE_PCT:g}% on "
        f"{btc.get('down_days', 0)} days and rose more than {BIG_MOVE_PCT:g}% on "
        f"{btc.get('up_days', 0)} days.",
        "",
        "**The 10 least Bitcoin-linked coins (last 90 days):**",
        "",
    ]
    for i, r in enumerate(ten, 1):
        meme = " (memecoin)" if r["memecoin"] else ""
        if r.get("btc_down_days"):
            worst = (f"on Bitcoin's {r['btc_down_days']} days down more than {BIG_MOVE_PCT:g}% it "
                     f"rose on {r['coin_rose_on_btc_down_days']} and moved "
                     f"{_pct(r['avg_move_on_btc_down_days_pct'])} on average")
        elif r["short_history"]:
            worst = f"only {r['days']} days of history, too short for the 1-year figures"
        else:
            worst = "no Bitcoin day down more than 3% in its history"
        lines.append(f"{i}. **{r['coin']}**{meme}: 90-day correlation {_num(r['corr_90d'])}, "
                     f"1-year {_num(r.get('corr_1y'))}; {worst}.")
    lines += [
        "",
        "**Left out:** stablecoins and fiat (" + ", ".join(sorted(STABLE)[:8]) + " and others"
        + (f"; by their price staying at $1: {', '.join(btc['left_out_pegged'])}"
           if btc.get("left_out_pegged") else "")
        + "), leveraged tokens, wrapped Bitcoin (" + ", ".join(sorted(WRAPPED_BTC)) + "), and "
        f"Binance's tokenized stocks and stock funds ({', '.join(sorted(TOKENIZED))}): they "
        "follow the stock market, not crypto, and several are 3x leveraged funds.",
        "",
        "**Read with care.** Only coins still listed today are measured: coins that died or were "
        "delisted are missing (survivorship bias), so the results look better than reality. A "
        "low correlation is not a hedge: a coin can fall on its own, and many of these fell far "
        "from their peaks. Correlations move over time; 90 days is a small sample. Volume is "
        "base volume x close.",
        "",
    ]
    return lines


def write_md(rows, path, first, last, btc):
    lines = summary_lines(rows, first, last, btc)
    lines += ["| # | Coin | Meme | Days | Corr 90d | Corr 1y | Beta 1y | BTC down >3%: coin rose "
              "(avg) | BTC up >3%: coin rose (avg) | Total | Max fall | Avg volume/day |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    ordered = sorted(rows, key=lambda r: (r.get("corr_90d") is None,
                                          r.get("corr_90d") if r.get("corr_90d") is not None
                                          else 0))
    for i, r in enumerate(ordered, 1):
        down = (f"{r['coin_rose_on_btc_down_days']}/{r['btc_down_days']} "
                f"({_pct(r['avg_move_on_btc_down_days_pct'])})"
                if r.get("btc_down_days") is not None else "–")
        up = (f"{r['coin_rose_on_btc_up_days']}/{r['btc_up_days']} "
              f"({_pct(r['avg_move_on_btc_up_days_pct'])})"
              if r.get("btc_up_days") is not None else "–")
        days = f"{r['days']}" + (" (short)" if r["short_history"] else "")
        vol = r.get("avg_daily_volume_usdt")
        lines.append(f"| {i} | {r['coin']} | {'yes' if r['memecoin'] else ''} | {days} | "
                     f"{_num(r.get('corr_90d'))} | {_num(r.get('corr_1y'))} | "
                     f"{_num(r.get('beta_1y'))} | {down} | {up} | "
                     f"{_pct(r.get('total_change_pct'), 0)} | {_pct(r.get('max_drawdown_pct'), 0)} | "
                     + (f"${vol / 1e6:,.1f}M" if vol else "–") + " |")
    lines += ["", f"Refresh: `python lab/btc_link.py` (writes lab/results/btc_link.csv and this "
              "file)."]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def build(series, volumes_usdt, first, last, out_dir=RESULTS):
    """series: {base: {day: close}} including "BTC"; volumes_usdt: {base: average daily volume}.
    Writes the two files and returns the rows."""
    btc = series["BTC"]
    rows, pegs = [], []
    for base, closes in series.items():
        if base == "BTC" or not closes:
            continue
        if pegged(closes):
            pegs.append(base)
            continue
        r = measure(closes, btc)
        r.update(coin=base, symbol=f"{base}USDT", memecoin=base in MEMECOINS,
                 avg_daily_volume_usdt=volumes_usdt.get(base))
        rows.append(r)
    ordered = sorted(rows, key=lambda r: (r["corr_90d"] is None, r["corr_90d"] or 0))
    for i, r in enumerate(ordered, 1):
        r["rank"] = i
    br = returns(btc)
    btc_info = {"total_change_pct": (btc[max(btc)] / btc[min(btc)] - 1) * 100,
                "max_drawdown_pct": max_drawdown(btc) * 100,
                "down_days": sum(1 for v in br.values() if v < -BIG_MOVE_PCT / 100),
                "up_days": sum(1 for v in br.values() if v > BIG_MOVE_PCT / 100)}
    os.makedirs(out_dir, exist_ok=True)
    write_csv(ordered, os.path.join(out_dir, "btc_link.csv"))
    btc_info["left_out_pegged"] = sorted(pegs)
    write_md(ordered, os.path.join(out_dir, "btc_link.md"), first, last, btc_info)
    return ordered


# ---------------------------------------------------------------------
# Binance's public files (only for a real refresh; the tests use fake data)
# ---------------------------------------------------------------------

def list_usdt_symbols(http):
    """Every symbol with a folder of daily candle files that ends in USDT (listed or not)."""
    import xml.etree.ElementTree as ET
    symbols, marker = set(), ""
    while True:
        resp = http.get(LISTING, params={"delimiter": "/", "prefix": "data/spot/daily/klines/",
                                         "marker": marker}, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"s": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
        q = (lambda tag: f"s:{tag}") if ns else (lambda tag: tag)
        prefixes = [p.text for p in root.iter(f"{{{ns['s']}}}Prefix" if ns else "Prefix")
                    if p.text and p.text.count("/") == 5]
        for p in prefixes:
            sym = p.rstrip("/").rsplit("/", 1)[-1]
            if sym.endswith("USDT"):
                symbols.add(sym)
        truncated = root.find(q("IsTruncated"), ns)
        nxt = root.find(q("NextMarker"), ns)
        if truncated is None or truncated.text != "true":
            break
        marker = nxt.text if nxt is not None else prefixes[-1]
    return symbols


def day_volume(http, symbol, day, tries=3, sleep=None):
    """The quote volume of one day's file, or None when there is no file (404: not listed). Any
    other failure is tried again (a pair is never left out because one download failed), then
    raised."""
    import time
    sleep = sleep or time.sleep
    for attempt in range(tries):
        try:
            resp = http.get(DAILY_FILE.format(symbol=symbol, day=day), timeout=30)
        except Exception:
            resp = None
        if resp is not None and resp.status_code == 404:
            return None
        if resp is not None and resp.status_code == 200:
            break
        if attempt == tries - 1:
            raise RuntimeError(f"{symbol} {day}: no answer after {tries} tries")
        sleep(2 * (attempt + 1))
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    rows = [r for r in csv.reader(io.StringIO(text)) if r and r[0].isdigit()]
    return float(rows[0][7]) if rows else None


def refresh(days=365, top=100, workers=8, out=print, cache=None):
    import requests
    from screener.trend import BinanceDaily, FetchError
    http = requests.Session()
    last = date.today() - timedelta(days=1)
    for _ in range(4):                     # the last day whose BTC file is published
        if day_volume(http, "BTCUSDT", last.isoformat()) is not None:
            break
        last -= timedelta(days=1)
    first = last - timedelta(days=days - 1)
    out(f"Period {first} .. {last}. Listing Binance's spot USDT pairs...")
    symbols = sorted(s for s in list_usdt_symbols(http) if wanted(base_of(s)))
    out(f"{len(symbols)} USDT symbols with daily files; reading {last}'s volume of each...")
    with ThreadPoolExecutor(workers) as pool:
        vols = dict(zip(symbols, pool.map(lambda s: day_volume(http, s, last.isoformat()),
                                          symbols)))
    listed = {base_of(s): v for s, v in vols.items() if v is not None}
    coins = choose(listed, top)
    not_listed = [b for b in EXTRA if b not in listed]
    maybe_stock = [b for b in coins if b.endswith("B") and b not in ("BNB", "SHIB", "ARB")]
    if maybe_stock:
        out("CHECK: these names end in B like Binance's tokenized stocks; if one is a stock or a "
            f"fund, add it to TOKENIZED and run again: {', '.join(maybe_stock)}")
    out(f"{len(listed)} listed on {last}; measuring {len(coins)} coins + BTC"
        + (f" (not listed on Binance spot now: {', '.join(not_listed)})" if not_listed else "")
        + "...")
    fetcher = BinanceDaily(http=http)

    def candles(base):
        path = os.path.join(cache, f"{base}-{first}-{last}.csv") if cache else None
        if path and os.path.exists(path):
            with open(path, newline="") as fh:
                return base, [(r[0], *map(float, r[1:])) for r in csv.reader(fh)], None
        try:
            rows, _, _ = fetcher.candles(f"{base}USDT", first, last)
        except FetchError as exc:
            out(f"  {base}: no candles ({exc})")
            return base, [], None
        if path:
            os.makedirs(cache, exist_ok=True)
            with open(path, "w", newline="") as fh:
                csv.writer(fh).writerows(rows)
        return base, rows, None
    with ThreadPoolExecutor(workers) as pool:
        got = list(pool.map(candles, ["BTC"] + coins))
    series = {b: {r[0]: r[4] for r in rows} for b, rows, _ in got}
    volumes = {b: statistics.fmean(r[5] * r[4] for r in rows) for b, rows, _ in got if rows}
    rows = build(series, volumes, first.isoformat(), last.isoformat())
    out(f"Wrote {os.path.join(RESULTS, 'btc_link.csv')} and btc_link.md ({len(rows)} coins).")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--cache", help="keep the downloaded candles in this folder and reuse "
                                        "them (for a quick second run)")
    args = parser.parse_args(argv)
    refresh(args.days, args.top, cache=args.cache)
    return 0


if __name__ == "__main__":
    sys.exit(main())
