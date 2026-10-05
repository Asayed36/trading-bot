"""Pretend trading. No real money, no wallet, no orders - just arithmetic.

Open positions are saved in data/positions.json so they survive between runs.
Every pretend buy and sell is added as a row to data/journal.csv, which you
can open in Excel, Google Sheets or Numbers.
"""

import csv
import json
import os
from datetime import datetime, timezone

from screener.filters import to_float
from screener.jupiter import COLUMNS as JUPITER_COLUMNS

JOURNAL_COLUMNS = [
    "time_utc", "action", "symbol", "token_address", "reason", "price_usd",
    "usd_amount", "pnl_usd", "pnl_pct", "running_total_pnl_usd",
]

# entries.csv: one row per paper buy with what the market looked like at that
# moment, for later analysis. Rows are only ever added, never removed.
# price_change_5m_pct / price_change_1h_pct are DexScreener's price change over
# the last 5 minutes / hour at the moment of the buy. The jupiter_* columns
# are Jupiter's organic score at the buy (screener/jupiter.py; logging only,
# blank when unknown or for non-Solana coins).
ENTRY_COLUMNS = [
    "time_utc", "symbol", "token_address", "price_usd", "buys_1h", "sells_1h",
    "insider_flagged", "insider_networks", "insider_linked_wallets", "insider_top_holders",
    "price_change_5m_pct", "price_change_1h_pct", *JUPITER_COLUMNS,
]


def pct(value):
    """A percentage for a CSV cell; blank when it isn't known."""
    value = to_float(value)
    return "" if value is None else f"{value:g}"


def append_row(path, columns, row):
    """Add one row to a CSV file. If the file was written with fewer columns
    (before a column was added), it's rewritten with the new header first,
    leaving the new columns blank in the old rows."""
    if os.path.exists(path):
        with open(path, newline="") as fh:
            header = next(csv.reader(fh), None)
        if header != columns:
            with open(path, newline="") as fh:
                old = list(csv.DictReader(fh))
            tmp = path + ".tmp"
            with open(tmp, "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(old)
            os.replace(tmp, path)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(columns)
        writer.writerow(row)


def now_utc():
    return datetime.now(timezone.utc)


class PaperTrader:
    # Optional: a callable mint -> Jupiter organic-score values, saved in
    # entries.csv at each buy (screener/jupiter.JupiterOrganic). None = blank.
    organic = None

    def __init__(self, cfg, data_folder):
        self.cfg = cfg
        os.makedirs(data_folder, exist_ok=True)
        self.state_path = os.path.join(data_folder, "positions.json")
        self.journal_path = os.path.join(data_folder, "journal.csv")
        self.entries_path = os.path.join(data_folder, "entries.csv")
        self.state = self._load()
        # False for a stopped strategy: no new buys, while the positions it
        # still holds finish under their normal exits.
        self.buying = True

    # ---- saving & loading ----

    def _load(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as fh:
                return json.load(fh)
        return {"open_positions": [], "ever_bought": [], "running_total_pnl_usd": 0.0}

    def save(self):
        with open(self.state_path, "w") as fh:
            json.dump(self.state, fh, indent=2)

    def _journal(self, when, action, pos, reason, price, usd_amount, pnl_usd=0.0, pnl_pct=0.0):
        new_file = not os.path.exists(self.journal_path)
        with open(self.journal_path, "a", newline="") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(JOURNAL_COLUMNS)
            writer.writerow([
                when.strftime("%Y-%m-%d %H:%M:%S"), action, pos["symbol"], pos["address"],
                reason, f"{price:.10g}", f"{usd_amount:.2f}", f"{pnl_usd:.2f}",
                f"{pnl_pct:.1f}", f"{self.state['running_total_pnl_usd']:.2f}",
            ])

    # ---- buying ----

    @property
    def open_positions(self):
        return self.state["open_positions"]

    def position(self, address):
        """The open position in this token, or None."""
        return next((p for p in self.open_positions if p["address"] == address), None)

    def can_buy(self, address):
        if not self.buying:
            return False
        if any(p["address"] == address for p in self.open_positions):
            return False
        if not self.cfg["allow_rebuy"] and address in self.state["ever_bought"]:
            return False
        return True

    def buy(self, result, when=None):
        """Record a pretend buy. Returns the new position, or None if skipped."""
        when = when or now_utc()
        price = result.price
        if not price or price <= 0 or not self.can_buy(result.address):
            return None
        cost = float(self.cfg["buy_amount_usd"])
        pos = {
            "address": result.address,
            "symbol": result.symbol,
            "pair_address": (result.pair or {}).get("pairAddress"),
            "entry_time": when.isoformat(),
            "entry_price": price,
            "peak_price": price,
            "tokens": cost / price,
            "cost_usd": cost,
            "remaining_fraction": 1.0,
            "took_profit": False,
            "last_price": price,
        }
        self.open_positions.append(pos)
        self.state["ever_bought"].append(result.address)
        self._journal(when, "BUY", pos, "passed all filters", price, cost)
        self._entry(when, pos, result)
        return pos

    def _entry(self, when, pos, result):
        """Save buys vs sells over the last hour, insider-network status,
        DexScreener's 5-minute and 1-hour price change and Jupiter's organic
        score at the moment of the buy. Blank means the data wasn't available."""
        tx = ((result.pair or {}).get("txns") or {}).get("h1") or {}
        change = (result.pair or {}).get("priceChange") or {}
        ins = getattr(result, "insider", None)
        if ins is None:
            flagged = "unknown"
        else:
            flagged = "yes" if any(ins.get(k) for k in ins) else "no"
        jup = self.organic(pos["address"]) if self.organic else {}
        append_row(self.entries_path, ENTRY_COLUMNS, [
            when.strftime("%Y-%m-%d %H:%M:%S"), pos["symbol"], pos["address"],
            f"{pos['entry_price']:.10g}",
            "" if tx.get("buys") is None else tx["buys"],
            "" if tx.get("sells") is None else tx["sells"],
            flagged,
            *(("", "", "") if ins is None else
              (ins["networks"], ins["linked_wallets"], ins["insider_top_holders"])),
            pct(change.get("m5")), pct(change.get("h1")),
            *("" if jup.get(k) is None else jup[k] for k in JUPITER_COLUMNS),
        ])

    # ---- selling ----

    def _sell(self, pos, fraction, price, reason, when):
        """Sell `fraction` of the ORIGINAL position (0.5 = half of it)."""
        fraction = min(fraction, pos["remaining_fraction"])
        cost = pos["cost_usd"] * fraction
        proceeds = pos["tokens"] * fraction * price
        fees = cost * self.cfg["round_trip_cost_pct"] / 100
        pnl = proceeds - cost - fees
        pos["remaining_fraction"] = round(pos["remaining_fraction"] - fraction, 10)
        self.state["running_total_pnl_usd"] += pnl
        self._journal(when, "SELL", pos, reason, price, proceeds - fees, pnl, pnl / cost * 100)
        pos.setdefault("sells", []).append({
            "time": when.isoformat(), "fraction": fraction, "price": price,
            "reason": reason, "proceeds_usd": proceeds - fees, "pnl_usd": pnl,
        })
        return {"symbol": pos["symbol"], "reason": reason, "pnl_usd": pnl,
                "closed": pos["remaining_fraction"] <= 0, "position": pos}

    def close_reason(self, pos, change_pct, from_peak, hours):
        """Why to sell everything that's left, or None to keep holding."""
        c = self.cfg
        if change_pct <= -c["stop_loss_pct"]:
            return f"stop loss: down {-change_pct:.0f}% from entry"
        if from_peak <= -c["trailing_stop_pct"]:
            return f"trailing stop: down {-from_peak:.0f}% from peak"
        if hours >= c["max_hold_hours"] and abs(change_pct) < c["stale_move_pct"]:
            return f"time exit: {hours:.0f}h held, only {change_pct:+.1f}% move"
        return None

    def update(self, prices, when=None):
        """Check every open position against the exit rules.

        `prices` maps token address -> current USD price.
        Returns a list of the sells that happened.
        """
        when = when or now_utc()
        c = self.cfg
        sells = []
        for pos in list(self.open_positions):
            price = prices.get(pos["address"])
            if not price:
                continue  # no price this run; try again next time
            pos["last_price"] = price
            pos["peak_price"] = max(pos["peak_price"], price)
            entry = pos["entry_price"]
            change_pct = (price / entry - 1) * 100

            # Rule 1: up enough -> sell half, let the rest ride.
            if not pos["took_profit"] and change_pct >= c["take_profit_pct"]:
                pos["took_profit"] = True
                sells.append(self._sell(pos, c["take_profit_sell_fraction"], price,
                                        f"take profit: up {change_pct:.0f}%", when))

            # Rules 2-4: close whatever is left.
            if pos["remaining_fraction"] > 0:
                hours = (when - datetime.fromisoformat(pos["entry_time"])).total_seconds() / 3600
                from_peak = (price / pos["peak_price"] - 1) * 100
                reason = self.close_reason(pos, change_pct, from_peak, hours)
                if reason:
                    sells.append(self._sell(pos, pos["remaining_fraction"], price, reason, when))

            if pos["remaining_fraction"] <= 0:
                self.open_positions.remove(pos)
        return sells
