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
    out = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, newline="") as fh:
                out += list(csv.DictReader(fh))
        except OSError:
            pass
    return out


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
    """The report's lines."""
    now = now or datetime.now(timezone.utc)
    days = days if days is not None else c.get("report_days", 7)
    window = timedelta(minutes=c.get("report_window_minutes", 10))
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    folder = os.path.join(data_root, c.get("folder", "xposts"))
    posts = [p for p in _rows(os.path.join(folder, "posts-*.csv"))
             if (p.get("posted_utc") or "")[:10] >= cutoff]
    all_launches = [r for r in _rows(os.path.join(data_root, "viral", "launches-*.csv"))
                    if (r.get("created_utc") or "")[:10] >= cutoff]
    priced = {r["token_address"]: r for r in _rows(os.path.join(data_root, "launch-record",
                                                                "launches-*.csv"))
              if (r.get("created_at_utc") or "")[:10] >= cutoff}
    launches = []
    for r in all_launches:
        when = _when(r.get("created_utc"))
        if when:
            launches.append((when, r))
    launches.sort(key=lambda x: x[0])
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
    if not posts:
        return lines + ["No posts saved yet."]
    total = 0
    for p in sorted(posts, key=lambda p: (p.get("posted_utc", ""), p.get("post_id", ""))):
        posted = _when(p.get("posted_utc")) or _when(p.get("seen_utc"))
        if posted is None:
            continue
        wanted = post_words(p.get("text"), c.get("min_word_letters", 3))
        found = []
        for when, r in launches:
            if when < posted:
                continue
            if when > posted + window:
                break
            hit = matches(r.get("symbol"), r.get("name"), wanted)
            if hit:
                found.append((when, r, hit))
        text = " ".join((p.get("text") or "").split())[:140].replace("|", "/")
        lines.append(f"## @{p.get('account')} {posted:%Y-%m-%d %H:%M:%S} UTC (post {p.get('post_id')})")
        lines.append(f"> {text}")
        lines.append("")
        if not found:
            lines += ["No matching launch in the next "
                      f"{window.total_seconds() / 60:g} minutes.", ""]
            continue
        total += len(found)
        lines += ["| Launched after | Symbol | Name | Matched | " +
                  " | ".join(label for label, _ in CHECKPOINTS) + " | Peak (after) |",
                  "|---|---|---|---|" + "---|" * len(CHECKPOINTS) + "---|"]
        for when, r, hit in found:
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
            lines.append(f"| {after} | {r.get('symbol', '')[:16]} | {name} | "
                         f"{', '.join(sorted(hit))} | " + " | ".join(moves) + f" | {peak} |")
        lines.append("")
    lines.insert(4, f"{len(posts)} post(s), {total} matching launch(es).")
    lines.insert(5, "")
    return lines


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
