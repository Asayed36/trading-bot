"""Side-by-side results of the paper strategies, for one day and all time.

Reads each strategy's journal.csv and positions.json. Nothing here trades.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

MARKER = "<!-- daily-comparison: {} -->"


def _read(folder):
    rows, state = [], {"open_positions": []}
    journal = os.path.join(folder, "journal.csv")
    if os.path.exists(journal):
        with open(journal, newline="") as fh:
            rows = list(csv.DictReader(fh))
    positions = os.path.join(folder, "positions.json")
    if os.path.exists(positions):
        with open(positions) as fh:
            state = json.load(fh)
    return rows, state


def _when(text):
    """Journal times ('YYYY-MM-DD HH:MM:SS') and ISO times, as UTC datetimes."""
    when = datetime.fromisoformat(text.replace(" ", "T"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def strategy_stats(folder, cost_pct, day, entered=None):
    """Numbers for one strategy. `day` is 'YYYY-MM-DD' (UTC). `entered` is an
    optional (since, until) pair of datetimes (either can be None): only
    positions bought in that time are counted."""
    rows, state = _read(folder)
    if entered:
        since, until = entered

        def keep(when):
            return (since is None or when >= since) and (until is None or when < until)
        bought = {r["token_address"] for r in rows
                  if r["action"] == "BUY" and keep(_when(r["time_utc"]))}
        rows = [r for r in rows if r["token_address"] in bought]
        state = dict(state, open_positions=[p for p in state.get("open_positions", [])
                                            if keep(_when(p["entry_time"]))])
    open_now = {p["address"] for p in state.get("open_positions", [])}

    # A position = every SELL row for that token (rebuys are off by default).
    pnl, last_sell = defaultdict(float), {}
    for r in rows:
        if r["action"] == "SELL":
            pnl[r["token_address"]] += float(r["pnl_usd"])
            last_sell[r["token_address"]] = r["time_utc"]
    closed = {a: p for a, p in pnl.items() if a not in open_now}
    closed_today = {a: p for a, p in closed.items() if last_sell[a].startswith(day)}
    wins = [p for p in closed.values() if p > 0]
    losses = [p for p in closed.values() if p <= 0]

    unrealized = 0.0
    for pos in state.get("open_positions", []):
        left = pos["remaining_fraction"]
        value = pos["tokens"] * left * pos["last_price"]
        cost = pos["cost_usd"] * left
        unrealized += value - cost - cost * cost_pct / 100
    realized = sum(float(r["pnl_usd"]) for r in rows if r["action"] == "SELL")

    return {
        "buys_today": sum(1 for r in rows if r["action"] == "BUY" and r["time_utc"].startswith(day)),
        "closed_today": len(closed_today),
        "wins_today": sum(1 for p in closed_today.values() if p > 0),
        "losses_today": sum(1 for p in closed_today.values() if p <= 0),
        "realized_today": sum(float(r["pnl_usd"]) for r in rows
                              if r["action"] == "SELL" and r["time_utc"].startswith(day)),
        "closed": len(closed),
        "wins": len(wins),
        "win_rate": len(wins) / len(closed) * 100 if closed else None,
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "best": max(closed.values()) if closed else None,
        "worst": min(closed.values()) if closed else None,
        "realized": realized,
        "open": len(open_now),
        "unrealized": unrealized,
        "total": realized + unrealized,
    }


def _usd(x):
    return "–" if x is None else f"${x:+.2f}"


def schedule_split(path):
    """(time of the latest schedule change, interval before, interval after)
    from data/schedule.json, or None if there hasn't been a change."""
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        history = json.load(fh).get("history") or []
    if len(history) < 2:
        return None
    return _when(history[-1]["since"]), history[-2]["every_minutes"], history[-1]["every_minutes"]


def actual_intervals(schedule_path, count_runs, now):
    """The real average minutes between runs before and after the latest
    schedule change: the period's length divided by the number of runs
    started in it (scheduled by GitHub or started by the server's trigger).
    `count_runs(start, end)` asks GitHub."""
    if not os.path.exists(schedule_path):
        return {}
    with open(schedule_path) as fh:
        history = json.load(fh).get("history") or []
    if len(history) < 2:
        return {}
    spans = {"before": (_when(history[-2]["since"]), _when(history[-1]["since"])),
             "after": (_when(history[-1]["since"]), now)}
    out = {}
    for key, (start, end) in spans.items():
        n = count_runs(start, end)
        if n:
            out[key] = (end - start).total_seconds() / 60 / n
    return out


def schedule_lines(strategies, schedule_path, actual=None):
    """All-time results before and after the latest schedule change, per
    strategy, grouped by when each position was bought. `actual` holds the
    real average minutes between runs ("before"/"after"), when known."""
    split = schedule_split(schedule_path)
    if not split:
        return ["**Before / after the schedule change:** no change recorded yet."]
    when, before, after = split
    actual = actual or {}

    def label(every, key):
        real = actual.get(key)
        return (f"every {every:g} min (actually ~{real:.0f})" if real
                else f"every {every:g} min")

    cols = []
    for name, folder, cost in strategies:
        cols.append((f"{name}, {label(before, 'before')}",
                     strategy_stats(folder, cost, "", entered=(None, when))))
        cols.append((f"{name}, {label(after, 'after')}",
                     strategy_stats(folder, cost, "", entered=(when, None))))

    def row(label, fn):
        return f"| {label} | " + " | ".join(fn(s) for _, s in cols) + " |"

    def rate(s):
        return "–" if s["win_rate"] is None else f"{s['win_rate']:.0f}% ({s['wins']} of {s['closed']})"

    return [
        f"**Before / after the schedule change** (scheduled {label(before, 'before')} "
        f"until {when:%Y-%m-%d %H:%M} UTC, {label(after, 'after')} since; "
        + ("the real average time between runs comes from GitHub's run history; "
           if actual else "real intervals not checked (no GitHub token); ")
        + "positions grouped by when they were bought, all time)",
        "",
        "| | " + " | ".join(label for label, _ in cols) + " |",
        "|---|" + "---|" * len(cols),
        row("Paper buys", lambda s: str(s["closed"] + s["open"])),
        row("Positions closed", lambda s: str(s["closed"])),
        row("Win rate", rate),
        row("Average win / loss", lambda s: f"{_usd(s['avg_win'])} / {_usd(s['avg_loss'])}"),
        row("Realized P&L", lambda s: _usd(s["realized"])),
        row("Open positions (unrealized P&L)",
            lambda s: f"{s['open']} ({_usd(s['unrealized'])})"),
        row("**Total P&L**", lambda s: f"**{_usd(s['total'])}**"),
    ]


def helius_lines(folder, day):
    """Helius credit use of the convergence strategy, from its positions.json."""
    path = os.path.join(folder, "positions.json")
    if not os.path.exists(path):
        return ["**Helius credits (convergence):** no data yet."]
    with open(path) as fh:
        state = json.load(fh)
    m = state.get("helius")
    if not m:
        return ["**Helius credits (convergence):** not used yet "
                "(is the HELIUS_API_KEY secret set?)."]
    pct = m["used"] / m["monthly"] * 100
    paused = state.get("paused_until")
    status = (f"**paused** until {paused[:10]} (would pass {m['pause_at_pct']:g}%)"
              if paused else "active")
    return [
        "**Helius credits (convergence)**",
        "",
        "| | |",
        "|---|---|",
        f"| Used on {day} | {m['by_day'].get(day, 0):,} |",
        f"| Used this cycle (since {m['cycle_start'][:10]}) | {m['used']:,} of "
        f"{m['monthly']:,} ({pct:.1f}%) |",
        f"| Pauses at | {m['cap']:,} ({m['pause_at_pct']:g}%) |",
        f"| Cycle resets | {m['cycle_end'][:10]} |",
        f"| Status | {status} |",
        f"| Wallets tracked | {len(state.get('tracked') or [])} |",
    ]


def slippage_lines(strategies):
    """Which strategies' paper buys pay extra over the market price (their
    positions.json "buy_slippage": the % and since when), for under the table."""
    groups = {}
    for name, folder, _ in strategies:
        path = os.path.join(folder, "positions.json")
        try:
            with open(path) as fh:
                slip = json.load(fh).get("buy_slippage")
        except (OSError, ValueError):
            slip = None
        if slip and slip.get("pct"):
            since = _when(slip["since"]).strftime("%Y-%m-%d %H:%M")
            groups.setdefault((slip["pct"], since), []).append(name)
    if not groups:
        return []
    parts = [f"+{pct:g}% for {', '.join(names)} (since {since} UTC)"
             for (pct, since), names in sorted(groups.items(), key=lambda g: g[0][1])]
    return [f"**Buy slippage:** paper buys pay extra over the market price, for a person's "
            f"reaction time: {'; '.join(parts)}. Their results include it from then on; "
            f"buys before that date were made at the market price.", ""]


def report(strategies, day, extra=None, health=None):
    """Markdown table. `strategies` is a list of (name, folder, round_trip_cost_pct).
    `extra` is more Markdown lines to add at the end, `health` lines to put
    at the top (see screener/health.py)."""
    stats = {name: strategy_stats(folder, cost, day) for name, folder, cost in strategies}
    names = list(stats)

    def row(label, fn):
        return f"| {label} | " + " | ".join(fn(stats[n]) for n in names) + " |"

    def rate(s):
        if s["win_rate"] is None:
            return "–"
        return f"{s['win_rate']:.0f}% ({s['wins']} of {s['closed']})"

    lines = [
        MARKER.format(day),
        f"## Paper strategy comparison: {day} (UTC)",
        "",
        *(health or []),
        "| | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
        f"| **{day}** | " + " | ".join("" for _ in names) + " |",
        row("Paper buys", lambda s: str(s["buys_today"])),
        row("Positions closed", lambda s: str(s["closed_today"])),
        row("Wins / losses", lambda s: f"{s['wins_today']} / {s['losses_today']}"),
        row("Realized P&L", lambda s: _usd(s["realized_today"])),
        "| **All time** | " + " | ".join("" for _ in names) + " |",
        row("Positions closed", lambda s: str(s["closed"])),
        row("Win rate", rate),
        row("Average win / loss", lambda s: f"{_usd(s['avg_win'])} / {_usd(s['avg_loss'])}"),
        row("Best / worst trade", lambda s: f"{_usd(s['best'])} / {_usd(s['worst'])}"),
        row("Realized P&L", lambda s: _usd(s["realized"])),
        row("Open positions (unrealized P&L)",
            lambda s: f"{s['open']} ({_usd(s['unrealized'])})"),
        row("**Total P&L**", lambda s: f"**{_usd(s['total'])}**"),
        "",
        *slippage_lines(strategies),
    ]
    if extra:
        lines += list(extra) + [""]
    lines += [
        "_Paper trading only ($10 per pretend buy, $5 for convergence). Fees and "
        "slippage assumed per full "
        "trade: " + ", ".join(f"{n} {c:g}%" for n, _, c in strategies) + ". Unrealized "
        "P&L uses the last price the bot saw. A handful of trades says little; judge "
        "the strategies over weeks, not days._",
    ]
    return "\n".join(lines)
