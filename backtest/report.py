"""Writes the results to a folder: numbers (json, csv) and SUMMARY.md, whose
sentences are produced from the numbers by the rules below, so it cannot say
anything the numbers do not show."""

import csv
import json
import os


def pct(x, signed=True):
    if x is None:
        return "n/a"
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def num(x, digits=2):
    return "n/a" if x is None else f"{x:.{digits}f}"


def factor(m):
    return "no losing trades" if m["profit_factor"] is None and m["trades"] else num(m["profit_factor"])


def _row(g, bh, extra=None):
    m = g["metrics"]
    row = {"family": g["family"], "variant": g["name"], "trades": m["trades"],
           "win_rate": m["win_rate"], "profit_factor": m["profit_factor"],
           "total_return": m["total_return"], "max_drawdown": m["max_drawdown"],
           "sharpe": m["sharpe"], "buy_and_hold_return": bh["total_return"],
           "excess_return_vs_buy_and_hold": g["excess_return"],
           "t_stat_of_that_gap": g.get("excess_t_stat"),
           "total_return_without_best_trade": m["total_return_without_best_1"],
           "total_return_without_best_3_trades": m["total_return_without_best_3"],
           "time_in_market": m["time_in_market"]}
    row.update(extra or {})
    return row


def _write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def verdicts(results):
    """The plain-language findings, each computed from the numbers."""
    proto = results["protocol"]
    bh = results["test"]["benchmark"]
    test = results["test"]["strategies"]
    window = f"{proto['test_window'][0]} to {proto['test_window'][1]}"
    lines = []
    beat = [s for s in test if s["beats_buy_and_hold_on_return"]]
    if not beat:
        lines.append(f"**Nothing beat buy-and-hold on total return after costs** in {window}: "
                     f"buy-and-hold of the same coins made {pct(bh['total_return'])}; the best "
                     f"strategy made {pct(max(s['metrics']['total_return'] for s in test))}.")
    else:
        lines.append("Beat buy-and-hold on total return after costs in " + window + " (buy-and-hold "
                     f"{pct(bh['total_return'])}): " + "; ".join(
                         f"{s['family']} ({pct(s['metrics']['total_return'])})" for s in beat) + ".")
        unsure = [s for s in beat if s.get("excess_t_stat") is None or abs(s["excess_t_stat"]) < 2]
        if unsure:
            lines.append("But for " + "; ".join(f"{s['family']} (t = {num(s.get('excess_t_stat'))})" for s in unsure)
                         + " the gap to buy-and-hold is not clearly bigger than luck could produce (t below 2).")
    better_sharpe = [s for s in test if s["beats_buy_and_hold_on_sharpe"]]
    if better_sharpe:
        lines.append(f"Higher return per unit of risk (Sharpe ratio) than buy-and-hold ({num(bh['sharpe'])}): "
                     + "; ".join(f"{s['family']} ({num(s['metrics']['sharpe'])})" for s in better_sharpe) + ".")
    else:
        lines.append(f"None had a higher Sharpe ratio than buy-and-hold ({num(bh['sharpe'])}).")
    calmer = [s for s in test if s["smaller_drawdown_than_buy_and_hold"]]
    if calmer:
        lines.append(f"Smaller worst fall than buy-and-hold ({pct(bh['max_drawdown'])}): " + "; ".join(
            f"{s['family']} ({pct(s['metrics']['max_drawdown'])}, return "
            f"{pct(s['metrics']['total_return'])})" for s in calmer) + ".")
    else:
        lines.append(f"None had a smaller worst fall than buy-and-hold ({pct(bh['max_drawdown'])}).")
    only_tuning = [s for s in test if s["tuning_beats_buy_and_hold_on_return"] and not s["beats_buy_and_hold_on_return"]]
    only_test = [s for s in test if not s["tuning_beats_buy_and_hold_on_return"] and s["beats_buy_and_hold_on_return"]]
    if only_tuning:
        lines.append("**Worked only in the tuning period** (beat buy-and-hold in 2020-2023 but not after): "
                     + "; ".join(s["family"] for s in only_tuning) + ".")
    if only_test:
        lines.append("Beat buy-and-hold only in the test period, not in 2020-2023: "
                     + "; ".join(s["family"] for s in only_test) + ".")
    fragile = [s for s in test if s["metrics"]["total_return"] > 0 and s["metrics"]["total_return_without_best_1"] <= 0]
    if fragile:
        lines.append("Depended on one trade (the return is zero or negative without the best trade): "
                     + "; ".join(s["family"] for s in fragile) + ".")
    thin = [s for s in test if s["metrics"]["trades"] < 30]
    if thin:
        lines.append("Fewer than 30 trades in the test period, too few to say much: "
                     + "; ".join(f"{s['family']} ({s['metrics']['trades']})" for s in thin) + ".")
    return lines


def summary(results, data_rows, info):
    proto = results["protocol"]
    bh_t, bh_x = results["tuning"]["benchmark"], results["test"]["benchmark"]
    test = results["test"]["strategies"]
    out = []
    w = out.append
    w("# Backtest summary")
    w("")
    w(f"Made {info['made_at']} from Binance spot prices (USDT pairs) up to {proto['test_window'][1]}, "
      f"for {len(proto['coins'])} coins. History only: nothing here trades, and no wallet or key is used.")
    w("")
    w("## The short answer")
    w("")
    for line in verdicts(results):
        w(f"- {line}")
    w("")
    w("## How it was tested (so you can judge it)")
    w("")
    w(f"- **Coins:** {', '.join(proto['coins'])}. Hourly and daily candles from data.binance.vision, as far back as "
      "the archive goes. Newer coins (SUI, ONDO, TAO) have only a short history.")
    w(f"- **Costs:** {info['fee_per_side'] * 100:.2f}% fee per side, plus slippage per side of "
      f"{info['slippage_majors'] * 100:.2f}% for {', '.join(info['majors'])} and {info['slippage_others'] * 100:.2f}% for the "
      "others. A stop that is hit by a gap fills at the next candle's open, never at the stop price.")
    w("- **No peeking:** a decision is made at a daily close and filled at the next open. Long only, no leverage.")
    w(f"- **Tuning period {proto['tuning_window'][0]} to {proto['tuning_window'][1]}:** "
      f"{proto['variants_tried']} variants were tried (3 trend, 4 breakout, 2 momentum, 4 mean-reversion). For each family "
      f"the one with the {proto['selection_rule']} was chosen. Candles after the end of this period were not loaded.")
    w(f"- **Test period {proto['test_window'][0]} to {proto['test_window'][1]}:** only the four chosen variants and "
      f"buy-and-hold were run, once ({proto['test_evaluations_of_the_chosen_variants']} runs). Nothing was changed afterwards.")
    w("- **Portfolio:** the money is split equally between the coins that have 200 days of history; each share is invested "
      "while its rule says so and is cash otherwise (momentum: three equal slots). Moving money between shares is free for "
      "the strategies and for buy-and-hold alike.")
    w("")
    w(f"## Test period results ({proto['test_window'][0]} to {proto['test_window'][1]}, run once)")
    w("")
    w("| Strategy (chosen in 2020-2023) | Trades | Win rate | Profit factor | Total return | Worst fall | "
      "Return minus buy-and-hold (points) | t-stat of that gap | Return without best trade | Without best 3 |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for s in test:
        m = s["metrics"]
        w(f"| **{s['family']}**: {s['name']} | {m['trades']} | {pct(m['win_rate'], False)} | {factor(m)} | "
          f"{pct(m['total_return'])} | {pct(m['max_drawdown'])} | {pct(s['excess_return'])} | "
          f"{num(s.get('excess_t_stat'))} | {pct(m['total_return_without_best_1'])} | "
          f"{pct(m['total_return_without_best_3'])} |")
    w(f"| **buy-and-hold** of the same coins (each coin is one \"trade\") | {bh_x['trades']} | – | – | "
      f"{pct(bh_x['total_return'])} | {pct(bh_x['max_drawdown'])} | – | – | {pct(bh_x['total_return_without_best_1'])} "
      f"(best coin removed) | {pct(bh_x['total_return_without_best_3'])} |")
    w("")
    w("The t-stat is the average daily gap to buy-and-hold divided by its standard error: below about 2 in size, a gap "
      "this big could easily be luck.")
    w("")
    w("Each row's trades are round trips in one coin; the win rate and profit factor count them after costs. "
      "\"Without best trade\" removes the one trade that added most to the portfolio and recomputes the total return.")
    w("")
    w("## The same strategies in the tuning period (2020-2023)")
    w("")
    w("| Strategy | Total return | Buy-and-hold | Worst fall | Sharpe | Trades |")
    w("|---|---|---|---|---|---|")
    for s in test:
        m = s["tuning_metrics"]
        w(f"| {s['family']}: {s['name']} | {pct(m['total_return'])} | {pct(bh_t['total_return'])} | "
          f"{pct(m['max_drawdown'])} | {num(m['sharpe'])} | {m['trades']} |")
    w(f"| buy-and-hold | {pct(bh_t['total_return'])} | – | {pct(bh_t['max_drawdown'])} | {num(bh_t['sharpe'])} | – |")
    w("")
    w("## Every variant tried in 2020-2023")
    w("")
    w("| Family | Variant | Chosen | Total return | Worst fall | Sharpe | Trades | Win rate |")
    w("|---|---|---|---|---|---|---|---|")
    for g in results["tuning"]["variants"]:
        m = g["metrics"]
        chosen = "yes" if results["selection"][g["family"]] == g["name"] else ""
        w(f"| {g['family']} | {g['name']} | {chosen} | {pct(m['total_return'])} | {pct(m['max_drawdown'])} | "
          f"{num(m['sharpe'])} | {m['trades']} | {pct(m['win_rate'], False)} |")
    w("")
    w("## Calendar years (the chosen strategies; buy-and-hold in the last row)")
    w("")
    years = sorted({y for s in test for y in list(s["tuning_metrics"]["yearly"]) + list(s["metrics"]["yearly"])}
                   | set(bh_t["yearly"]) | set(bh_x["yearly"]), key=int)

    def cell(per, y):
        return pct(per[y]) if y in per else "–"

    w("| Strategy | " + " | ".join(str(y) for y in years) + " |")
    w("|---|" + "---|" * len(years))
    for s in test:
        merged = {**s["tuning_metrics"]["yearly"], **s["metrics"]["yearly"]}
        w(f"| {s['family']} | " + " | ".join(cell(merged, y) for y in years) + " |")
    merged = {**bh_t["yearly"], **bh_x["yearly"]}
    w("| buy-and-hold | " + " | ".join(cell(merged, y) for y in years) + " |")
    w("")
    w("2020-2023 years come from the tuning run, 2024 onward from the single test run.")
    w("")
    w("## Limits you should keep in mind")
    w("")
    w("- **Survivorship bias.** The coins were picked by hand and all still trade and are liquid today, including the "
      "newer SUI, ONDO and TAO; coins that collapsed or were delisted (LUNA, FTT and others) are absent. This flatters "
      "every long-only result, buy-and-hold included.")
    w("- **A short test.** The test period is a few years of one market; a difference of a few percentage points over a period "
      "this short should not be treated as real.")
    w("- **Prices are Binance USDT pairs**, not dollars, and fills are simulated: real orders in a fast market can fill "
      "worse than the slippage assumed here.")
    w("- **Daily candles for decisions**, hourly candles only to decide where a stop fills. Rules were fixed in advance; "
      "13 variants were tried in the tuning period, and picking the best of 13 still flatters the tuning result.")
    w("- **No tax, no funding of any kind, no cash interest.**")
    w("")
    return "\n".join(out)


def write_outputs(results, data_rows, info, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    tune_bh = results["tuning"]["benchmark"]
    test_bh = results["test"]["benchmark"]
    _write_csv(os.path.join(out_dir, "tuning_grid.csv"), [
        _row(g, tune_bh, {"chosen": "yes" if results["selection"][g["family"]] == g["name"] else ""})
        for g in results["tuning"]["variants"]])
    _write_csv(os.path.join(out_dir, "test_results.csv"), [
        _row(s, test_bh, {"tuning_total_return": s["tuning_metrics"]["total_return"],
                          "tuning_sharpe": s["tuning_metrics"]["sharpe"],
                          "beats_buy_and_hold_on_return": s["beats_buy_and_hold_on_return"],
                          "smaller_drawdown_than_buy_and_hold": s["smaller_drawdown_than_buy_and_hold"]})
        for s in results["test"]["strategies"]])
    _write_csv(os.path.join(out_dir, "trades_test.csv"), results["trades"]["test"])
    _write_csv(os.path.join(out_dir, "trades_tuning.csv"), results["trades"]["tuning"])
    _write_csv(os.path.join(out_dir, "data_report.csv"), data_rows)
    with open(os.path.join(out_dir, "results.json"), "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    with open(os.path.join(out_dir, "run_info.json"), "w") as fh:
        json.dump(info, fh, indent=1)
    with open(os.path.join(out_dir, "SUMMARY.md"), "w") as fh:
        fh.write(summary(results, data_rows, info))
