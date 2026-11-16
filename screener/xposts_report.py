"""MEASUREMENT ONLY: for each saved X post (data/xposts/posts-*.csv), the new pump.fun launches
in the window_minutes (10) after it whose name or symbol matches a word of the post, and how
fast their price moved. Writes data/xposts/report.md. Nothing here trades or decides anything.

    python -m screener.xposts_report          <- write the report now

Launches come from two files the launch recorder already writes:
  data/viral/launches-*.csv          every launch (name and symbol, no prices)
  data/launch-record/launches-*.csv  the launches it followed, with prices 5 s .. 1 h after the
                                     launch (the qualified launches and a 2% sample only)
A matching launch that is only in the first file is listed with "price not recorded".

A word matches when it has at least min_word_letters (3) letters or digits, is not a common
word (STOPWORDS), and equals the launch's normalized symbol, or (with 4 letters or more)
one of the words of its name.
"""

import bisect
import csv
import glob
import os
from datetime import datetime, timedelta, timezone

from screener.viral import symbol_key, words

STOPWORDS = {
    "the", "and", "for", "you", "are", "but", "not", "all", "any", "can", "had", "her", "was",
    "one", "our", "out", "has", "his", "how", "its", "may", "new", "now", "old", "see", "two",
    "who", "did", "get", "got", "let", "say", "she", "too", "use", "way", "yes", "this", "that",
    "with", "have", "from", "they", "will", "would", "there", "their", "what", "about", "which",
    "when", "make", "like", "time", "just", "know", "take", "into", "year", "your", "good",
    "some", "could", "them", "than", "then", "look", "only", "come", "over", "think", "also",
    "back", "after", "work", "first", "well", "even", "want", "because", "these", "give",
    "most", "very", "much", "more", "here", "really", "people", "great", "today", "https",
    "http", "www", "com", "amp", "coin", "token", "crypto", "pump", "fun", "sol", "solana",
}
CHECKPOINTS = (("1 min", "price_sol_60s"), ("5 min", "price_sol_300s"),
               ("15 min", "price_sol_900s"), ("1 h", "price_sol_3600s"))


def _when(text):
    try:
        when = datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _rows(pattern):
    """All rows of the files matching `pattern` (only for the small posts files)."""
    out = []
    for path in sorted(glob.glob(pattern)):
        out += list(_stream(path))
    return out


def _stream(path, columns=None):
    """The rows of one CSV file, one at a time (a missing file has none). With `columns`, each
    row keeps only those: a day of launch-record rows is several MB, and whole days held as
    dictionaries took hundreds of MB."""
    try:
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                yield {k: row.get(k) for k in columns} if columns else row
    except OSError:
        return


def _num(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def post_words(text, min_letters=3):
    """The words of a post that can match a launch (no links, no common words)."""
    kept = set()
    for raw in (text or "").split():
        if raw.lower().startswith(("http://", "https://")):
            continue
        for w in words(raw):
            if len(w) >= min_letters and w not in STOPWORDS and not w.isdigit():
                kept.add(w)
    return kept


def matches(launch_symbol, launch_name, wanted):
    """The post words this launch matches (empty: none)."""
    hit = set()
    key = symbol_key(launch_symbol)
    if key in wanted:
        hit.add(key)
    hit |= {w for w in words(launch_name) if len(w) >= 4 and w in wanted}
    return hit


def build(data_root, c, now=None, days=None):
    """The report's lines. Memory stays small: the posts are read first (nothing else is read
    when there are none), then only the launch files of the days the posts' windows touch, one
    row at a time, keeping only the launches that match a post and only the columns used."""
    now = now or datetime.now(timezone.utc)
    days = days if days is not None else c.get("report_days", 7)
    window = timedelta(minutes=c.get("report_window_minutes", 10))
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    folder = os.path.join(data_root, c.get("folder", "xposts"))
    lines = [
        "# X posts and the pump.fun launches after them",
        "",
        f"Measurement only (screener/xposts_report.py), written {now:%Y-%m-%d %H:%M} UTC, "
        f"the last {days} days. For each post, the new launches in the "
        f"{window.total_seconds() / 60:g} minutes after it whose name or symbol matches a word "
        "of the post. Price moves are from the first recorded price (5 s after the launch) and "
        "exist only for the launches the launch recorder followed (qualified launches and a 2% "
        "sample); a match is not a cause.",
        "",
    ]
    posts = []
    for p in _rows(os.path.join(folder, "posts-*.csv")):
        if (p.get("posted_utc") or "")[:10] < cutoff:
            continue
        posted = _when(p.get("posted_utc")) or _when(p.get("seen_utc"))
        if posted is not None:
            posts.append((posted, p, post_words(p.get("text"), c.get("min_word_letters", 3))))
    if not posts:
        return lines + ["No posts saved yet."]
    posts.sort(key=lambda x: (x[1].get("posted_utc", ""), x[1].get("post_id", "")))
    starts = sorted(range(len(posts)), key=lambda i: posts[i][0])
    times = [posts[i][0] for i in starts]

    # the days whose launches can fall in a post's window
    wanted_days = set()
    for posted, _, _ in posts:
        wanted_days.add(posted.strftime("%Y-%m-%d"))
        wanted_days.add((posted + window).strftime("%Y-%m-%d"))
    found = {i: [] for i in range(len(posts))}
    for day in sorted(wanted_days):
        path = os.path.join(data_root, "viral", f"launches-{day}.csv")
        for r in _stream(path, ("created_utc", "token_address", "symbol", "name")):
            when = _when(r.get("created_utc"))
            if when is None:
                continue
            # the posts made at most one window before this launch (and not after it)
            lo = bisect.bisect_left(times, when - window)
            hi = bisect.bisect_right(times, when)
            for i in starts[lo:hi]:
                hit = matches(r.get("symbol"), r.get("name"), posts[i][2])
                if hit:
                    found[i].append((when, r, hit))
    needed = {r["token_address"] for hits in found.values() for _, r, _ in hits}
    priced = {}
    if needed:
        price_days = set()
        for hits in found.values():
            for when, _, _ in hits:
                price_days.add(when.strftime("%Y-%m-%d"))
                price_days.add((when + timedelta(days=1)).strftime("%Y-%m-%d"))
        keep = ("token_address", "peak_price_sol", "seconds_to_peak", "price_sol_5s",
                *(col for _, col in CHECKPOINTS))
        for day in sorted(price_days):
            path = os.path.join(data_root, "launch-record", f"launches-{day}.csv")
            for r in _stream(path, keep):
                if r.get("token_address") in needed:
                    priced[r["token_address"]] = r
    # the viral recorder's post_match flags of these posts (DexScreener's price and liquidity
    # at 1, 5, 15 and 60 minutes), from its flags files of the same days
    ids = {p.get("post_id") for _, p, _ in posts}
    flagged = {}
    flag_days = set(wanted_days) | {(datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1))
                                    .strftime("%Y-%m-%d") for d in wanted_days}
    flag_cols = ("by_post_match", "post_id", "symbol", "name", "matched_word", "created_utc",
                 "max_liquidity_usd", "reached_liquidity_utc",
                 *(f"{k}_{m}m{u}" for m in FLAG_MINUTES
                   for k, u in (("price", "_usd"), ("liquidity", "_usd"), ("at", "_utc"))))
    for day in sorted(flag_days):
        path = os.path.join(data_root, "viral", f"flags-{day}.csv")
        for r in _stream(path, flag_cols):
            if r.get("by_post_match") == "yes" and r.get("post_id") in ids:
                flagged.setdefault(r["post_id"], []).append(r)
    total = 0
    for i, (posted, p, _) in enumerate(posts):
        hits = sorted(found[i], key=lambda x: x[0])
        text = " ".join((p.get("text") or "").split())[:140].replace("|", "/")
        lines.append(f"## @{p.get('account')} {posted:%Y-%m-%d %H:%M:%S} UTC (post {p.get('post_id')})")
        lines.append(f"> {text}")
        lines.append("")
        lines += _flag_lines(flagged.get(p.get("post_id")) or [])
        if not hits:
            lines += ["No matching launch in the next "
                      f"{window.total_seconds() / 60:g} minutes.", ""]
            continue
        total += len(hits)
        lines += ["| Launched after | Symbol | Name | Matched | " +
                  " | ".join(label for label, _ in CHECKPOINTS) + " | Peak (after) |",
                  "|---|---|---|---|" + "---|" * len(CHECKPOINTS) + "---|"]
        for when, r, hit in hits:
            rec = priced.get(r.get("token_address"))
            after = f"{(when - posted).total_seconds():.0f} s"
            if rec is None or not _num(rec.get("price_sol_5s")):
                moves = ["price not recorded"] + [""] * (len(CHECKPOINTS) - 1)
                peak = ""
            else:
                base = _num(rec["price_sol_5s"])
                moves = []
                for _, col in CHECKPOINTS:
                    v = _num(rec.get(col))
                    moves.append(f"{(v / base - 1) * 100:+.0f}%" if v else "–")
                top = _num(rec.get("peak_price_sol"))
                peak = (f"{(top / base - 1) * 100:+.0f}% ({rec.get('seconds_to_peak') or '?'} s)"
                        if top else "–")
            name = (r.get("name") or "").replace("|", "/")[:40]
            lines.append(f"| {after} | {(r.get('symbol') or '')[:16]} | {name} | "
                         f"{', '.join(sorted(hit))} | " + " | ".join(moves) + f" | {peak} |")
        lines.append("")
    lines.insert(4, f"{len(posts)} post(s), {total} matching launch(es).")
    lines.insert(5, "")
    return lines


FLAG_MINUTES = (1, 5, 15, 60)


def _flag_lines(rows):
    """The post_match flags of one post: DexScreener's price (change from the first value read)
    and liquidity at each checkpoint, with the minutes after the launch it was really read."""
    if not rows:
        return []
    out = ["post_match flags (DexScreener, recording only):", "",
           "| Symbol | Matched | " + " | ".join(f"{m} min" for m in FLAG_MINUTES)
           + " | Highest liquidity | Reached $50,000 |",
           "|---|---|" + "---|" * len(FLAG_MINUTES) + "---|---|"]
    for r in sorted(rows, key=lambda r: r.get("created_utc") or ""):
        created = _when(r.get("created_utc"))
        base, cells = None, []
        for m in FLAG_MINUTES:
            at = r.get(f"at_{m}m_utc") or ""
            price, liq = _num(r.get(f"price_{m}m_usd")), _num(r.get(f"liquidity_{m}m_usd"))
            if at == "missed":
                cells.append("missed")
                continue
            if not at or price is None:
                cells.append("–")
                continue
            base = base or price
            when = _when(at)
            late = f" @{(when - created).total_seconds() / 60:.1f}m" if when and created else ""
            cells.append(f"{(price / base - 1) * 100:+.0f}%, "
                         + (f"liq ${liq:,.0f}" if liq is not None else "no liq") + late)
        top = _num(r.get("max_liquidity_usd"))
        out.append(f"| {(r.get('symbol') or '')[:16].replace('|', '/')} | "
                   f"{r.get('matched_word') or ''} | " + " | ".join(cells)
                   + f" | {'$' + format(top, ',.0f') if top is not None else '–'} | "
                   + ("yes" if r.get("reached_liquidity_utc") else "no") + " |")
    return out + [""]


def write_report(data_root, c, now=None):
    lines = build(data_root, c, now)
    path = os.path.join(data_root, c.get("folder", "xposts"), "report.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)
    return path


def main():
    from screener.settings import HERE, load_config
    cfg = load_config()
    print(write_report(os.path.join(HERE, cfg["files"]["data_folder"]), cfg["xposts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
