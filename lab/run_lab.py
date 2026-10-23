"""The strategy lab: test a trading rule on the recorded data in seconds.

    python lab/run_lab.py lab/rules/baseline_1h.toml      one rule
    python lab/run_lab.py --all                           every rule in lab/rules/ + summary.md
    python lab/run_lab.py lab/rules/x.toml --validate     only check the rule file (no results)

READ-ONLY on the bot's data and OFFLINE: it reads data/main-1min/candidates.csv (or
data/convergence/candidates.csv), makes no web request, changes no bot, strategy or setting, and
writes only to lab/results/. Not part of any workflow. See lab/README.md.

How a rule is judged (the numbers are not tuned to flatter anything):
  * The days are split by time: the earliest 60% are LEARN, the latest 40% are CHECK. If the rule
    has a [tune] section, its parameters are chosen on LEARN only and applied unchanged to CHECK.
  * An entry is at the price of the first check plus the buy slippage; the exit is at a recorded
    price. ONLY THREE PRICES EXIST after the first check: 1h, 6h and 24h. A rule cannot sell at
    any other moment. A token whose price is missing at the exit (DexScreener had no pair when
    asked) is a TOTAL LOSS (-100%), never zero change; a token whose checkpoint was not answered
    (too recent, or missed) cannot be tested and is left out, and the lab says how many.
  * Costs: the round trip (default 3%) plus the buy slippage (default 1.5%).
  * Each part is compared with 1,000 random draws of the same number of tokens from the same
    days (per day: as many tokens as the rule traded that day).
  * PASS needs ALL of: >= 30 trades in CHECK, positive profit, positive profit without the best
    trade, trades on >= 7 different days, and beating >= 95% of the random draws (99% for the
    11th idea and later, because the more ideas are tried the likelier one passes by luck).
"""

import argparse
import csv
import hashlib
import json
import math
import os
import random
import statistics
import sys
import tomllib
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAB = os.path.dirname(os.path.abspath(__file__))

CHECKPOINTS = ("1h", "6h", "24h")            # the only prices recorded after the first check
SOURCES = {"main-1min": os.path.join("data", "main-1min", "candidates.csv"),
           "convergence": os.path.join("data", "convergence", "candidates.csv")}
LEARN_SHARE = 0.6
DRAWS = 1000
SEED = 20261023
# The verdict (the user's rules).
MIN_TRADES, MIN_DAYS = 30, 7
BEAT, STRICT_BEAT, STRICT_AFTER = 0.95, 0.99, 10
STAKE_USD = 10.0
DEFAULT_SLIPPAGE, DEFAULT_ROUND_TRIP = 1.5, 3.0
LOST = "lost"                                 # asked, and DexScreener had no price: total loss

OPS = {"gt", "gte", "min", "lt", "lte", "max", "eq", "ne", "in", "not_in"}
TUNE_RESERVED = {"min_trades"}
MAX_GRID = 300


class LabError(Exception):
    """A problem with a rule file or the data, in plain words."""


# ---------------------------------------------------------------------
# the data
# ---------------------------------------------------------------------

def num(text):
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def derived(row):
    """Extra columns worked out from the recorded ones (blank when they cannot be)."""
    out = {}
    for tag in ("5m", "1h"):
        b, s = num(row.get(f"buys_{tag}")), num(row.get(f"sells_{tag}"))
        out[f"buy_share_{tag}_pct"] = None if b is None or s is None or b + s == 0 \
            else 100.0 * b / (b + s)
    return out


DERIVED_COLUMNS = ("buy_share_5m_pct", "buy_share_1h_pct")


class Token:
    """One row of candidates.csv: its columns, its entry price and its three outcomes."""

    __slots__ = ("row", "day", "p0", "out", "values")

    def __init__(self, row):
        self.row = row
        self.day = (row.get("first_checked_utc") or "")[:10]
        self.p0 = num(row.get("price_usd"))
        if self.p0 is not None and self.p0 <= 0:
            self.p0 = None
        self.out = {}
        for cp in CHECKPOINTS:
            if not row.get(f"time_{cp}_utc"):
                self.out[cp] = None                      # not answered: unknown
            else:
                price = num(row.get(f"price_{cp}_usd"))
                self.out[cp] = price if (price is not None and price > 0) else LOST
        self.values = derived(row)

    def get(self, column):
        if column in self.values:
            return self.values[column]
        return self.row.get(column)


def load_tokens(path):
    try:
        with open(path, newline="") as fh:
            return [Token(r) for r in csv.DictReader(fh)]
    except OSError:
        raise LabError(f"cannot read {path}")


def known_columns(tokens):
    cols = set(DERIVED_COLUMNS)
    if tokens:
        cols |= set(tokens[0].row.keys())
    return cols


# ---------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------

def load_rule(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        rule = tomllib.loads(raw.decode())
    except OSError:
        raise LabError(f"cannot read {path}")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise LabError(f"{os.path.basename(path)} is not valid TOML: {exc}")
    rule.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    rule["_hash"] = hashlib.sha256(raw).hexdigest()[:10]
    rule["_file"] = path
    return rule


def validate_rule(rule, columns):
    """Raise LabError for anything the lab cannot run, naming the problem."""
    name = rule["name"]
    allowed = {"name", "description", "source", "filter", "entry", "exit", "costs", "tune",
               "_hash", "_file"}
    odd = sorted(set(rule) - allowed)
    if odd:
        raise LabError(f"{name}: unknown section(s) {odd}; allowed: "
                       f"{sorted(k for k in allowed if not k.startswith('_'))}")
    if rule.get("source", "main-1min") not in SOURCES:
        raise LabError(f"{name}: source must be one of {sorted(SOURCES)}")
    for column, ops in (rule.get("filter") or {}).items():
        if column not in columns:
            raise LabError(f"{name}: filter on unknown column '{column}' (see lab/README.md)")
        if not isinstance(ops, dict) or not ops:
            raise LabError(f"{name}: filter.{column} needs operators such as max = 20")
        bad = set(ops) - OPS
        if bad:
            raise LabError(f"{name}: filter.{column} has unknown operator(s) {sorted(bad)}; "
                           f"use {sorted(OPS)}")
    ex = rule.get("exit") or {}
    mode = ex.get("mode", "fixed")
    if mode == "fixed":
        if ex.get("at", "1h") not in CHECKPOINTS:
            raise LabError(f"{name}: exit.at must be one of {CHECKPOINTS} (only these prices "
                           "are recorded)")
    elif mode == "first_hit":
        if ex.get("take_profit_pct") is None and ex.get("stop_loss_pct") is None:
            raise LabError(f"{name}: first_hit needs take_profit_pct and/or stop_loss_pct")
        for k in ("take_profit_pct", "stop_loss_pct"):
            if ex.get(k) is not None and not (isinstance(ex[k], (int, float)) and ex[k] > 0):
                raise LabError(f"{name}: exit.{k} must be a positive number")
        if ex.get("final", "24h") not in CHECKPOINTS:
            raise LabError(f"{name}: exit.final must be one of {CHECKPOINTS}")
    else:
        raise LabError(f"{name}: exit.mode must be 'fixed' or 'first_hit'")
    for k, lo in (("slippage_pct", 0), ("round_trip_pct", 0)):
        section = "entry" if k == "slippage_pct" else "costs"
        v = (rule.get(section) or {}).get(k)
        if v is not None and not (isinstance(v, (int, float)) and lo <= v < 100):
            raise LabError(f"{name}: {section}.{k} must be a number from 0 to 100")
    tune = rule.get("tune") or {}
    combos = 1
    for key, values in tune.items():
        if key in TUNE_RESERVED:
            continue
        if not isinstance(values, list) or not values:
            raise LabError(f"{name}: tune.\"{key}\" must be a non-empty list of values")
        parts = key.split(".")
        if parts[0] not in ("filter", "exit", "entry", "costs") or len(parts) < 2:
            raise LabError(f"{name}: tune key '{key}' must start with filter., exit., entry. "
                           "or costs.")
        if parts[0] == "filter" and (len(parts) != 3 or parts[1] not in columns
                                     or parts[2] not in OPS):
            raise LabError(f"{name}: tune key '{key}' must be filter.<column>.<operator>")
        combos *= len(values)
    if combos > MAX_GRID:
        raise LabError(f"{name}: the tune grid has {combos} combinations (the most is {MAX_GRID})")


def set_path(rule, dotted, value):
    node = rule
    parts = dotted.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def grid(rule):
    """[(label, rule with those parameters set)] - just the rule when it has no [tune]."""
    tune = {k: v for k, v in (rule.get("tune") or {}).items() if k not in TUNE_RESERVED}
    if not tune:
        return [({}, rule)]
    keys = sorted(tune)
    out = [{}]
    for k in keys:
        out = [dict(o, **{k: v}) for o in out for v in tune[k]]
    result = []
    for choice in out:
        copy = json.loads(json.dumps({k: v for k, v in rule.items() if not k.startswith("_")}))
        for k, v in choice.items():
            set_path(copy, k, v)
        copy["_hash"], copy["_file"] = rule["_hash"], rule["_file"]
        result.append((choice, copy))
    return result


# ---------------------------------------------------------------------
# filters, exits, costs
# ---------------------------------------------------------------------

def _is_text(want):
    items = want if isinstance(want, list) else [want]
    return bool(items) and all(isinstance(x, str) for x in items)


def passes(token, filters):
    """(True/False, column that was unknown or None). A token whose value for a filtered
    column is blank cannot be judged and is left out."""
    for column, ops in (filters or {}).items():
        raw = token.get(column)
        for op, want in ops.items():
            if raw in (None, ""):
                return False, column
            if _is_text(want):
                v = str(raw)
            else:
                v = raw if isinstance(raw, float) else num(raw)
                if v is None:
                    return False, column
            many = want if isinstance(want, list) else [want]
            if op in ("gt", "lt", "gte", "lte", "min", "max") and isinstance(want, list):
                raise LabError("filter %s.%s needs one number" % (column, op))
            ok = {"gt": lambda: v > want, "gte": lambda: v >= want, "min": lambda: v >= want,
                  "lt": lambda: v < want, "lte": lambda: v <= want, "max": lambda: v <= want,
                  "eq": lambda: v in many, "ne": lambda: v not in many,
                  "in": lambda: v in many, "not_in": lambda: v not in many}[op]()
            if not ok:
                return False, None
    return True, None


def exit_price(token, ex):
    """The price the rule sells at: a number, LOST (total loss), or None (cannot be known)."""
    mode = (ex or {}).get("mode", "fixed")
    if token.p0 is None:
        return None
    if mode == "fixed":
        return token.out[(ex or {}).get("at", "1h")]
    tp, sl = ex.get("take_profit_pct"), ex.get("stop_loss_pct")
    final = ex.get("final", "24h")
    for cp in CHECKPOINTS:
        o = token.out[cp]
        if o is None:
            return None                     # an unanswered checkpoint before any exit
        if o == LOST:
            return LOST
        change = (o / token.p0 - 1) * 100
        if cp == final:
            return o
        if tp is not None and change >= tp:
            return o
        if sl is not None and change <= -sl:
            return o
    return None


def trade_pnl(p0, price, slippage_pct, round_trip_pct, stake=STAKE_USD):
    """Profit in dollars on `stake`. Buy at the first-check price plus slippage; sell at `price`;
    the round trip costs round_trip_pct of the stake. A missing exit price (LOST) is a total loss:
    -100% of the stake (no further fee is charged on a worthless sale)."""
    if price == LOST or price is None:
        return -stake
    entry = p0 * (1 + slippage_pct / 100)
    return stake * (price / entry - 1) - stake * round_trip_pct / 100


def evaluate(tokens, rule):
    """(trades, universe, counts). trades: [(day, pnl)] of the tokens that pass the rule's filters;
    universe: [(day, pnl)] of every token with an entry price and a known exit (the chance pool);
    counts: what was left out and why."""
    slip = (rule.get("entry") or {}).get("slippage_pct", DEFAULT_SLIPPAGE)
    rt = (rule.get("costs") or {}).get("round_trip_pct", DEFAULT_ROUND_TRIP)
    ex, filters = rule.get("exit") or {}, rule.get("filter") or {}
    trades, universe = [], []
    counts = {"tokens": len(tokens), "no_entry_price": 0, "exit_not_answered": 0,
              "lost": 0, "unknown_filter": {}}
    for t in tokens:
        if t.p0 is None:
            counts["no_entry_price"] += 1
            continue
        price = exit_price(t, ex)
        if price is None:
            counts["exit_not_answered"] += 1
            continue
        pnl = trade_pnl(t.p0, price, slip, rt)
        universe.append((t.day, pnl))
        ok, unknown = passes(t, filters)
        if unknown:
            counts["unknown_filter"][unknown] = counts["unknown_filter"].get(unknown, 0) + 1
        if ok:
            trades.append((t.day, pnl))
            counts["lost"] += price == LOST
    return trades, universe, counts


# ---------------------------------------------------------------------
# the time split, the statistics, the random baseline
# ---------------------------------------------------------------------

def split_days(days, learn_share=LEARN_SHARE):
    """(learn days, check days): the earliest `learn_share` of the days and the rest."""
    days = sorted(set(days))
    if len(days) < 2:
        raise LabError(f"only {len(days)} day(s) with usable data: at least 2 are needed to split "
                       "them into learn and check")
    n = max(1, min(len(days) - 1, int(len(days) * learn_share + 0.5)))
    return days[:n], days[n:]


def stats(trades, stake=STAKE_USD):
    """Numbers for a list of (day, pnl)."""
    n = len(trades)
    pnls = sorted((p for _, p in trades), reverse=True)
    total = sum(pnls)
    returns = [p / stake * 100 for p in pnls]
    return {
        "trades": n,
        "win_rate": 100.0 * sum(1 for p in pnls if p > 0) / n if n else None,
        "avg_return_pct": statistics.fmean(returns) if n else None,
        "median_return_pct": statistics.median(returns) if n else None,
        "profit": total,
        "profit_without_best": total - sum(pnls[:1]) if n else 0.0,
        "profit_without_best3": total - sum(pnls[:3]) if n else 0.0,
        "days": len({d for d, _ in trades}),
    }


def baseline(trades, universe, draws=DRAWS, seed=SEED):
    """Random draws with the same number of tokens on each day, from that day's tokens.
    Returns {"beaten": share of draws the rule's profit beats, "beat_it": share that beat
    the rule, "mean": average profit of a draw, "p95": 95th percentile of draws}."""
    rule_total = sum(p for _, p in trades)
    need = {}
    for d, _ in trades:
        need[d] = need.get(d, 0) + 1
    pool = {}
    for d, p in universe:
        pool.setdefault(d, []).append(p)
    if not trades:
        return {"beaten": None, "beat_it": None, "mean": None, "p95": None, "draws": 0}
    rng = random.Random(seed)
    totals = []
    for _ in range(draws):
        total = 0.0
        for d in sorted(need):
            total += sum(rng.sample(pool[d], min(need[d], len(pool[d]))))
        totals.append(total)
    totals.sort()
    beaten = sum(1 for t in totals if t < rule_total - 1e-9) / draws
    beat_it = sum(1 for t in totals if t >= rule_total - 1e-9) / draws
    return {"beaten": beaten, "beat_it": beat_it, "mean": statistics.fmean(totals),
            "p95": totals[int(0.95 * (draws - 1))], "draws": draws}


def verdict(check, base, idea_number):
    """(passed, [failed tests], needed share of random draws beaten)."""
    needed = STRICT_BEAT if idea_number > STRICT_AFTER else BEAT
    failed = []
    if check["trades"] < MIN_TRADES:
        failed.append(f"fewer than {MIN_TRADES} trades in CHECK ({check['trades']})")
    if not check["profit"] > 0:
        failed.append(f"profit after costs is not positive in CHECK (${check['profit']:+.2f})")
    if not check["profit_without_best"] > 0:
        failed.append("profit without the best trade is not positive in CHECK "
                      f"(${check['profit_without_best']:+.2f})")
    if check["days"] < MIN_DAYS:
        failed.append(f"trades on fewer than {MIN_DAYS} different days in CHECK ({check['days']})")
    beaten = base.get("beaten")
    if beaten is None or beaten < needed:
        shown = "no trades" if beaten is None else f"{beaten * 100:.1f}%"
        failed.append(f"does not beat {needed * 100:.0f}% of random draws in CHECK ({shown})")
    return not failed, failed, needed


# ---------------------------------------------------------------------
# results folder, the number of ideas tried
# ---------------------------------------------------------------------

HISTORY_COLUMNS = ["run_at_utc", "rule", "rule_hash", "source", "ideas_added",
                   "idea_number", "verdict"]


def read_history(results_dir):
    path = os.path.join(results_dir, "history.csv")
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def idea_number(history, rule, combos):
    """(this rule's idea number, ideas tried so far, is it already counted). Every distinct
    version of a rule file is one idea; a [tune] grid counts every combination."""
    seen = {}
    for r in history:
        key = (r["rule"], r["rule_hash"])
        if key not in seen:
            seen[key] = int(r["idea_number"])
    key = (rule["name"], rule["_hash"])
    if key in seen:
        return seen[key], max(seen.values()), True
    total = max(seen.values(), default=0)
    return total + combos, total + combos, False


def append_history(results_dir, rule, source, combos, number, verdict_text):
    os.makedirs(results_dir, exist_ok=True)
    path = os.path.join(results_dir, "history.csv")
    fresh = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if fresh:
            w.writerow(HISTORY_COLUMNS)
        w.writerow([datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), rule["name"],
                    rule["_hash"], source, combos, number, verdict_text])


# ---------------------------------------------------------------------
# running one rule
# ---------------------------------------------------------------------

def money(x):
    return f"{x:+.2f}"


def pct(x):
    return "-" if x is None else f"{x:.1f}%"


def part_lines(title, s, b):
    lines = [f"  {title}",
             f"    trades {s['trades']}   win rate {pct(s['win_rate'])}   "
             f"average {pct(s['avg_return_pct'])}   median {pct(s['median_return_pct'])}",
             f"    profit on $10 a trade ${money(s['profit'])}   without the best trade "
             f"${money(s['profit_without_best'])}   without the best 3 "
             f"${money(s['profit_without_best3'])}   days with trades {s['days']}"]
    if b.get("beaten") is None:
        lines.append("    random draws: none (no trades)")
    else:
        lines.append(f"    random draws ({b['draws']}, same number of tokens on the same days): "
                     f"average ${money(b['mean'])}, the best 5% reach ${money(b['p95'])}; "
                     f"{b['beat_it'] * 100:.1f}% of draws beat the rule, the rule beats "
                     f"{b['beaten'] * 100:.1f}%")
    return lines


def choose_on_learn(options, tokens_by_part, tune_min_trades):
    """Pick the parameter set with the highest LEARN profit among those with enough trades."""
    best = None
    for choice, rule in options:
        trades, universe, _ = tokens_by_part(rule, "learn")
        s = stats(trades)
        if s["trades"] < tune_min_trades:
            continue
        if best is None or s["profit"] > best[0]:
            best = (s["profit"], choice, rule)
    return best


def run_rule(rule_path, data_dir=HERE, results_dir=None, draws=DRAWS, seed=None, save=True,
             out=print):
    """Run one rule file. Returns the result dict (also saved in results_dir)."""
    results_dir = results_dir or os.path.join(LAB, "results")
    rule = load_rule(rule_path)
    source = rule.get("source", "main-1min")
    path = os.path.join(data_dir, SOURCES.get(source, "?"))
    all_tokens = load_tokens(path) if source in SOURCES else []
    validate_rule(rule, known_columns(all_tokens))
    seed = seed if seed is not None else rule.get("seed", SEED)
    options = grid(rule)
    combos = len(options)

    # the days that have at least one token with an entry and a known exit, under the exit
    # of each option (the split is the same for every option of a rule)
    probe = options[0][1]
    ex = probe.get("exit") or {}
    usable_days = [t.day for t in all_tokens if t.p0 is not None and exit_price(t, ex) is not None]
    learn_days, check_days = split_days(usable_days)
    learn_set, check_set = set(learn_days), set(check_days)

    def part(rule_, which):
        keep = learn_set if which == "learn" else check_set
        tokens = [t for t in all_tokens if t.day in keep]
        return evaluate(tokens, rule_)

    chosen, tuned_note = {}, ""
    if combos > 1:
        found = choose_on_learn(options, part, int((rule.get("tune") or {}).get("min_trades", 20)))
        if found is None:
            raise_text = (f"no parameter set had at least "
                          f"{(rule.get('tune') or {}).get('min_trades', 20)} trades on the LEARN days")
            chosen_rule, chosen = options[0][1], {}
            tuned_note = f"TUNING FAILED: {raise_text}"
        else:
            _, chosen, chosen_rule = found
            tuned_note = ("parameters chosen on the LEARN days only: "
                          + ", ".join(f"{k} = {v}" for k, v in sorted(chosen.items())))
    else:
        chosen_rule = options[0][1]

    l_trades, l_universe, l_counts = part(chosen_rule, "learn")
    c_trades, c_universe, c_counts = part(chosen_rule, "check")
    l_stats, c_stats = stats(l_trades), stats(c_trades)
    l_base = baseline(l_trades, l_universe, draws, seed)
    c_base = baseline(c_trades, c_universe, draws, seed)

    history = read_history(results_dir)
    number, tried, counted = idea_number(history, rule, combos)
    passed, failed, needed = verdict(c_stats, c_base, number)
    if tuned_note.startswith("TUNING FAILED"):
        passed, failed = False, failed + [tuned_note]
    verdict_text = "PASS" if passed else "FAIL"

    ex_used = chosen_rule.get("exit") or {}
    exit_text = (f"sell at the {ex_used.get('at', '1h')} price" if ex_used.get("mode", "fixed") == "fixed"
                 else "sell at the first of 1h/6h/24h where the price is "
                 + " or ".join(x for x in (
                     f"up {ex_used['take_profit_pct']:g}%" if ex_used.get("take_profit_pct") else "",
                     f"down {ex_used['stop_loss_pct']:g}%" if ex_used.get("stop_loss_pct") else "") if x)
                 + f" (else at {ex_used.get('final', '24h')})")
    filt = chosen_rule.get("filter") or {}
    filter_text = "; ".join(f"{c} " + ", ".join(f"{o} {v}" for o, v in ops.items())
                            for c, ops in filt.items()) or "none (every token)"
    lines = [
        "=" * 78,
        f"RULE {rule['name']}  (file version {rule['_hash']})   data: {source}",
        f"  {rule.get('description', '')}".rstrip(),
        f"  filters: {filter_text}",
        f"  entry: first-check price + {(chosen_rule.get('entry') or {}).get('slippage_pct', DEFAULT_SLIPPAGE):g}% slippage;"
        f" exit: {exit_text}",
        f"  costs: {(chosen_rule.get('costs') or {}).get('round_trip_pct', DEFAULT_ROUND_TRIP):g}% round trip"
        " + the buy slippage; a missing exit price is a total loss",
        "  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.",
    ]
    if tuned_note:
        lines.append(f"  {tuned_note} ({combos} combinations tried, each counts as an idea)")
    lines += [
        f"  days: LEARN {learn_days[0]} .. {learn_days[-1]} ({len(learn_days)} days), "
        f"CHECK {check_days[0]} .. {check_days[-1]} ({len(check_days)} days)",
        f"  left out (CHECK): {c_counts['no_entry_price']} with no entry price, "
        f"{c_counts['exit_not_answered']} whose exit checkpoint has no answer yet/missed"
        + "".join(f", {n} with no {col}" for col, n in sorted(c_counts['unknown_filter'].items()))
        + f"; total losses among the trades: {c_counts['lost']}",
        "",
    ]
    lines += part_lines("LEARN (earliest 60% of days)", l_stats, l_base)
    lines += part_lines("CHECK (latest 40% of days)", c_stats, c_base)
    lines.append("")
    if number > STRICT_AFTER:
        lines.append(f"  WARNING: this is idea no. {number}. The more ideas are tried the likelier one "
                     f"passes by luck, so it must beat {STRICT_BEAT * 100:.0f}% of random draws "
                     f"instead of {BEAT * 100:.0f}%.")
    else:
        lines.append(f"  Ideas tried so far: {number} (after the {STRICT_AFTER}th idea the bar rises "
                     f"to {STRICT_BEAT * 100:.0f}% of random draws).")
    if passed:
        lines.append("  VERDICT: PASS - all five tests passed in CHECK (still only a lead to "
                     "watch on new days, not proof).")
    else:
        lines.append("  VERDICT: FAIL - " + "; ".join(failed))
    text = "\n".join(l for l in lines if l is not None)
    out(text)

    result = {
        "rule": rule["name"], "rule_hash": rule["_hash"], "description": rule.get("description", ""),
        "source": source, "idea_number": number, "ideas_added": 0 if counted else combos,
        "chosen": chosen, "learn_days": learn_days, "check_days": check_days,
        "learn": l_stats, "check": c_stats, "learn_baseline": l_base, "check_baseline": c_base,
        "left_out_check": c_counts, "needed_beat": needed, "verdict": verdict_text,
        "failed": failed, "seed": seed,
    }
    if save:
        os.makedirs(results_dir, exist_ok=True)
        with open(os.path.join(results_dir, f"{rule['name']}.md"), "w") as fh:
            fh.write("```\n" + text + "\n```\n")
        with open(os.path.join(results_dir, f"{rule['name']}.json"), "w") as fh:
            json.dump(result, fh, indent=1)
        append_history(results_dir, rule, source, 0 if counted else combos, number, verdict_text)
    return result


def write_summary(results, results_dir):
    lines = ["# Strategy lab summary", "",
             "One row per rule (CHECK = the latest 40% of days; the rule's parameters were fixed on "
             "the earlier days). Profit is on $10 a trade after costs. Only the 1h, 6h and 24h "
             "prices exist, so these are the only exits that can be tested.", "",
             "| Rule | Idea | LEARN trades | LEARN avg | CHECK trades | CHECK avg | CHECK profit "
             "| without best | CHECK days | beats random | Verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        c, l, b = r["check"], r["learn"], r["check_baseline"]
        beat = "-" if b.get("beaten") is None else f"{b['beaten'] * 100:.1f}% (need {r['needed_beat'] * 100:.0f}%)"
        verdict_cell = "PASS" if r["verdict"] == "PASS" else "FAIL: " + "; ".join(r["failed"])
        lines.append(f"| {r['rule']} | {r['idea_number']} | {l['trades']} | {pct(l['avg_return_pct'])} "
                     f"| {c['trades']} | {pct(c['avg_return_pct'])} | ${money(c['profit'])} "
                     f"| ${money(c['profit_without_best'])} | {c['days']} | {beat} | {verdict_cell} |")
    lines += ["", f"Ideas tried so far: {max((r['idea_number'] for r in results), default=0)}. "
              f"Chance alone passes some rules: after the {STRICT_AFTER}th idea the bar is "
              f"{STRICT_BEAT * 100:.0f}% of random draws.", ""]
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "summary.md"), "w") as fh:
        fh.write("\n".join(lines))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rule", nargs="?", help="a rule file, e.g. lab/rules/baseline_1h.toml")
    parser.add_argument("--all", action="store_true", help="run every rule in lab/rules/")
    parser.add_argument("--validate", action="store_true",
                        help="only check the rule file(s); no results, nothing is counted")
    parser.add_argument("--data-dir", default=HERE, help="the folder that holds data/")
    parser.add_argument("--results-dir", default=os.path.join(LAB, "results"))
    parser.add_argument("--draws", type=int, default=DRAWS)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        if args.all:
            files = sorted(os.path.join(LAB, "rules", f) for f in os.listdir(os.path.join(LAB, "rules"))
                           if f.endswith(".toml"))
        elif args.rule:
            files = [args.rule]
        else:
            parser.print_help()
            return 2
        if args.validate:
            for f in files:
                rule = load_rule(f)
                source = rule.get("source", "main-1min")
                tokens = load_tokens(os.path.join(args.data_dir, SOURCES.get(source, "?")))
                validate_rule(rule, known_columns(tokens))
                print(f"{rule['name']}: OK ({len(grid(rule))} parameter set(s))")
            return 0
        results = [run_rule(f, args.data_dir, args.results_dir, args.draws, args.seed) for f in files]
        if args.all:
            print(write_summary(results, args.results_dir))
    except LabError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
