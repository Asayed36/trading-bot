"""The "liquid" paper strategy, run inside main (1 min) (main_1min.py, every minute).

ENTRY (the same for all four versions, [liquid] in config.toml): when a token gets its
first check (the minute its row is written to candidates.csv) and its pool holds at least
min_liquidity_usd of liquidity (DexScreener, the candidates.csv column liquidity_usd), each
version opens one paper buy of the [paper_trading] buy amount at the first-check price plus
buy_slippage_pct. Nothing else is checked: not main's filters, not RugCheck. A token with
no price or no liquidity value is skipped; a version never buys the same token twice.

EXITS (checked every minute, with the same prices main (1 min) reads for its open
positions), per version ([[liquid.versions]]): optionally sell part at +take_profit_pct,
then the rest when the price falls trailing_stop_pct below its peak SINCE that sale;
optionally a stop loss at -stop_loss_pct from the buy price; and everything
max_hold_minutes after the buy. Costs: round_trip_cost_pct over the whole trade, plus the
buy slippage.

PAPER TRADING ONLY: nothing here touches a wallet, a key or a real order.
"""

import os
from datetime import datetime

from screener.paper_trader import _iso
from screener.token_record import pair_facts

PRICE_KEYS = ("take_profit_pct", "take_profit_sell_fraction", "trailing_stop_pct",
              "stop_loss_pct", "max_hold_minutes")


class LiquidTrader:
    """Mixed into SafeTrader (main_1min.py) so a version saves exactly like the others.
    Only the exit rules and the buy's journal reason differ from main's PaperTrader."""

    buy_reason = "first check with enough liquidity"

    def update(self, prices, when=None, source=None, fetched_at=None):
        """Check every open position against this version's exits. Same arguments and
        result as PaperTrader.update."""
        from screener.paper_trader import now_utc
        when = when or now_utc()
        c = self.cfg
        sells = []
        for pos in list(self.open_positions):
            price = prices.get(pos["address"])
            if not price:
                continue                       # no price this run; try again next minute
            pos["last_price"] = price
            got = fetched_at.get(pos["address"]) if isinstance(fetched_at, dict) else fetched_at
            pos["last_price_source"] = source or self.price_source
            pos["last_price_time"] = _iso(got or when)
            pos["peak_price"] = max(pos["peak_price"], price)
            change_pct = (price / pos["entry_price"] - 1) * 100

            take = c.get("take_profit_pct")
            if take is not None and not pos["took_profit"] and change_pct >= take:
                pos["took_profit"] = True
                pos["peak_since_sale"] = price         # the trailing peak starts here
                sells.append(self._sell(pos, c["take_profit_sell_fraction"], price,
                                        f"take profit: up {change_pct:.0f}%", when))
            elif pos["took_profit"]:
                pos["peak_since_sale"] = max(pos.get("peak_since_sale", price), price)

            if pos["remaining_fraction"] > 0:
                reason = self.close_reason(pos, change_pct, price, when)
                if reason:
                    sells.append(self._sell(pos, pos["remaining_fraction"], price, reason, when))
            if pos["remaining_fraction"] <= 0:
                self.open_positions.remove(pos)
        return sells

    def close_reason(self, pos, change_pct, price, when):
        """Why to sell everything that's left, or None to keep holding."""
        c = self.cfg
        stop = c.get("stop_loss_pct")
        if stop is not None and change_pct <= -stop:
            return f"stop loss: down {-change_pct:.0f}% from entry"
        trail = c.get("trailing_stop_pct")
        if trail is not None and pos["took_profit"]:
            from_peak = (price / pos["peak_since_sale"] - 1) * 100
            if from_peak <= -trail:
                return f"trailing stop: down {-from_peak:.0f}% from the peak since the sale"
        minutes = (when - datetime.fromisoformat(pos["entry_time"])).total_seconds() / 60
        if minutes >= c["max_hold_minutes"]:
            return f"time exit: {minutes:.0f} min held ({change_pct:+.1f}%)"
        return None


class LiquidVersion:
    """One version ([[liquid.versions]]): its numbers and its own files."""

    def __init__(self, section, v, data_folder, buy_amount_usd):
        self.name = v["name"]
        self.label = v.get("label") or f"main (1 min) liquid {self.name}"
        self.folder = os.path.join(data_folder, v["folder"])
        self.stopped = bool(v.get("stopped"))
        # The settings a trader reads: the shared costs and buy amount plus this
        # version's exits.
        self.cfg = {"buy_amount_usd": buy_amount_usd,
                    "buy_slippage_pct": section["buy_slippage_pct"],
                    "round_trip_cost_pct": section["round_trip_cost_pct"],
                    "allow_rebuy": False,
                    **{k: v[k] for k in PRICE_KEYS if v.get(k) is not None}}
        if self.cfg.get("take_profit_pct") is not None and \
                self.cfg.get("take_profit_sell_fraction") is None:
            raise ValueError(f"liquid version {self.name}: take_profit_pct needs "
                             "take_profit_sell_fraction")
        if self.cfg.get("max_hold_minutes") is None:
            raise ValueError(f"liquid version {self.name}: max_hold_minutes is required")


def entry_problem(result, now, min_liquidity_usd):
    """None when a token's first check qualifies for the liquid buy, else why not."""
    if not result.price or result.price <= 0:
        return "no price"
    liquidity = pair_facts(result.pair, now)["liquidity_usd"]
    if liquidity is None:
        return "no liquidity value"
    if liquidity < min_liquidity_usd:
        return f"liquidity ${liquidity:,.0f} below ${min_liquidity_usd:,.0f}"
    return None
