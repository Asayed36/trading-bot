"""The test protocol, in one place.

1. Every variant (13 of them, see strategies.py) is run on 2020-01-01 to
   2023-12-31 only. Candles after 2023-12-31 are cut off BEFORE this step, so
   nothing from the later years can influence it.
2. For each family, the variant with the best Sharpe ratio in that period is
   chosen (ties: fewer trades, then name). The choice is written down.
3. Only those chosen variants (and buy-and-hold) are run on 2024-01-01 to the
   last day available. Exactly once. Nothing is changed afterwards.
"""

import argparse
import subprocess
import sys
from datetime import date, datetime, timezone

from . import data, strategies, universe
from .portfolio import Run, measure, paired_t, run_strategy, trade_rows
from .report import write_outputs

TUNE_START, TUNE_END = date(2020, 1, 1), date(2023, 12, 31)
TEST_START = date(2024, 1, 1)
SELECTION_RULE = "highest Sharpe ratio of the daily portfolio returns in 2020-2023 " \
                 "(ties: fewer trades, then name)"


class Variant:
    def __init__(self, family, name, make, slots=None, positive_only=None):
        self.family, self.name, self.make = family, name, make
        self.slots, self.positive_only = slots, positive_only

    def builder(self, coins):
        """build(coin) -> a fresh strategy, for this set of coins."""
        if self.positive_only is None:
            return lambda coin: self.make()
        schedules = strategies.momentum_schedules(coins, self.positive_only)
        return lambda coin: strategies.Scheduled(self.name, schedules[coin.label])


def all_variants():
    out = []
    for family, makers in strategies.families().items():
        for make in makers:
            out.append(Variant(family, make().name, make))
    for name, positive_only in strategies.MOMENTUM_VARIANTS:
        out.append(Variant("momentum", name, None, slots=strategies.MOMENTUM_TOP,
                           positive_only=positive_only))
    return out


def evaluate(coins, variant, start, end):
    sleeves = run_strategy(coins, variant.builder(coins), start, end)
    run = Run(sleeves, slots=variant.slots)
    return run, measure(run)


def benchmark(coins, start, end):
    sleeves = run_strategy(coins, lambda coin: strategies.BuyHold(), start, end)
    run = Run(sleeves)
    return run, measure(run)


def compare(m, bh, t_stat=None):
    """How a result stands against buy-and-hold over the same days."""
    return {"excess_return": m["total_return"] - bh["total_return"],
            "excess_t_stat": t_stat,
            "beats_buy_and_hold_on_return": m["total_return"] > bh["total_return"],
            "beats_buy_and_hold_on_sharpe": m["sharpe"] > bh["sharpe"],
            "smaller_drawdown_than_buy_and_hold": m["max_drawdown"] > bh["max_drawdown"]}


def choose(rows):
    return min(rows, key=lambda r: (-r["metrics"]["sharpe"], r["metrics"]["trades"], r["name"]))


def run_protocol(coins, log=print, tune_end=TUNE_END, test_start=TEST_START):
    """Runs the whole protocol on the given coins (a list of CoinData)."""
    variants = all_variants()
    last_day = max(date.fromordinal(data.EPOCH_ORDINAL + c.day[-1]) for c in coins)

    # ---- 1. tuning: the later years are not even in memory
    tuning_coins = [c.truncate(tune_end) for c in coins]
    tuning_coins = [c for c in tuning_coins if len(c) > strategies.WARMUP_DAYS]
    log(f"tuning on {TUNE_START} to {tune_end}: {len(tuning_coins)} coins, {len(variants)} variants")
    bh_run, bh_tuning = benchmark(tuning_coins, TUNE_START, tune_end)
    grid = []
    for v in variants:
        run, m = evaluate(tuning_coins, v, TUNE_START, tune_end)
        grid.append({"family": v.family, "name": v.name, "metrics": m,
                     **compare(m, bh_tuning, paired_t(run, bh_run))})
        log(f"  {v.family:16} {v.name:50} return {m['total_return']:+8.1%}  sharpe {m['sharpe']:5.2f}  trades {m['trades']}")

    # ---- 2. the choice, written down before the test period is touched
    selection = {}
    for family in dict.fromkeys(v.family for v in variants):
        selection[family] = choose([g for g in grid if g["family"] == family])["name"]
    log("chosen on 2020-2023: " + "; ".join(f"{f}: {n}" for f, n in selection.items()))

    # ---- 3. the test period, once
    test_end = last_day
    log(f"test on {test_start} to {test_end}: each chosen variant once")
    bh_test_run, bh_test = benchmark(coins, test_start, test_end)
    by_name = {(v.family, v.name): v for v in variants}
    test, trades_test, trades_tuning = [], [], []
    evaluations = 0
    for family, name in selection.items():
        v = by_name[(family, name)]
        run, m = evaluate(coins, v, test_start, test_end)
        evaluations += 1
        tuning_row = next(g for g in grid if g["family"] == family and g["name"] == name)
        test.append({"family": family, "name": name, "metrics": m,
                     **compare(m, bh_test, paired_t(run, bh_test_run)),
                     "tuning_metrics": tuning_row["metrics"],
                     "tuning_excess_return": tuning_row["excess_return"],
                     "tuning_beats_buy_and_hold_on_return": tuning_row["beats_buy_and_hold_on_return"]})
        trades_test += trade_rows(run, f"{family}: {name}")
        trun, _ = evaluate(tuning_coins, v, TUNE_START, tune_end)
        trades_tuning += trade_rows(trun, f"{family}: {name}")
        log(f"  {family:16} {name:50} return {m['total_return']:+8.1%}  (buy-and-hold {bh_test['total_return']:+.1%})")

    return {
        "protocol": {"tuning_window": [TUNE_START.isoformat(), tune_end.isoformat()],
                     "test_window": [test_start.isoformat(), test_end.isoformat()],
                     "selection_rule": SELECTION_RULE, "variants_tried": len(variants),
                     "test_evaluations_of_the_chosen_variants": evaluations,
                     "coins": [c.label for c in coins]},
        "tuning": {"benchmark": bh_tuning, "variants": grid},
        "selection": selection,
        "test": {"benchmark": bh_test, "strategies": test},
        "trades": {"tuning": trades_tuning, "test": trades_test},
    }


def data_report(coins):
    rows = []
    for c in coins:
        rows.append({"coin": c.label, "binance_symbols": "+".join(c.symbols),
                     "slippage_per_side": universe.slippage(c.label),
                     "first_day": c.date_of(0).isoformat(), "last_day": c.date_of(len(c) - 1).isoformat(),
                     **c.notes})
    return rows


def git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m backtest", description=__doc__.splitlines()[0])
    p.add_argument("--out", default="backtests", help="folder for the results")
    p.add_argument("--cache", default=None, help="folder for downloaded files")
    p.add_argument("--quick", action="store_true", help="only 4 coins (to try the tool)")
    p.add_argument("--offline", action="store_true", help="use only files already downloaded")
    p.add_argument("--today", default=None, help="YYYY-MM-DD (default: today, UTC)")
    args = p.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    labels = universe.QUICK if args.quick else tuple(universe.COINS)
    fetcher = data.Fetcher(args.cache, offline=args.offline)

    coins = []
    for label in labels:
        coin = data.load_coin(fetcher, label, universe.COINS[label], today)
        if coin is None:
            print(f"{label}: nothing in the archive, skipped")
            continue
        coins.append(coin)
        print(f"{label}: {coin.date_of(0)} to {coin.date_of(len(coin) - 1)}, "
              f"{len(coin)} days, {len(coin.h_open)} hours", flush=True)
    print(f"downloaded {fetcher.downloaded} new files")
    if not any(c.label == "BTC" for c in coins):
        print("no BTC data: cannot run")
        return 1

    results = run_protocol(coins, log=lambda s: print(s, flush=True))
    info = {"made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": git_sha(), "source": "https://data.binance.vision (Binance spot, USDT pairs)",
            "today_used": today.isoformat(), "quick": bool(args.quick),
            "fee_per_side": universe.FEE, "slippage_majors": universe.SLIPPAGE_MAJOR,
            "slippage_others": universe.SLIPPAGE_OTHER, "majors": list(universe.MAJORS)}
    write_outputs(results, data_report(coins), info, args.out)
    print(f"results written to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
