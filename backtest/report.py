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


# ---------------------------------------------------------------------
# The cycle filter, side by side with the unfiltered versions
# ---------------------------------------------------------------------

def _pairs(results):
    """[(label, tuning_twin, test_twin, plain_test_metrics, plain_tuning_metrics,
    filtered_test_metrics, filtered_tuning_metrics)] for each chosen strategy and buy-and-hold.
    The twin dicts hold return_difference, worst_fall_difference, trades_difference, t_stat."""
    keys = ("return_difference", "worst_fall_difference", "trades_difference", "t_stat")
    out = []
    for plain, filt in zip(results["test"]["strategies"], results["test"]["filtered"]):
        out.append((plain["family"],
                    {k: filt["tuning_vs_unfiltered"][k] for k in keys},
                    {k: filt[k] for k in keys},
                    plain["metrics"], plain["tuning_metrics"],
                    filt["metrics"], filt["tuning_metrics"]))
    t, x = results["tuning"], results["test"]
    out.append(("buy-and-hold",
                {k: t["filtered_benchmark_vs_unfiltered"][k] for k in keys},
                {k: x["filtered_benchmark_vs_unfiltered"][k] for k in keys},
                x["benchmark"], t["benchmark"], x["filtered_benchmark"], t["filtered_benchmark"]))
    return out


def _names(items):
    return ", ".join(items) if items else "none"


def cycle_verdicts(results):
    """The plain-language findings about the cycle filter, each computed from the numbers."""
    pairs = _pairs(results)
    tune_name = "2020-2023"
    test_name = "the test period"
    lines = []

    def classify(key, better):
        both, only_tune, only_test, neither = [], [], [], []
        for label, tw_tune, tw_test, *_ in pairs:
            a, b = better(tw_tune[key]), better(tw_test[key])
            (both if a and b else only_tune if a else only_test if b else neither).append(label)
        return both, only_tune, only_test, neither

    for key, what in (("return_difference", "a higher total return"),
                      ("worst_fall_difference", "a smaller worst fall")):
        both, only_tune, only_test, neither = classify(key, lambda v: v > 0)
        lines.append(f"With the filter, {what} in **both** periods: {_names(both)}. "
                     f"Only in {tune_name}: {_names(only_tune)}. Only in {test_name}: {_names(only_test)}. "
                     f"In neither: {_names(neither)}.")
    one_period = [label for label, a, b, *_ in pairs
                  if (a["return_difference"] > 0) != (b["return_difference"] > 0)]
    if one_period:
        lines.append("**The filter's return gain shows in only one of the two periods** for: "
                     + _names(one_period) + " (see the first line for which).")

    # luck: the rough paired t-stat of the daily growth difference
    luck, beyond, cost = [], [], []
    for label, tw_tune, tw_test, *_ in pairs:
        for period, tw in ((tune_name, tw_tune), (test_name, tw_test)):
            t = tw["t_stat"]
            if tw["return_difference"] > 0:
                (luck if t is None or abs(t) < 2 else beyond).append(
                    f"{label} in {period} ({pct(tw['return_difference'])}, t = {num(t)})")
            elif tw["return_difference"] < 0 and t is not None and abs(t) >= 2:
                cost.append(f"{label} in {period} ({pct(tw['return_difference'])}, t = {num(t)})")
    if luck:
        lines.append("**Within luck** (the return gain is not clearly bigger than chance could produce, "
                     "t below 2 in size): " + "; ".join(luck) + ".")
    if beyond:
        lines.append("Gains that pass the rough luck test (t of 2 or more; days are not independent, so "
                     "this is a guide only): " + "; ".join(beyond) + ".")
    if cost:
        lines.append("Periods where the filter clearly cost return (t of 2 or more): " + "; ".join(cost) + ".")
    if not (luck or beyond):
        lines.append("The filter did not raise the total return of any strategy in either period.")

    # one calendar year carrying the result
    carried, helped = [], []
    for label, _, _, plain_x, plain_t, filt_x, filt_t in pairs:
        plain = {**plain_t.get("yearly", {}), **plain_x.get("yearly", {})}
        filt = {**filt_t.get("yearly", {}), **filt_x.get("yearly", {})}
        diffs = {y: filt[y] - plain[y] for y in plain if y in filt}
        if not diffs:
            continue
        better = sorted(y for y, d in diffs.items() if d > 0)
        helped.append(f"{label}: {len(better)} of {len(diffs)}")
        total, best_year = sum(diffs.values()), max(diffs, key=diffs.get)
        if total > 0 and total - diffs[best_year] <= 0:
            carried.append(f"{label} ({best_year})")
    if helped:
        lines.append("Calendar years in which the filtered version had the higher return: "
                     + "; ".join(helped) + ".")
    if carried:
        lines.append("**The filter's overall gain comes from a single calendar year** (leave that year out "
                     "and the yearly gains add up to zero or less): " + "; ".join(carried) + ".")

    regime = results.get("regime")
    if regime:
        a, b = regime["tuning"], regime["test"]
        lines.append(f"BTC's daily close was above its 200-day average on {pct(a['share_of_days_above'], False)} "
                     f"of the days in {tune_name} ({a['switches']} crossings) and "
                     f"{pct(b['share_of_days_above'], False)} in {test_name} ({b['switches']} crossings); the "
                     "filtered versions sat in cash the rest of the time.")
        lines.append(f"There are only {a['switches']} + {b['switches']} crossings in all: the filter makes "
                     "that few independent calls, so even a clear difference rests on very few market cycles.")
    return lines


def cycle_sections(results):
    """The SUMMARY.md sections for the cycle filter (a list of lines)."""
    proto = results["protocol"]
    test_window = f"{proto['test_window'][0]} to {proto['test_window'][1]}"
    out = []
    w = out.append
    w("## The cycle filter: only hold while BTC's close is above its 200-day average")
    w("")
    w("Each strategy (and buy-and-hold) was also run behind a filter: it opens or keeps a position only while BTC's "
      "daily close is above BTC's 200-day average, and sits in cash otherwise (a position is sold at the next open after "
      "the close that breaks the rule; its own stops still work meanwhile). Same rules and costs as the unfiltered "
      "version. The filter is one fixed rule, not tuned. The variant is the one chosen without it in 2020-2023 (nothing was "
      "chosen using the filter); in the test period each filtered version was run once.")
    w("")
    for line in cycle_verdicts(results):
        w(f"- {line}")
    w("")
    w(f"### Test period ({test_window}), side by side")
    w("")
    w("| Strategy | Return | Return, filtered | Worst fall | Worst fall, filtered | Trades | Trades, filtered | "
      "Without best trade | Without best trade, filtered | Return difference | t-stat |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for label, tw_tune, tw_test, px, pt, fx, ft in _pairs(results):
        w(f"| {label} | {pct(px['total_return'])} | {pct(fx['total_return'])} | {pct(px['max_drawdown'])} | "
          f"{pct(fx['max_drawdown'])} | {px['trades']} | {fx['trades']} | {pct(px['total_return_without_best_1'])} | "
          f"{pct(fx['total_return_without_best_1'])} | {pct(tw_test['return_difference'])} | {num(tw_test['t_stat'])} |")
    w("")
    w("\"Without best trade\" removes the one trade that added most to the portfolio (for buy-and-hold: the best coin) "
      "and recomputes the total return. The t-stat is the rough luck check used above: below 2 in size, the difference "
      "in return could easily be chance.")
    w("")
    w("### 2020-2023, side by side (the same variants as in the test table)")
    w("")
    w("| Strategy | Return | Return, filtered | Worst fall | Worst fall, filtered | Trades | Trades, filtered | "
      "Without best trade | Without best trade, filtered | Return difference | t-stat |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for label, tw_tune, tw_test, px, pt, fx, ft in _pairs(results):
        w(f"| {label} | {pct(pt['total_return'])} | {pct(ft['total_return'])} | {pct(pt['max_drawdown'])} | "
          f"{pct(ft['max_drawdown'])} | {pt['trades']} | {ft['trades']} | {pct(pt['total_return_without_best_1'])} | "
          f"{pct(ft['total_return_without_best_1'])} | {pct(tw_tune['return_difference'])} | {num(tw_tune['t_stat'])} |")
    w("")
    w("### All 13 variants in 2020-2023, with and without the filter")
    w("")
    w("| Family | Variant | Return | Return, filtered | Worst fall | Worst fall, filtered | Trades | Trades, filtered | "
      "Without best trade | Without best trade, filtered |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for g, f in zip(results["tuning"]["variants"], results["tuning"]["filtered_variants"]):
        m, fm = g["metrics"], f["metrics"]
        w(f"| {g['family']} | {g['name']} | {pct(m['total_return'])} | {pct(fm['total_return'])} | "
          f"{pct(m['max_drawdown'])} | {pct(fm['max_drawdown'])} | {m['trades']} | {fm['trades']} | "
          f"{pct(m['total_return_without_best_1'])} | {pct(fm['total_return_without_best_1'])} |")
    w("")
    w("### Calendar years")
    w("")
    rows = []
    for label, _, _, px, pt, fx, ft in _pairs(results):
        rows.append((label, {**pt.get("yearly", {}), **px.get("yearly", {})},
                     {**ft.get("yearly", {}), **fx.get("yearly", {})}))
    years = sorted({y for _, a, b in rows for y in list(a) + list(b)}, key=int)
    w("| Strategy | " + " | ".join(str(y) for y in years) + " |")
    w("|---|" + "---|" * len(years))
    for label, plain, filt in rows:
        w(f"| {label} | " + " | ".join(pct(plain[y]) if y in plain else "–" for y in years) + " |")
        w(f"| {label}, filtered | " + " | ".join(pct(filt[y]) if y in filt else "–" for y in years) + " |")
    by_year = (results.get("regime") or {}).get("by_year")
    if by_year:
        w("| *share of the year BTC was above its 200-day average* | "
          + " | ".join(pct(by_year[int(y)], False) if by_year.get(int(y)) is not None else "–"
                       for y in years) + " |")
    w("")
    return out


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
      "the archive goes. Newer coins (SUI, ONDO, TAO) have only a short history; coverage, gaps and any disagreement between "
      "hourly and daily candles are listed per coin in data_report.csv.")
    w(f"- **Costs:** {info['fee_per_side'] * 100:.2f}% fee per side, plus slippage per side of "
      f"{info['slippage_majors'] * 100:.2f}% for {', '.join(info['majors'])} and {info['slippage_others'] * 100:.2f}% for the "
      "others. A stop that is hit by a gap fills at the next candle's open, never at the stop price.")
    w("- **No peeking:** a decision is made at a daily close and filled at the next open. Long only, no leverage.")
    w(f"- **Tuning period {proto['tuning_window'][0]} to {proto['tuning_window'][1]}:** "
      f"{proto['variants_tried']} variants were tried (3 trend, 4 breakout, 2 momentum, 4 mean-reversion). For each family "
      f"the one with the {proto['selection_rule']} was chosen. Candles after the end of this period were not loaded.")
    w(f"- **Test period {proto['test_window'][0]} to {proto['test_window'][1]}:** only the four chosen variants and "
      f"buy-and-hold were run, once ({proto['test_evaluations_of_the_chosen_variants']} runs). Nothing was changed afterwards.")
    w("- **Cycle filter:** each strategy also ran behind a filter (hold only while BTC's close is above its 200-day "
      "average); it is shown separately below, and nothing was chosen using it.")
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
    w("The t-stat is a rough check on that gap: the average daily difference in growth rate from buy-and-hold, divided by "
      "its standard error. Below about 2 in size, a gap this big could easily be luck (days are not independent, so treat "
      "it as a guide only).")
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
    if results.get("test", {}).get("filtered"):
        out.extend(cycle_sections(results))
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


def _write_cycle_csvs(results, out_dir):
    def row(label, family, variant, plain, filt, twin, period):
        return {"period": period, "strategy": label, "family": family, "variant": variant,
                "return": plain["total_return"], "return_filtered": filt["total_return"],
                "worst_fall": plain["max_drawdown"], "worst_fall_filtered": filt["max_drawdown"],
                "trades": plain["trades"], "trades_filtered": filt["trades"],
                "return_without_best_trade": plain["total_return_without_best_1"],
                "return_without_best_trade_filtered": filt["total_return_without_best_1"],
                "return_difference": twin["return_difference"], "t_stat_of_difference": twin["t_stat"]}
    keys = ("return_difference", "worst_fall_difference", "trades_difference", "t_stat")
    test_rows, tuning_rows = [], []
    for plain, filt in zip(results["test"]["strategies"], results["test"]["filtered"]):
        test_rows.append(row(plain["family"], plain["family"], plain["name"], plain["metrics"], filt["metrics"],
                             {k: filt[k] for k in keys}, "test"))
        tuning_rows.append(row(plain["family"], plain["family"], plain["name"], plain["tuning_metrics"],
                               filt["tuning_metrics"], {k: filt["tuning_vs_unfiltered"][k] for k in keys},
                               "2020-2023"))
    t, x = results["tuning"], results["test"]
    test_rows.append(row("buy-and-hold", "buy-and-hold", "buy-and-hold", x["benchmark"], x["filtered_benchmark"],
                         x["filtered_benchmark_vs_unfiltered"], "test"))
    tuning_rows.append(row("buy-and-hold", "buy-and-hold", "buy-and-hold", t["benchmark"], t["filtered_benchmark"],
                           t["filtered_benchmark_vs_unfiltered"], "2020-2023"))
    for g, f in zip(t["variants"], t["filtered_variants"]):
        tuning_rows.append(row(f"{g['family']}: {g['name']}", g["family"], g["name"], g["metrics"], f["metrics"],
                               f, "2020-2023 (all variants)"))
    _write_csv(os.path.join(out_dir, "cycle_filter_test.csv"), test_rows)
    _write_csv(os.path.join(out_dir, "cycle_filter_tuning.csv"), tuning_rows)
    _write_csv(os.path.join(out_dir, "trades_test_filtered.csv"), results["trades"]["filtered_test"])
    _write_csv(os.path.join(out_dir, "trades_tuning_filtered.csv"), results["trades"]["filtered_tuning"])


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
    if results["test"].get("filtered"):
        _write_cycle_csvs(results, out_dir)
    _write_csv(os.path.join(out_dir, "trades_test.csv"), results["trades"]["test"])
    _write_csv(os.path.join(out_dir, "trades_tuning.csv"), results["trades"]["tuning"])
    _write_csv(os.path.join(out_dir, "data_report.csv"), data_rows)
    with open(os.path.join(out_dir, "results.json"), "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    with open(os.path.join(out_dir, "run_info.json"), "w") as fh:
        json.dump(info, fh, indent=1)
    with open(os.path.join(out_dir, "SUMMARY.md"), "w") as fh:
        fh.write(summary(results, data_rows, info))
