"""What we know about a token when the bot looks at it, saved for later analysis.

RECORDING ONLY. Nothing here is read by any buy, sell, filter or exit; every
function is wrapped by its caller so a failure in it can only leave cells blank.
Blank always means "not known / not saved", never zero.

1. record_fields() / cells(): extra entries.csv columns for every paper buy,
   from the RugCheck report and DexScreener pair the bot had already fetched
   (no new request): launchpad, first-seen time and token age, creator and
   their share, top-1 and top-10 holder share, holders, the largest insider
   network, the creator's other tokens (when RugCheck lists them), the pool's
   DEX and age, market cap and liquidity, and what our creator ledger knows.

2. CandidateLog: candidates.csv, ONE row per token the first time a strategy
   checks it (bought or skipped, with the verdict, the failed checks and what
   each version decided), then the token's price, market cap and liquidity
   about 1, 6 and 24 hours later from DexScreener's batched free call (30
   tokens per request), so skipped tokens have outcomes too.

3. CreatorLedger: creator -> the tokens we have seen them launch and which
   died (market cap under $5k, as early does). Seeded by early's dead creators.

PAPER TRADING ONLY: read-only GET requests, nothing signed or sent.
"""

import csv
import json
import os
from datetime import datetime, timedelta, timezone

TIME = "%Y-%m-%d %H:%M:%S"
DEAD_MCAP_USD = 5_000          # as early: a token under this market cap is dead
MAX_TOKENS_PER_CREATOR = 30
MAX_CREATORS = 20_000

# entries.csv, appended after the existing columns.
RECORD_COLUMNS = [
    "rc_launchpad", "rc_first_seen_utc", "token_age_hours", "rc_creator", "rc_creator_pct",
    "rc_top1_pct", "rc_top10_pct", "rc_total_holders", "rc_insider_largest_network",
    "rc_insider_largest_network_pct", "rc_creator_tokens", "rc_creator_tokens_dead",
    "dex_id", "pool_age_minutes", "market_cap_usd", "liquidity_usd",
    "creator_ledger_launches", "creator_ledger_dead",
]
# The RugCheck part (what record_fields() gives).
RUGCHECK_KEYS = ["rc_launchpad", "rc_first_seen_utc", "rc_creator", "rc_creator_pct",
                 "rc_top1_pct", "rc_top10_pct", "rc_total_holders", "rc_insider_largest_network",
                 "rc_insider_largest_network_pct", "rc_creator_tokens", "rc_creator_tokens_dead"]

CHECKPOINTS = (("1h", 60, 30), ("6h", 360, 60), ("24h", 1440, 120))   # name, minutes, grace min
CANDIDATE_COLUMNS = (
    ["first_checked_utc", "strategy", "token_address", "symbol", "name", "pair_address",
     "price_usd", "verdict", "failed_checks", "safety_checked", "decisions", "signal_wallets",
     "dex_id", "pool_age_minutes", "market_cap_usd", "liquidity_usd",
     "buys_5m", "sells_5m", "buys_1h", "sells_1h", "buys_24h", "sells_24h",
     "volume_5m_usd", "volume_1h_usd", "volume_24h_usd",
     "price_change_5m_pct", "price_change_1h_pct", "price_change_24h_pct"]
    + [k for k in RUGCHECK_KEYS] + ["token_age_hours", "creator_ledger_launches",
                                    "creator_ledger_dead"]
    + [c for name, _, _ in CHECKPOINTS
       for c in (f"price_{name}_usd", f"market_cap_{name}_usd", f"liquidity_{name}_usd",
                 f"time_{name}_utc")])


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cell(value):
    """A CSV cell: blank when unknown (None), a short number otherwise."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return value


def _utc(text):
    """A RugCheck/ISO time like 2026-10-10T18:31:17.42Z as an aware datetime."""
    try:
        return datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# 1. entries.csv columns
# ---------------------------------------------------------------------

def record_fields(report, pair, f, dead_mcap=DEAD_MCAP_USD):
    """The RugCheck facts (RUGCHECK_KEYS) of a report; None when there's no
    report or a fact isn't in it."""
    if not report:
        return {}
    from screener.filters import real_holders
    out = dict.fromkeys(RUGCHECK_KEYS)
    pad = report.get("launchpad") or {}
    out["rc_launchpad"] = (pad.get("platform") or pad.get("name")
                           or report.get("deployPlatform") or None)
    seen = _utc(report.get("detectedAt"))
    out["rc_first_seen_utc"] = seen.strftime(TIME) if seen else None
    out["rc_creator"] = report.get("creator") or None
    supply = _num((report.get("token") or {}).get("supply"))
    balance = _num(report.get("creatorBalance"))
    if supply and balance is not None:
        out["rc_creator_pct"] = balance / supply * 100
    holders = real_holders(report, pair, f)
    if holders:
        pcts = [_num(h.get("pct")) or 0.0 for h in holders]
        out["rc_top1_pct"], out["rc_top10_pct"] = pcts[0], sum(pcts[:10])
    total = report.get("totalHolders")
    out["rc_total_holders"] = total if isinstance(total, int) else None
    # No insider network in a report that has none listed means "none detected".
    networks = [n for n in (report.get("insiderNetworks") or []) if isinstance(n, dict)]
    if networks:
        big = max(networks, key=lambda n: _num(n.get("size")) or 0)
        out["rc_insider_largest_network"] = int(_num(big.get("size")) or 0)
        held = _num(big.get("currentHolding"))
        out["rc_insider_largest_network_pct"] = held / supply * 100 if held is not None and supply \
            else None
    else:
        out["rc_insider_largest_network"], out["rc_insider_largest_network_pct"] = 0, 0.0
    others = report.get("creatorTokens")
    if isinstance(others, list):
        out["rc_creator_tokens"] = len(others)
        out["rc_creator_tokens_dead"] = sum(
            1 for t in others if (_num((t or {}).get("marketCap")) or 0) < dead_mcap)
    return out


def pair_facts(pair, when):
    """DexScreener's side: DEX, pool age at `when`, market cap, liquidity."""
    pair = pair or {}
    created = _num(pair.get("pairCreatedAt"))
    age = None
    if created:
        age = (when - datetime.fromtimestamp(created / 1000, timezone.utc)).total_seconds() / 60
    return {"dex_id": pair.get("dexId") or None, "pool_age_minutes": age,
            "market_cap_usd": _num(pair.get("marketCap")) or _num(pair.get("fdv")),
            "liquidity_usd": _num((pair.get("liquidity") or {}).get("usd"))}


def token_age_hours(first_seen, when):
    seen = _utc(first_seen.replace(" ", "T")) if first_seen else None
    return (when - seen).total_seconds() / 3600 if seen else None


def cells(record, pair, when, ledger=None, mint=None):
    """RECORD_COLUMNS' cells for an entries.csv row (blank where unknown)."""
    rec = record or {}
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    facts = dict(rec, **pair_facts(pair, when))
    facts["token_age_hours"] = token_age_hours(rec.get("rc_first_seen_utc"), when)
    launches = dead = None
    if ledger is not None and rec.get("rc_creator"):
        launches, dead = ledger.stats(rec["rc_creator"], exclude=mint)
    facts["creator_ledger_launches"], facts["creator_ledger_dead"] = launches, dead
    return [_cell(facts.get(k)) for k in RECORD_COLUMNS]


# ---------------------------------------------------------------------
# 3. The creator ledger
# ---------------------------------------------------------------------

class CreatorLedger:
    """creator -> {token: dead? (True / False / None = not known)}, for the
    tokens we have seen them launch. Creators in early's dead_creators (the
    file data/early/positions.json) count as one launch that died, without
    being copied here. Saved to `path` only when something changed."""

    def __init__(self, path, early_path=None, dead_mcap=DEAD_MCAP_USD):
        self.path, self.dead_mcap, self.changed = path, dead_mcap, False
        try:
            with open(path) as fh:
                self.creators = json.load(fh).get("creators", {})
        except (OSError, ValueError):
            self.creators = {}
        self.early = set()
        if early_path:
            try:
                with open(early_path) as fh:
                    self.early = set(json.load(fh).get("dead_creators") or [])
            except (OSError, ValueError):
                pass

    def stats(self, creator, exclude=None):
        """(launches we know of, how many of them died) for this creator,
        not counting token `exclude` (the one being looked at)."""
        tokens = {m: d for m, d in (self.creators.get(creator) or {}).items() if m != exclude}
        launches = len(tokens) + (1 if creator in self.early else 0)
        dead = sum(1 for d in tokens.values() if d) + (1 if creator in self.early else 0)
        return launches, dead

    def note(self, creator, mint, dead=None):
        """A token this creator launched; dead = True/False when known. A
        known answer is never overwritten by an unknown one."""
        if not creator or not mint:
            return
        tokens = self.creators.setdefault(creator, {})
        if mint in tokens and (dead is None or tokens[mint] == dead):
            return
        tokens[mint] = dead if dead is not None else tokens.get(mint)
        while len(tokens) > MAX_TOKENS_PER_CREATOR:
            tokens.pop(next(iter(tokens)))
        while len(self.creators) > MAX_CREATORS:
            self.creators.pop(next(iter(self.creators)))
        self.changed = True

    def note_report(self, report, mint):
        """The creator's launch of `mint` and the other tokens RugCheck lists."""
        creator = (report or {}).get("creator")
        if not creator:
            return
        self.note(creator, mint)
        others = report.get("creatorTokens")
        if isinstance(others, list):
            for t in others:
                if isinstance(t, dict) and t.get("mint"):
                    self.note(creator, t["mint"], (_num(t.get("marketCap")) or 0) < self.dead_mcap)

    def save(self):
        if not self.changed:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"creators": self.creators}, fh)
        os.replace(tmp, self.path)
        self.changed = False


# ---------------------------------------------------------------------
# 2. candidates.csv
# ---------------------------------------------------------------------

class CandidateLog:
    """candidates.csv of a strategy's folder: a row per token the first time
    it is checked, and its later prices. Its own memory is the file."""

    def __init__(self, folder, strategy, name="candidates.csv"):
        self.path, self.strategy = os.path.join(folder, name), strategy
        self._seen = None

    # -- the file --

    def rows(self):
        try:
            with open(self.path, newline="") as fh:
                return list(csv.DictReader(fh))
        except OSError:
            return []

    def _write(self, rows):
        tmp = self.path + ".tmp"
        with open(tmp, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=CANDIDATE_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, self.path)

    def seen(self):
        if self._seen is None:
            self._seen = {r["token_address"] for r in self.rows()}
        return self._seen

    # -- first check --

    def add(self, result, report, record, now, verdict, failed, safety_checked, decisions,
            ledger=None, wallets=None):
        """One row for a token not seen before (a result of screener.filters:
        .address .symbol .name .pair). Returns True when a row was added."""
        if result.address in self.seen():
            return False
        pair = result.pair or {}
        when = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        facts = dict(record or {}, **pair_facts(pair, when))
        tx, vol, chg = pair.get("txns") or {}, pair.get("volume") or {}, pair.get("priceChange") or {}
        launches = dead = None
        if ledger is not None:
            ledger.note_report(report, result.address)
            if (record or {}).get("rc_creator"):
                launches, dead = ledger.stats(record["rc_creator"], exclude=result.address)
        row = {
            "first_checked_utc": when.strftime(TIME), "strategy": self.strategy,
            "token_address": result.address, "symbol": result.symbol, "name": result.name,
            "pair_address": pair.get("pairAddress"), "price_usd": _num(pair.get("priceUsd")),
            "verdict": verdict, "failed_checks": failed,
            "safety_checked": "yes" if safety_checked else "no",
            "decisions": decisions, "signal_wallets": wallets,
            "buys_5m": (tx.get("m5") or {}).get("buys"), "sells_5m": (tx.get("m5") or {}).get("sells"),
            "buys_1h": (tx.get("h1") or {}).get("buys"), "sells_1h": (tx.get("h1") or {}).get("sells"),
            "buys_24h": (tx.get("h24") or {}).get("buys"),
            "sells_24h": (tx.get("h24") or {}).get("sells"),
            "volume_5m_usd": vol.get("m5"), "volume_1h_usd": vol.get("h1"),
            "volume_24h_usd": vol.get("h24"),
            "price_change_5m_pct": chg.get("m5"), "price_change_1h_pct": chg.get("h1"),
            "price_change_24h_pct": chg.get("h24"),
            "token_age_hours": token_age_hours((record or {}).get("rc_first_seen_utc"), when),
            "creator_ledger_launches": launches, "creator_ledger_dead": dead,
            **facts,
        }
        from screener.paper_trader import append_row
        append_row(self.path, CANDIDATE_COLUMNS, [_cell(row.get(c)) for c in CANDIDATE_COLUMNS])
        self.seen().add(result.address)
        return True

    # -- later prices --

    def due(self, now):
        """{token: [checkpoint names]} due now: not yet asked, past its time and
        not past its grace time."""
        now = now.replace(tzinfo=None) if now.tzinfo else now
        out = {}
        for row in self.rows():
            if not row.get("price_usd"):
                continue            # no price at the first check: nothing to compare with
            start = datetime.strptime(row["first_checked_utc"], TIME)
            for name, minutes, grace in CHECKPOINTS:
                if row.get(f"time_{name}_utc"):
                    continue
                due = start + timedelta(minutes=minutes)
                if due <= now <= due + timedelta(minutes=grace):
                    out.setdefault(row["token_address"], []).append(name)
        return out

    def fill(self, due, pairs, now, allowed_dexes, ledger=None):
        """Save DexScreener's answer for the due tokens. The time is set even
        when DexScreener has no pair any more (price left blank): that means
        "asked, nothing there". A market cap under $5k marks the creator's
        token dead in the ledger."""
        from screener.filters import best_pair
        stamp = (now.replace(tzinfo=None) if now.tzinfo else now).strftime(TIME)
        rows = self.rows()
        for row in rows:
            names = due.get(row["token_address"])
            if not names:
                continue
            mine = [p for p in pairs if (p.get("baseToken") or {}).get("address")
                    == row["token_address"]]
            pair = next((p for p in mine if p.get("pairAddress") == row.get("pair_address")),
                        None) or best_pair(pairs, row["token_address"], allowed_dexes)
            facts = pair_facts(pair, now if now.tzinfo else now.replace(tzinfo=timezone.utc))
            price = _num((pair or {}).get("priceUsd"))
            for name in names:
                row[f"price_{name}_usd"] = _cell(price)
                row[f"market_cap_{name}_usd"] = _cell(facts["market_cap_usd"])
                row[f"liquidity_{name}_usd"] = _cell(facts["liquidity_usd"])
                row[f"time_{name}_utc"] = stamp
            if ledger is not None and row.get("rc_creator") and facts["market_cap_usd"] is not None \
                    and facts["market_cap_usd"] < ledger.dead_mcap:
                ledger.note(row["rc_creator"], row["token_address"], True)
        self._write(rows)


def reprice(log, api, now, allowed_dexes, ledger=None):
    """Ask DexScreener (batched, 30 tokens a request) about every token with a
    checkpoint due, and save the answers. Returns how many tokens were asked."""
    due = log.due(now)
    if not due:
        return 0
    pairs = api.pairs_for_tokens(list(due))
    log.fill(due, pairs, now, allowed_dexes, ledger)
    return len(due)
