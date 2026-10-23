"""The early-launch RECORDER: for every new pump.fun launch, what was known at creation
and the real price path afterwards, saved so features can be tested later.

RECORDING ONLY. It never buys, never sells, never uses a wallet, a key or a paid
service, and nothing else reads what it writes except the daily comparison's one
health line. It reads pump.fun's on-chain events from the Solana public RPC
(screener/pumpfeed.py, read-only logsSubscribe); launch_record_bot.py feeds it.

Each launch is followed in memory for TRACK_SECONDS (1 hour) after creation, then one
row is written (if it qualifies, see below) and the launch is forgotten. Memory is
bounded: compact per-launch state, capped wallet sets, a cap on launches followed, a
cap on the creator ledger.

Times: the on-chain time of the events (not when we received them). If the creation
event's on-chain time is missing or not plausible, the receive time is used instead
and created_source says "received" (otherwise "chain").

Columns (launches-YYYY-MM-DD.csv, one file per UTC day of creation; prices in SOL per
token; blank = not known, never 0):
  created_at_utc, created_hour_utc, created_weekday (0 = Monday), created_source,
  token_address, creator, name, symbol
  dev_buy_pct          the creator's buy in the creation transaction, % of the 1 billion supply
  dev_buy_sol          the same buy in SOL
  first_block_buyers   distinct non-creator wallets that bought in the creation block (slot)
  bundle_suspect_buyers distinct non-creator buyers among the first 4 trades after creation
  creator_prior_launches, creator_prior_dead, copycat_name
                       earlier launches by this creator that we saw (within the memory
                       window), how many of them are older than dead_after_minutes and never
                       graduated, and the launch bot's copycat-name rule
  buyers, sellers      distinct non-creator wallets that bought / sold in the hour
  buys, sells, volume_sol   trade counts (all wallets) and SOL traded
  buyers_60s           distinct non-creator buyers in the first 60 seconds
  creator_sold_within_60s, creator_sold_pct_1h   (pct of the tokens the creator bought)
  price_sol_5s ... price_sol_3600s   the price after the last trade at or before each
                       checkpoint after creation (blank if there was none)
  peak_price_sol, seconds_to_peak, curve_progress_pct_1h, graduated (yes/no),
  seconds_to_graduation
  btc_change_1h_pct, btc_change_24h_pct, eth_change_1h_pct, sol_change_1h_pct
                       the market backdrop when the launch was created (screener/backdrop.py)
  incomplete           1 if the feed had a gap during the launch's first 60 seconds
  sample               1 if the launch is in the 2% reproducible random sample of ALL launches
  qualified            1 if it had min_buyers_60s buyers in 60 s, or graduated
  tracked_seconds, wallets_capped

Which launches are written: every qualified launch, plus the sample (a hash of the token
address, so the same launches are chosen every time). The sample is a fair baseline of ALL
launches; qualified launches are not. The daily cap max_rows_per_day applies to the
qualified-only rows; sample rows are always written so the baseline cannot be cut off by
the cap.
"""

import csv
import hashlib
import io
import json
import os
from collections import deque
from datetime import datetime, timezone

from screener.pumpfeed import decode

TRACK_SECONDS = 3600
BUYERS_WINDOW_SECONDS = 60
SUPPLY_TOKENS = 1_000_000_000          # every pump.fun token has a fixed supply of 1 billion
PLAUSIBLE_SECONDS = 900                # an on-chain time further from "now" than this is ignored
DEFAULT_CHECKPOINTS = (5, 10, 20, 30, 60, 120, 300, 900, 3600)
BACKDROP_COLUMNS = ["btc_change_1h_pct", "btc_change_24h_pct", "eth_change_1h_pct",
                    "sol_change_1h_pct"]


def columns(checkpoints=DEFAULT_CHECKPOINTS):
    return (["created_at_utc", "created_hour_utc", "created_weekday", "created_source",
             "token_address", "creator", "name", "symbol",
             "dev_buy_pct", "dev_buy_sol", "first_block_buyers", "bundle_suspect_buyers",
             "creator_prior_launches", "creator_prior_dead", "copycat_name",
             "buyers", "sellers", "buys", "sells", "volume_sol", "buyers_60s",
             "creator_sold_within_60s", "creator_sold_pct_1h"]
            + [f"price_sol_{c}s" for c in checkpoints]
            + ["peak_price_sol", "seconds_to_peak", "curve_progress_pct_1h", "graduated",
               "seconds_to_graduation"] + BACKDROP_COLUMNS
            + ["incomplete", "sample", "qualified", "tracked_seconds", "wallets_capped"])


COLUMNS = columns()
ISO = "%Y-%m-%dT%H:%M:%SZ"


def utc(t):
    return datetime.fromtimestamp(t, timezone.utc)


def h64(text):
    """A stable 64-bit number for a name, wallet or token (for the compact ledger)."""
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


def in_sample(mint, sample_pct):
    """True for sample_pct percent of all tokens, always the same ones (a hash of the
    token address, not chance)."""
    return h64("sample:" + mint) % 1_000_000 < sample_pct * 10_000


def cell(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


# ---------------------------------------------------------------------
# the daily files
# ---------------------------------------------------------------------

class DailyCsv:
    """data/launch-record/launches-YYYY-MM-DD.csv: one file a day. A file written with a
    different header is rewritten with the new one first (old rows keep their values, new
    columns are blank), through a temporary file; a half-written last line left by a crash is
    cut off; rows are appended in one write."""

    def __init__(self, folder, cols=COLUMNS):
        self.folder, self.cols = folder, list(cols)
        self.checked = set()

    def path(self, day):
        return os.path.join(self.folder, f"launches-{day}.csv")

    def _prepare(self, path):
        if path in self.checked:
            return
        self.checked.add(path)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return
        with open(path, "rb") as fh:
            data = fh.read()
        if not data.endswith(b"\n"):                 # a crash left half a line: drop it
            cut = data.rfind(b"\n")
            data = data[:cut + 1] if cut >= 0 else b""
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        with open(path, newline="") as fh:
            header = next(csv.reader(fh), None)
        if header != self.cols:
            with open(path, newline="") as fh:
                old = list(csv.DictReader(fh))
            tmp = path + ".tmp"
            with open(tmp, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=self.cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(old)
            os.replace(tmp, path)

    def append(self, day, rows):
        """rows: lists of cells in column order. Returns the file's path."""
        if not rows:
            return None
        os.makedirs(self.folder, exist_ok=True)
        path = self.path(day)
        self._prepare(path)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        fresh = not os.path.exists(path) or os.path.getsize(path) == 0
        if fresh:
            w.writerow(self.cols)
        w.writerows(rows)
        with open(path, "a", newline="") as fh:
            fh.write(buf.getvalue())             # one write: a crash can only cut the last line
            fh.flush()
            os.fsync(fh.fileno())
        return path


# ---------------------------------------------------------------------
# one launch in memory
# ---------------------------------------------------------------------

class _Launch:
    __slots__ = (
        "mint", "creator", "name", "symbol", "recv", "t0", "chain", "slot", "due",
        "dev_buy_pct", "dev_buy_sol", "first_block", "bundle", "after_n", "buyers", "sellers",
        "buyers60", "buys", "sells", "volume", "cp_price", "cp_time", "cp_progress", "peak",
        "peak_rel", "creator_bought", "creator_sold", "creator_sold_60", "graduated_s",
        "capped", "backdrop", "prior_launches", "prior_dead", "copycat", "last_rel")

    def __init__(self, mint, creator, name, symbol, recv, t0, chain, slot, n_cp):
        self.mint, self.creator, self.name, self.symbol = mint, creator, name, symbol
        self.recv, self.t0, self.chain, self.slot = recv, t0, chain, slot
        self.due = recv + TRACK_SECONDS
        self.dev_buy_pct = self.dev_buy_sol = None
        self.first_block, self.bundle = set(), set()
        self.after_n = 0
        self.buyers, self.sellers, self.buyers60 = set(), set(), set()
        self.buys = self.sells = 0
        self.volume = 0.0
        self.cp_price = [None] * n_cp
        self.cp_time = [None] * n_cp
        self.cp_progress = [None] * n_cp
        self.peak = None
        self.peak_rel = None
        self.creator_bought = self.creator_sold = 0.0
        self.creator_sold_60 = False
        self.graduated_s = None
        self.capped = False
        self.backdrop = ()
        self.prior_launches = self.prior_dead = 0
        self.copycat = False
        self.last_rel = None


class LaunchRecorder:
    """All the decisions, driven by the feed's events and the clock. No network here:
    launch_record_bot.py feeds it and gives it the backdrop."""

    def __init__(self, cfg, data_folder, clock=None):
        import time
        self.clock = clock or time.time
        self.c = c = cfg["launch_record"]
        launch, momentum = cfg.get("launch", {}), cfg.get("momentum", {})
        self.checkpoints = tuple(c.get("checkpoints_seconds", DEFAULT_CHECKPOINTS))
        self.cols = columns(self.checkpoints)
        self.min_buyers = int(c.get("min_buyers_60s", 3))
        self.sample_pct = float(c.get("sample_pct", 2.0))
        self.max_rows = int(c.get("max_rows_per_day", 4000))
        self.max_launches = int(c.get("max_tracked_launches", 5000))
        self.max_wallets = int(c.get("max_wallets_per_launch", 3000))
        self.max_ledger = int(c.get("max_ledger_entries", 600_000))
        self.bundle_trades = int(c.get("bundle_window_trades", 4))
        self.silent_gap = float(c.get("silent_gap_seconds", momentum.get("feed_stale_seconds", 10)))
        self.copycat_days = c.get("copycat_window_days", launch.get("copycat_window_days", 7))
        self.creator_days = c.get("creator_memory_days", launch.get("creator_memory_days", 7))
        self.dead_after = c.get("dead_after_minutes", launch.get("dead_after_minutes", 60)) * 60
        self.folder = os.path.join(data_folder, c.get("folder", "launch-record"))
        os.makedirs(self.folder, exist_ok=True)
        self.writer = DailyCsv(self.folder, self.cols)
        self.launches = {}              # mint -> _Launch being followed
        self.order = deque()            # (due, mint), oldest first
        self.buffer = []                # (day, row) waiting to be written
        self.backdrop_values = ()
        self.names, self.creators, self.completed = {}, {}, {}   # the compact ledger
        self.recent = deque()           # creation times in the last hour (for the health line)
        self.days = {}                  # "YYYY-MM-DD" -> counters
        self.gaps = deque()             # (start, end or None) of feed gaps, last 2 hours
        self.feed_up = False
        self.last_message = None
        self.endpoint = None
        self.last_row = None
        self.started = self.clock()
        self.dropped_at_start = 0
        self.lags = []                  # receive time minus on-chain creation time (a sample)
        self.chain_creates = self.received_creates = 0
        self._load()

    # ---- persistence ---------------------------------------------------

    def _state_path(self):
        return os.path.join(self.folder, "state.json")

    def _health_path(self):
        return os.path.join(self.folder, "health.json")

    def _load(self):
        try:
            with open(self._state_path()) as fh:
                saved = json.load(fh)
            self.names = {int(k): v for k, v in saved.get("names", {}).items()}
            self.creators = {int(k): [tuple(x) for x in v]
                             for k, v in saved.get("creators", {}).items()}
            self.completed = {int(k): v for k, v in saved.get("completed", {}).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            self.names, self.creators, self.completed = {}, {}, {}
        try:
            with open(self._health_path()) as fh:
                old = json.load(fh)
            self.days = old.get("days", {})
            self.last_row = old.get("last_row_ts")
            self.dropped_at_start = int(old.get("in_flight", 0) or 0)
            if self.dropped_at_start:
                self._day(self.clock())["dropped_at_restart"] = \
                    self._day(self.clock()).get("dropped_at_restart", 0) + self.dropped_at_start
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.prune(self.clock())

    def save(self):
        """The ledger, to state.json (stays on the server; not pushed)."""
        snapshot = (dict(self.names), {k: list(v) for k, v in self.creators.items()},
                    dict(self.completed))
        self._write_state(*snapshot)

    def _write_state(self, names, creators, completed):
        tmp = self._state_path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"names": names, "creators": creators, "completed": completed}, fh,
                      separators=(",", ":"))
        os.replace(tmp, self._state_path())

    def prune(self, t):
        """Forget what is older than the memory windows; keep the ledger under its cap."""
        names_keep, creators_keep = self.copycat_days * 86400, self.creator_days * 86400
        self.names = {k: v for k, v in self.names.items() if t - v <= names_keep}
        self.creators = {k: [x for x in v if t - x[0] <= creators_keep]
                         for k, v in self.creators.items()}
        self.creators = {k: v for k, v in self.creators.items() if v}
        self.completed = {k: v for k, v in self.completed.items() if t - v <= creators_keep}
        total = len(self.names) + len(self.creators) + len(self.completed)
        if total > self.max_ledger:                       # over the cap: the oldest go first
            share = self.max_ledger / total
            self.names = self._newest(self.names, int(len(self.names) * share), lambda v: v)
            self.creators = self._newest(self.creators, int(len(self.creators) * share),
                                         lambda v: max(x[0] for x in v))
            self.completed = self._newest(self.completed, int(len(self.completed) * share),
                                          lambda v: v)
            self._count(t, "ledger_trimmed")
        cutoff = t - 7200
        while self.gaps and self.gaps[0][1] is not None and self.gaps[0][1] < cutoff:
            self.gaps.popleft()
        for day in sorted(self.days)[:-8]:
            del self.days[day]

    @staticmethod
    def _newest(table, keep, when):
        """The `keep` entries of a dict with the latest times (when(value) -> time)."""
        if len(table) <= keep:
            return table
        newest = sorted(table.items(), key=lambda kv: when(kv[1]), reverse=True)[:keep]
        return dict(newest)

    # ---- counters ------------------------------------------------------

    def _day(self, t):
        key = utc(t).strftime("%Y-%m-%d")
        return self.days.setdefault(key, {})

    def _count(self, t, key, n=1):
        d = self._day(t)
        d[key] = d.get(key, 0) + n

    # ---- the feed ------------------------------------------------------

    def connected(self, t=None, endpoint=None):
        t = t or self.clock()
        self._close_gap(t)
        self.endpoint = endpoint or self.endpoint
        self.feed_up, self.last_message = True, t

    def disconnected(self, t=None, stopping=False):
        t = t or self.clock()
        if self.feed_up and not stopping:
            self._count(t, "feed_disconnects")
            self.gaps.append((t, None))
        self.feed_up = False

    def _close_gap(self, t):
        if self.gaps and self.gaps[-1][1] is None:
            start = self.gaps[-1][0]
            self.gaps[-1] = (start, t)
            self._count(t, "gap_seconds", round(t - start))

    def _gap_overlaps(self, start, end, now):
        for g_start, g_end in self.gaps:
            if g_start < end and (g_end if g_end is not None else now) > start:
                return True
        return False

    def on_logs(self, logs, failed, t=None, slot=None):
        """One notification from the feed."""
        t = t or self.clock()
        if self.last_message is not None and self.feed_up and t - self.last_message > self.silent_gap:
            # a silent stretch on a live connection counts as a gap
            self.gaps.append((self.last_message, t))
            self._count(t, "gap_seconds", round(t - self.last_message))
        self.last_message = t
        if failed:
            return
        in_tx = set()                               # launches created in this transaction
        for e in decode(logs):
            if e["kind"] == "create":
                if self._on_create(e, t, slot):
                    in_tx.add(e["mint"])
            elif e["kind"] == "trade":
                self._on_trade(e, t, slot, e["mint"] in in_tx)
            else:
                self._on_complete(e, t)

    def set_backdrop(self, values):
        values = values or {}
        self.backdrop_values = tuple(values.get(k) for k in BACKDROP_COLUMNS)

    def _event_time(self, ts, recv, launch=None):
        """(time, from_chain): the event's on-chain time when plausible, else the receive time."""
        if ts is not None and abs(ts - recv) <= PLAUSIBLE_SECONDS:
            return float(ts), True
        return recv, False

    # ---- a new launch ----------------------------------------------------

    def _on_create(self, e, t, slot):
        mint, creator = e["mint"], e["creator"]
        if mint in self.launches:
            return False
        self._count(t, "launches_seen")
        self.recent.append(t)
        if len(self.launches) >= self.max_launches:      # over the cap: drop the oldest
            self._forget(self.order.popleft()[1], dropped=True) if self.order else None
        ts, chain = self._event_time(e.get("ts"), t)
        if chain:
            self.chain_creates += 1
            if len(self.lags) < 5000:
                self.lags.append(t - ts)
        else:
            self.received_creates += 1
        w = _Launch(mint, creator, e.get("name", ""), e.get("symbol", ""), t,
                    ts if chain else t, chain, slot, len(self.checkpoints))
        w.backdrop = self.backdrop_values
        # the launch bot's rules: a copycat name, and the creator's earlier launches
        keys = {h64(k) for k in (w.name.lower(), w.symbol.lower()) if k}
        for k in keys:
            seen = self.names.get(k)
            if seen is not None and t - seen <= self.copycat_days * 86400:
                w.copycat = True
            self.names.setdefault(k, int(t))
        ch, mid = h64(creator or ""), h64(mint)
        earlier = self.creators.get(ch, [])
        w.prior_launches = len(earlier)
        w.prior_dead = sum(1 for when, other in earlier
                           if t - when >= self.dead_after and other not in self.completed)
        if creator:
            self.creators.setdefault(ch, []).append((int(t), mid))
        self.launches[mint] = w
        self.order.append((w.due, mint))
        return True

    def _forget(self, mint, dropped=False):
        if self.launches.pop(mint, None) is not None and dropped:
            self._count(self.clock(), "dropped_over_cap")

    # ---- trades -----------------------------------------------------------

    def _on_trade(self, e, t, slot, in_creation_tx):
        w = self.launches.get(e["mint"])
        if w is None:
            return                                    # created before we were watching
        ts, from_chain = self._event_time(e.get("ts"), t)
        when = ts if (w.chain and from_chain) else t     # one clock per launch
        rel = when - w.t0
        if rel > TRACK_SECONDS or rel < -5:
            return
        rel = max(rel, 0.0)
        user, is_buy, sol = e["user"], e["is_buy"], e["sol"]
        is_creator = user == w.creator
        w.last_rel = rel
        wallet = hash(user)
        if is_buy:
            w.buys += 1
        else:
            w.sells += 1
        w.volume += sol or 0.0
        if is_creator:
            tokens = e.get("tokens") or 0.0
            if is_buy:
                w.creator_bought += tokens
                if in_creation_tx and w.dev_buy_pct is None:
                    w.dev_buy_pct = round(100 * tokens / SUPPLY_TOKENS, 4)
                    w.dev_buy_sol = sol
            else:
                w.creator_sold += tokens
                if rel <= BUYERS_WINDOW_SECONDS:
                    w.creator_sold_60 = True
        else:
            side = w.buyers if is_buy else w.sellers
            if wallet in side or len(side) < self.max_wallets:
                side.add(wallet)
            else:
                w.capped = True
            if is_buy and rel <= BUYERS_WINDOW_SECONDS:
                w.buyers60.add(wallet)
        if not in_creation_tx:
            if w.after_n < self.bundle_trades:
                w.after_n += 1
                if is_buy and not is_creator:
                    w.bundle.add(wallet)
            same_block = (slot is not None and w.slot is not None and slot == w.slot) or \
                (slot is None and w.chain and from_chain and int(ts) == int(w.t0))
            if same_block and is_buy and not is_creator:
                w.first_block.add(wallet)
        price = e.get("price_sol")
        if price and price > 0:
            if w.peak is None or price > w.peak:
                w.peak, w.peak_rel = price, rel
            for i, cp in enumerate(self.checkpoints):
                if rel <= cp and (w.cp_time[i] is None or rel >= w.cp_time[i]):
                    w.cp_price[i], w.cp_time[i] = price, rel
                    w.cp_progress[i] = e.get("progress_pct")

    def _on_complete(self, e, t):
        self.completed[h64(e["mint"])] = int(t)
        w = self.launches.get(e["mint"])
        if w is not None and w.graduated_s is None:
            ts, from_chain = self._event_time(e.get("ts"), t)
            w.graduated_s = max(0.0, (ts - w.t0) if (w.chain and from_chain) else (t - w.recv))

    # ---- the clock ----------------------------------------------------------

    def tick(self, t=None):
        """Finish the launches that are an hour old. Returns how many."""
        t = t or self.clock()
        n = 0
        while self.order and self.order[0][0] <= t:
            _, mint = self.order.popleft()
            w = self.launches.get(mint)
            if w is not None:
                self._finish(w, t, tracked=TRACK_SECONDS)
                n += 1
        while self.recent and t - self.recent[0] > 3600:
            self.recent.popleft()
        return n

    def finish_all(self, t=None):
        """For a test run only: finish the launches still followed, with the time they were
        followed in tracked_seconds. (A real run drops them: a partial hour would bias the data.)"""
        t = t or self.clock()
        for mint, w in list(self.launches.items()):
            self._finish(w, t, tracked=round(min(TRACK_SECONDS, t - w.recv)))

    def _finish(self, w, now, tracked):
        self.launches.pop(w.mint, None)
        qualified = len(w.buyers60) >= self.min_buyers or w.graduated_s is not None
        sample = in_sample(w.mint, self.sample_pct)
        day_key = utc(w.t0).strftime("%Y-%m-%d")
        day = self.days.setdefault(day_key, {})
        day["finished"] = day.get("finished", 0) + 1
        if tracked >= BUYERS_WINDOW_SECONDS:             # its first minute was fully watched
            day["watched_60"] = day.get("watched_60", 0) + 1
            if len(w.buyers60) >= self.min_buyers:
                day["buyers_qualified"] = day.get("buyers_qualified", 0) + 1
        if qualified:
            day["qualified"] = day.get("qualified", 0) + 1
        if sample:
            day["sample"] = day.get("sample", 0) + 1
        if not (qualified or sample):
            return
        if not sample:                                    # the cap is for the qualified-only rows
            if day.get("nonsample_rows", 0) >= self.max_rows:
                day["skipped_by_cap"] = day.get("skipped_by_cap", 0) + 1
                return
            day["nonsample_rows"] = day.get("nonsample_rows", 0) + 1
        self.buffer.append((day_key, self._row(w, qualified, sample, tracked, now)))

    def _row(self, w, qualified, sample, tracked, now):
        created = utc(w.t0)
        incomplete = self._gap_overlaps(w.recv, w.recv + BUYERS_WINDOW_SECONDS, now)
        creator_pct = None
        if w.creator_bought > 0:
            creator_pct = round(100 * w.creator_sold / w.creator_bought, 2)
        last = self.checkpoints.index(TRACK_SECONDS) if TRACK_SECONDS in self.checkpoints else None
        values = {
            "created_at_utc": created.strftime(ISO), "created_hour_utc": created.hour,
            "created_weekday": created.weekday(),
            "created_source": "chain" if w.chain else "received",
            "token_address": w.mint, "creator": w.creator, "name": w.name, "symbol": w.symbol,
            "dev_buy_pct": w.dev_buy_pct, "dev_buy_sol": w.dev_buy_sol,
            "first_block_buyers": len(w.first_block), "bundle_suspect_buyers": len(w.bundle),
            "creator_prior_launches": w.prior_launches, "creator_prior_dead": w.prior_dead,
            "copycat_name": int(w.copycat),
            "buyers": len(w.buyers), "sellers": len(w.sellers), "buys": w.buys, "sells": w.sells,
            "volume_sol": round(w.volume, 4), "buyers_60s": len(w.buyers60),
            "creator_sold_within_60s": int(w.creator_sold_60),
            "creator_sold_pct_1h": creator_pct,
            "peak_price_sol": w.peak,
            "seconds_to_peak": None if w.peak_rel is None else round(w.peak_rel, 1),
            "curve_progress_pct_1h": w.cp_progress[last] if last is not None else None,
            "graduated": "yes" if w.graduated_s is not None else "no",
            "seconds_to_graduation": None if w.graduated_s is None else round(w.graduated_s, 1),
            "incomplete": int(incomplete), "sample": int(sample), "qualified": int(qualified),
            "tracked_seconds": tracked, "wallets_capped": int(w.capped),
        }
        for i, cp in enumerate(self.checkpoints):
            values[f"price_sol_{cp}s"] = w.cp_price[i]
        for k, v in zip(BACKDROP_COLUMNS, w.backdrop or (None,) * 4):
            values[k] = v
        return [cell(values.get(col)) for col in self.cols]

    # ---- writing --------------------------------------------------------------

    def flush(self, t=None):
        """Write the finished rows (one append per day's file). Returns the number written."""
        t = t or self.clock()
        if not self.buffer:
            return 0
        by_day = {}
        for day, row in self.buffer:
            by_day.setdefault(day, []).append(row)
        written = 0
        for day, rows in by_day.items():
            try:
                self.writer.append(day, rows)
            except OSError:
                continue                                  # tried again at the next flush
            written += len(rows)
            self.days.setdefault(day, {})["rows_written"] = \
                self.days.setdefault(day, {}).get("rows_written", 0) + len(rows)
            self.buffer = [x for x in self.buffer if x[0] != day]
        if written:
            self.last_row = t
        return written

    # ---- health -------------------------------------------------------------------

    def health(self, t=None):
        t = t or self.clock()
        today = self.days.get(utc(t).strftime("%Y-%m-%d"), {})
        ongoing_gap = 0
        if self.gaps and self.gaps[-1][1] is None:
            ongoing_gap = round(t - self.gaps[-1][0])
        return {
            "updated": utc(t).strftime(ISO),
            "feed_up": self.feed_up, "endpoint": self.endpoint,
            "last_message": utc(self.last_message).strftime(ISO) if self.last_message else None,
            "feed_silent_seconds": round(t - self.last_message) if self.last_message else None,
            "last_row": utc(self.last_row).strftime(ISO) if self.last_row else None,
            "last_row_ts": self.last_row,
            "since_last_row_seconds": round(t - self.last_row) if self.last_row else None,
            "launches_seen_last_hour": len(self.recent),
            "in_flight": len(self.launches),
            "rows_written_today": today.get("rows_written", 0),
            "rows_skipped_by_cap_today": today.get("skipped_by_cap", 0),
            "max_rows_per_day": self.max_rows,
            "feed_disconnects_today": today.get("feed_disconnects", 0),
            "gap_seconds_today": today.get("gap_seconds", 0) + ongoing_gap,
            "started": utc(self.started).strftime(ISO),
            "dropped_at_last_restart": self.dropped_at_start,
            "days": self.days,
        }

    def write_health(self, t=None):
        data = self.health(t)
        tmp = self._health_path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, self._health_path())
        return data
