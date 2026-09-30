"""Side-by-side results of the paper strategies, for one day and all time.

Reads each strategy's journal.csv and positions.json. Nothing here trades.
"""

import csv
import json
import os
from collections import defaultdict

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


def strategy_stats(folder, cost_pct, day):
    """Numbers for one strategy. `day` is 'YYYY-MM-DD' (UTC)."""
    rows, state = _read(folder)
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


def report(strategies, day):
    """Markdown table. `strategies` is a list of (name, folder, round_trip_cost_pct)."""
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
        "_Paper trading only, $10 per pretend buy. Fees and slippage assumed per full "
        "trade: " + ", ".join(f"{n} {c:g}%" for n, _, c in strategies) + ". Unrealized "
        "P&L uses the last price the bot saw. A handful of trades says little; judge "
        "the strategies over weeks, not days._",
    ]
    return "\n".join(lines)
