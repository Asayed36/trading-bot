"""Ticker mentions in the X posts the watcher saves (xposts_bot.py). RECORDING ONLY: nothing here
buys, sells or changes any strategy, paper version or setting, and it makes no X request (it
only reads the posts the watcher already saved).

1. Find: in each new saved post (original posts only: the watcher never saves replies or
   reposts), its cashtags ($WIF, $PEPE: 2-10 letters or digits after the $, not starting with a
   digit, so "$10M" is a dollar amount, not a coin), Solana token addresses (base58, 32-44
   characters, with at least one digit) and EVM addresses (0x + 40 hex characters). At most
   max_per_post (5) per post, the rest are counted as dropped.
2. Identify, with ONE DexScreener lookup per mention (tried again only when it fails, for
   lookup_retry_minutes): a cashtag is the pair with the highest liquidity whose base token
   symbol is exactly the tag; "candidates" is how many different tokens had that symbol in
   DexScreener's search answer (DexScreener answers at most 30 pairs, so it is "at least"); an
   address is that token. "large": BTC, ETH, SOL, BNB, XRP, DOGE, or a market cap above $5
   billion at the first check.
3. Follow: price, liquidity, 24 h volume and market cap at the first check (the lookup, with
   its delay from the post's own time) and about 5, 15 and 60 minutes and 24 hours after the
   post, each at the first check at or after that time if it comes within post_match's
   tolerance (max(2 minutes, 20% of the time)), else "missed" (never recorded late); with the
   real time it was read. "1 h change at first check" is DexScreener's 1-hour price change at
   the first check: the hour before the check, not exactly the hour before the post
   (DexScreener keeps no price history). BTC's change over the same windows comes from the
   once-a-minute price log (data/market/prices-*.csv), and over the hour before the post exactly.

Files (data/xposts/): mentions-YYYY-MM-DD.csv (the UTC day the post was saved; rows are
rewritten while their checkpoints come in, for 24 hours) and mentions_health.json.

PAPER TRADING ONLY: read-only public GET requests, nothing signed or sent.
"""

import csv
import json
import logging
import os
import re
import statistics
import threading
from datetime import datetime, timedelta, timezone

log = logging.getLogger("xposts")

ISO = "%Y-%m-%dT%H:%M:%SZ"
CASHTAG = re.compile(r"(?<![A-Za-z0-9_$])\$([A-Za-z][A-Za-z0-9]{1,9})(?![A-Za-z0-9_])")
EVM = re.compile(r"(?<![0-9A-Za-z])0x[0-9a-fA-F]{40}(?![0-9A-Za-z])")
SOLANA = re.compile(r"(?<![0-9A-Za-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![0-9A-Za-z])")
LINK = re.compile(r"https?://\S+")
LARGE_SYMBOLS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE")
LARGE_MARKET_CAP_USD = 5e9
# (label, minutes after the post)
CHECKPOINTS = (("5m", 5), ("15m", 15), ("60m", 60), ("24h", 1440))
VALUES = ("price", "liquidity", "volume_24h", "market_cap")
COLUMNS = (["post_id", "account", "posted_utc", "seen_utc", "mention", "kind", "status", "chain",
            "token_address", "pair_address", "symbol", "name", "candidates", "large",
            "first_check_utc", "first_check_delay_seconds", "price_first_usd",
            "liquidity_first_usd", "volume_24h_first_usd", "market_cap_first_usd",
            "change_1h_at_first_check_pct", "btc_change_1h_before_post_pct",
            "btc_change_1h_before_first_check_pct"]
           + [c for label, _ in CHECKPOINTS for c in
              (f"at_{label}_utc", f"price_{label}_usd", f"liquidity_{label}_usd",
               f"volume_24h_{label}_usd", f"market_cap_{label}_usd", f"change_{label}_pct",
               f"btc_change_{label}_pct")])
FINAL = ("not found", "lookup failed")
COUNTS = ("posts_with_mentions", "mentions", "dropped_by_cap", "identified", "not_found",
          "lookup_failed", "requests", "errors")


def _utc(text):
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _iso(when):
    return when.astimezone(timezone.utc).strftime(ISO)


def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _cell(value, fmt="{:.10g}"):
    return "" if value is None else fmt.format(value)


def tolerance_seconds(minutes):
    """post_match's tolerance (screener/viral.py): max(2 minutes, 20% of the time)."""
    return max(120, minutes * 60 * 0.2)


# ---- 1. find --------------------------------------------------------------

def find_mentions(text, max_per_post=5):
    """([(kind, mention)], dropped) in the order they appear, each once. kind: "cashtag"
    (mention "$WIF", upper case), "solana" (the address as written), "evm" (lower case)."""
    text = LINK.sub(" ", text or "")
    found = []
    for m in CASHTAG.finditer(text):
        found.append((m.start(), "cashtag", "$" + m.group(1).upper()))
    for m in EVM.finditer(text):
        found.append((m.start(), "evm", m.group(0).lower()))
    for m in SOLANA.finditer(text):
        if any(ch.isdigit() for ch in m.group(0)):
            found.append((m.start(), "solana", m.group(0)))
    seen, out = set(), []
    for _, kind, mention in sorted(found):
        if mention not in seen:
            seen.add(mention)
            out.append((kind, mention))
    return out[:max_per_post], max(0, len(out) - max_per_post)


def is_original(text):
    """The watcher asks X for original posts only; a repost's text starts with "RT @"."""
    return not (text or "").lstrip().startswith("RT @")


# ---- 2. identify --------------------------------------------------------------

def facts(pair):
    """{price, liquidity, volume_24h, market_cap} of one DexScreener pair (None: not given)."""
    pair = pair or {}
    cap = _num(pair.get("marketCap"))
    return {"price": _num(pair.get("priceUsd")),
            "liquidity": _num((pair.get("liquidity") or {}).get("usd")),
            "volume_24h": _num((pair.get("volume") or {}).get("h24")),
            "market_cap": cap if cap is not None else _num(pair.get("fdv"))}


def _liquidity(pair):
    return facts(pair)["liquidity"] or 0


def _base(pair):
    return (pair or {}).get("baseToken") or {}


def _same(a, b, kind):
    a, b = a or "", b or ""
    return a.lower() == b.lower() if kind == "evm" else a == b


def choose(kind, mention, pairs):
    """(pair, candidates) for one mention from DexScreener's pairs; (None, 0) when nothing
    matches. A cashtag: the highest-liquidity pair whose base symbol is exactly the tag; the
    candidates are the different tokens with that symbol. An address: that token's
    highest-liquidity pair (its candidates: the chains it was found on)."""
    pairs = [p for p in pairs or [] if isinstance(p, dict)]
    if kind == "cashtag":
        tag = mention[1:].upper()
        hits = [p for p in pairs if (_base(p).get("symbol") or "").upper() == tag]
    else:
        hits = [p for p in pairs if _same(_base(p).get("address"), mention, kind)]
    if not hits:
        return None, 0
    tokens = {(p.get("chainId"), (_base(p).get("address") or "").lower()) for p in hits}
    return max(hits, key=_liquidity), len(tokens)


def is_large(symbol, market_cap):
    return (symbol or "").upper() in LARGE_SYMBOLS or (market_cap or 0) > LARGE_MARKET_CAP_USD


# ---- BTC from the once-a-minute price log ---------------------------------------

class BtcLog:
    """BTC's price at a minute from data/market/prices-YYYY-MM-DD.csv (the same minute or up to 2
    minutes before it). A day is read again when its file changed."""

    def __init__(self, folder):
        self.folder, self.days = folder, {}

    def _day(self, day):
        path = os.path.join(self.folder, f"prices-{day}.csv")
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return {}
        cached = self.days.get(day)
        if cached and cached[0] == stamp:
            return cached[1]
        prices = {}
        try:
            with open(path, newline="") as fh:
                for row in csv.DictReader(fh):
                    value = _num(row.get("btc_usd"))
                    if value and value > 0:
                        prices.setdefault((row.get("time_utc") or "")[:16], value)
        except OSError:
            return {}
        self.days[day] = (stamp, prices)
        for old in sorted(self.days)[:-4]:
            del self.days[old]
        return prices

    def price(self, when):
        if when is None:
            return None
        for back in range(3):
            t = when - timedelta(minutes=back)
            value = self._day(f"{t:%Y-%m-%d}").get(f"{t:%Y-%m-%d %H:%M}")
            if value:
                return value
        return None

    def change(self, start, end):
        a, b = self.price(start), self.price(end)
        return None if not a or not b else (b / a - 1) * 100


# ---- the recorder -------------------------------------------------------------

class Mentions:
    """add_posts() after each watcher round; tick() every check_seconds (its own thread in
    xposts_bot.py). Never raises into the watcher."""

    def __init__(self, cfg, data_folder, api, clock=None):
        self.c = cfg["xposts"]
        self.folder = os.path.join(data_folder, self.c.get("folder", "xposts"))
        os.makedirs(self.folder, exist_ok=True)
        self.api = api
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.btc = BtcLog(os.path.join(data_folder, "market"))
        self.max_per_post = self.c.get("mentions_max_per_post", 5)
        self.retry = timedelta(minutes=self.c.get("mentions_lookup_retry_minutes", 10))
        self.lock = threading.Lock()
        self.days = {}             # "YYYY-MM-DD" -> rows (dicts), the files still followed
        self.dirty = set()
        self.health = self._read_health()
        self._load(self.clock())

    # -- files --

    def path(self, day):
        return os.path.join(self.folder, f"mentions-{day}.csv")

    def _load(self, now):
        for back in range(3):                       # 24 h plus the tolerance: 2 days back is enough
            day = f"{now - timedelta(days=back):%Y-%m-%d}"
            try:
                with open(self.path(day), newline="") as fh:
                    rows = [{c: r.get(c) or "" for c in COLUMNS} for r in csv.DictReader(fh)]
            except OSError:
                continue
            if any(not self._finished(r) for r in rows):
                self.days[day] = rows

    def _save(self):
        for day in sorted(self.dirty):
            rows = self.days.get(day)
            if rows is None:
                continue
            tmp = self.path(day) + ".tmp"
            with open(tmp, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            os.replace(tmp, self.path(day))
        self.dirty.clear()
        for day in [d for d, rows in self.days.items() if all(self._finished(r) for r in rows)]:
            del self.days[day]

    def _read_health(self):
        try:
            with open(os.path.join(self.folder, "mentions_health.json")) as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _count(self, now, key, n=1):
        days = self.health.setdefault("days", {})
        day = days.setdefault(f"{now:%Y-%m-%d}", {k: 0 for k in COUNTS})
        day[key] = day.get(key, 0) + n
        for old in sorted(days)[:-35]:
            del days[old]

    def _write_health(self, now):
        self.health["updated"] = _iso(now)
        self.health["following_now"] = sum(1 for rows in self.days.values() for r in rows
                                           if not self._finished(r))
        path = os.path.join(self.folder, "mentions_health.json")
        with open(path + ".tmp", "w") as fh:
            json.dump(self.health, fh, indent=1, sort_keys=True)
        os.replace(path + ".tmp", path)

    # -- 1. new posts --

    def add_posts(self, saved, now=None):
        """The watcher's new rows ([account, post_id, posted_utc, seen_utc, text]): one row per
        mention, looked up at the next tick. Returns how many mentions were added."""
        try:
            with self.lock:
                return self._add_posts(saved, now or self.clock())
        except Exception:                    # recording only: never stops the watcher
            log.exception("ticker mentions: the new posts could not be read")
            return 0

    def _add_posts(self, saved, now):
        added = 0
        for account, post_id, posted, seen, text in saved:
            if not is_original(text):
                continue
            found, dropped = find_mentions(text, self.max_per_post)
            if dropped:
                self._count(now, "dropped_by_cap", dropped)
            if not found:
                continue
            self._count(now, "posts_with_mentions")
            day = (seen or _iso(now))[:10]
            rows = self.days.setdefault(day, [])
            have = {(r["post_id"], r["mention"]) for r in rows}
            for kind, mention in found:
                if (post_id, mention) in have:
                    continue
                row = {c: "" for c in COLUMNS}
                row.update(post_id=post_id, account=account, posted_utc=posted or seen,
                           seen_utc=seen, mention=mention, kind=kind, status="pending")
                rows.append(row)
                added += 1
            self.dirty.add(day)
        if added:
            self._count(now, "mentions", added)
        if self.dirty:
            self._save()
            self._write_health(now)
        return added

    # -- 2 and 3. lookups and checkpoints --

    def tick(self, now=None):
        """Look up the new mentions and read the checkpoints that are due. Never raises."""
        try:
            with self.lock:
                self._tick(now or self.clock())
        except Exception:
            log.exception("ticker mentions: this check was skipped")

    def _rows(self):
        return [r for rows in self.days.values() for r in rows]

    def _tick(self, now):
        for row in self._rows():
            if row["status"] == "pending":
                self._identify(row, now)
        due = {}
        for row in self._rows():
            if row["status"] != "identified" or self._finished(row):
                continue
            if self._checkpoints(row, None, now, mark_only=True):
                due.setdefault(row["chain"], []).append(row)
        for chain, rows in due.items():
            addresses = list(dict.fromkeys(r["token_address"] for r in rows))
            try:
                pairs = self.api.pairs_on_chain(chain, addresses)
                self._count(now, "requests", (len(addresses) + 29) // 30)
            except Exception as exc:
                self._count(now, "requests", (len(addresses) + 29) // 30)
                self._count(now, "errors")
                log.warning("ticker mentions: DexScreener check failed (%s)", str(exc)[:120])
                continue
            for row in rows:
                pair = self._pair_for(row, pairs)
                self._checkpoints(row, pair, now)
                self._mark(row)
        if self.dirty:
            self._save()
        self._write_health(now)

    def _mark(self, row):
        day = (row["seen_utc"] or "")[:10]
        if day in self.days:
            self.dirty.add(day)

    def _identify(self, row, now):
        kind, mention = row["kind"], row["mention"]
        try:
            if kind == "cashtag":
                pairs = self.api.search_pairs(mention[1:])
            elif kind == "solana":
                pairs = self.api.pairs_on_chain("solana", [mention])
            else:
                pairs = self.api.search_pairs(mention)
            self._count(now, "requests")
        except Exception as exc:
            self._count(now, "requests")
            self._count(now, "errors")
            seen = _utc(row["seen_utc"]) or now
            if now - seen > self.retry:
                row["status"] = "lookup failed"
                self._count(now, "lookup_failed")
            log.warning("ticker mentions: lookup of %s failed (%s)", mention, str(exc)[:120])
            self._mark(row)
            return
        pair, candidates = choose(kind, mention, pairs)
        row["candidates"] = str(candidates)
        if pair is None:
            row["status"] = "not found"
            self._count(now, "not_found")
            self._mark(row)
            return
        base = _base(pair)
        f = facts(pair)
        posted = _utc(row["posted_utc"]) or _utc(row["seen_utc"]) or now
        row.update(status="identified", chain=pair.get("chainId") or "",
                   token_address=base.get("address") or "", pair_address=pair.get("pairAddress") or "",
                   symbol=(base.get("symbol") or "")[:40], name=(base.get("name") or "")[:80],
                   large="yes" if is_large(base.get("symbol"), f["market_cap"]) else "no",
                   first_check_utc=_iso(now),
                   first_check_delay_seconds=f"{(now - posted).total_seconds():.0f}",
                   change_1h_at_first_check_pct=_cell(
                       _num((pair.get("priceChange") or {}).get("h1")), "{:g}"),
                   btc_change_1h_before_post_pct=_cell(
                       self.btc.change(posted - timedelta(hours=1), posted), "{:.3f}"),
                   btc_change_1h_before_first_check_pct=_cell(
                       self.btc.change(now - timedelta(hours=1), now), "{:.3f}"))
        for key in VALUES:
            row[f"{key}_first_usd"] = _cell(f[key])
        self._count(now, "identified")
        self._checkpoints(row, pair, now)            # a checkpoint already due takes this answer
        self._mark(row)

    def _pair_for(self, row, pairs):
        mine = [p for p in pairs or [] if isinstance(p, dict)
                and _same(_base(p).get("address"), row["token_address"], row["kind"])]
        same = [p for p in mine if p.get("pairAddress") == row["pair_address"]]
        return (same or [max(mine, key=_liquidity)] if mine else [None])[0]

    def _checkpoints(self, row, pair, now, mark_only=False):
        """Fill each checkpoint due now (at the first check at or after it, within the
        tolerance), mark the ones past it "missed". With mark_only, only marks the missed ones
        and says whether one is due now (so a request is worth making)."""
        posted = _utc(row["posted_utc"]) or _utc(row["seen_utc"])
        if posted is None:
            return False
        first = _utc(row["first_check_utc"])
        base = _num(row["price_first_usd"])
        wanted = False
        for label, minutes in CHECKPOINTS:
            at = f"at_{label}_utc"
            if row[at]:
                continue
            due = posted + timedelta(minutes=minutes)
            if now < due:
                break
            if now > due + timedelta(seconds=tolerance_seconds(minutes)):
                row[at] = "missed"
                self._mark(row)
                continue
            if mark_only:
                wanted = True
                continue
            f = facts(pair)
            if pair is None or not f["price"]:
                continue                               # no answer: try at the next check
            row[at] = _iso(now)
            for key in VALUES:
                row[f"{key}_{label}_usd"] = _cell(f[key])
            if base:
                row[f"change_{label}_pct"] = f"{(f['price'] / base - 1) * 100:.3f}"
            row[f"btc_change_{label}_pct"] = _cell(self.btc.change(first, now), "{:.3f}")
        return wanted

    @staticmethod
    def _finished(row):
        if row.get("status") in FINAL:
            return True
        return row.get("status") == "identified" and all(row.get(f"at_{label}_utc")
                                                         for label, _ in CHECKPOINTS)


# ---- reading the files back (the report, the daily comparison, the health row) -------

def read_rows(folder, first_day=None):
    """Every row of the mentions files (from first_day, "YYYY-MM-DD", when given)."""
    out = []
    try:
        names = sorted(n for n in os.listdir(folder)
                       if n.startswith("mentions-") and n.endswith(".csv"))
    except OSError:
        return out
    for name in names:
        if first_day and name[9:19] < first_day:
            continue
        try:
            with open(os.path.join(folder, name), newline="") as fh:
                out += list(csv.DictReader(fh))
        except OSError:
            continue
    return out


def _stat(values):
    if not values:
        return None
    return statistics.mean(values), statistics.median(values)


def report_lines(folder, now, days=7):
    """The "Ticker mentions" section of data/xposts/report.md."""
    cutoff = f"{now - timedelta(days=days):%Y-%m-%d}"
    rows = [r for r in read_rows(folder, cutoff) if (r.get("posted_utc") or "")[:10] >= cutoff]
    lines = ["## Ticker mentions", "",
             f"Recording only (screener/xmentions.py), the last {days} days. Cashtags, Solana "
             "and EVM addresses in the saved posts (at most 5 a post), each looked up once on "
             "DexScreener. Changes are from the price at the first check (not the post's own "
             "time); BTC is over the same real times, from the once-a-minute price log. "
             "\"large\": BTC, ETH, SOL, BNB, XRP, DOGE or above $5 billion. A handful of "
             "mentions says nothing yet; a mention is not a cause.", ""]
    if not rows:
        return lines + ["No ticker mentions recorded yet.", ""]
    found = [r for r in rows if r.get("status") == "identified"]
    status = {}
    for r in rows:
        status[r.get("status") or "?"] = status.get(r.get("status") or "?", 0) + 1
    lines += [f"{len(rows)} mention(s) in {len({r.get('post_id') for r in rows})} post(s): "
              + ", ".join(f"{n} {s}" for s, n in sorted(status.items())) + ".", ""]
    head = "| Account | Coins | Mentions | " + " | ".join(
        f"{label} coin avg / median (n) | {label} BTC avg / median" for label in ("5m", "15m", "60m"))
    lines += [head + " |", "|---|---|---|" + "---|---|" * 3]
    for account in sorted({r.get("account") or "" for r in found}, key=str.lower):
        for group in ("large", "small"):
            mine = [r for r in found if r.get("account") == account
                    and (r.get("large") == "yes") == (group == "large")]
            if not mine:
                continue
            cells = []
            for label in ("5m", "15m", "60m"):
                done = [r for r in mine if _num(r.get(f"change_{label}_pct")) is not None]
                coin = _stat([_num(r[f"change_{label}_pct"]) for r in done])
                btc = _stat([v for v in (_num(r.get(f"btc_change_{label}_pct")) for r in done)
                             if v is not None])
                missed = sum(1 for r in mine if r.get(f"at_{label}_utc") == "missed")
                cells.append("–" if coin is None else
                             f"{coin[0]:+.2f}% / {coin[1]:+.2f}% ({len(done)})")
                if missed:
                    cells[-1] += f", {missed} missed"
                cells.append("–" if btc is None else f"{btc[0]:+.2f}% / {btc[1]:+.2f}%")
            lines.append(f"| @{account} | {group} | {len(mine)} | " + " | ".join(cells) + " |")
    lines += ["", "Latest mentions (newest first; candidates = different tokens with that symbol "
              "in DexScreener's search answer, so more than 1 means the ticker is ambiguous):", "",
              "| Posted (UTC) | Account | Mention | Coin | Candidates | Large | First check after "
              "| 1 h change at first check | 5m | 15m | 60m | 24h |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r.get("posted_utc") or "", r.get("mention") or ""),
                    reverse=True)[:30]:
        delay = _num(r.get("first_check_delay_seconds"))
        cells = []
        for label, _ in CHECKPOINTS:
            at, change = r.get(f"at_{label}_utc") or "", _num(r.get(f"change_{label}_pct"))
            cells.append("missed" if at == "missed" else
                         f"{change:+.1f}%" if change is not None else "–")
        h1 = _num(r.get("change_1h_at_first_check_pct"))
        coin = (r.get("symbol") or r.get("status") or "").replace("|", "/")
        if r.get("chain"):
            coin += f" ({r['chain']})"
        lines.append(f"| {(r.get('posted_utc') or '')[:16].replace('T', ' ')} | @{r.get('account')} "
                     f"| {(r.get('mention') or '')[:14]} | {coin[:40]} | {r.get('candidates') or '–'} "
                     f"| {r.get('large') or '–'} | "
                     + (f"{delay / 60:.1f} min" if delay is not None else "–") + " | "
                     + (f"{h1:+.1f}%" if h1 is not None else "–") + " | " + " | ".join(cells) + " |")
    return lines + [""]


def comparison_line(folder, day):
    """The daily comparison's "Ticker mentions" line: the day and since the start."""
    rows = read_rows(folder)
    if not rows:
        return ["**Ticker mentions** (recording only): none recorded yet.", ""]

    def part(subset):
        found = [r for r in subset if r.get("status") == "identified"]
        large = sum(1 for r in found if r.get("large") == "yes")
        ambiguous = sum(1 for r in found if (_num(r.get("candidates")) or 0) > 1)
        not_found = sum(1 for r in subset if r.get("status") == "not found")
        return (f"{len(subset)} in {len({r.get('post_id') for r in subset})} post(s), "
                f"{len(found)} identified ({large} large, {ambiguous} ambiguous ticker(s)), "
                f"{not_found} not found")
    today = [r for r in rows if (r.get("seen_utc") or "").startswith(day)]
    return [f"**Ticker mentions** (recording only; cashtags and token addresses in the X posts, "
            f"followed on DexScreener for 24 h): {day}: {part(today)} | since the start: "
            f"{part(rows)}", ""]
