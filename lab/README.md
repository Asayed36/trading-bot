# Strategy lab

Tests a trading rule on the data we already recorded, in seconds. It only reads
`data/main-1min/candidates.csv` (and `data/convergence/candidates.csv`), makes no web request and
changes no bot, strategy or setting. Everything it writes goes to `lab/results/`.

    python lab/run_lab.py lab/rules/baseline_1h.toml   # one rule
    python lab/run_lab.py --all                         # every rule + lab/results/summary.md
    python lab/run_lab.py --validate lab/rules/x.toml   # only check the file, count nothing

## Add a rule

Copy a file in `lab/rules/` and change it. Example:

    name = "my_idea"                  # optional, defaults to the file name
    description = "one line"
    source = "main-1min"              # or "convergence"

    [filter.pool_age_minutes]         # any column of candidates.csv; several allowed
    gt = 60                           # gt, gte/min, lt, lte/max, eq, ne, in, not_in

    [exit]
    mode = "fixed"                    # sell at one price...
    at = "1h"                         # ...1h, 6h or 24h
    # or: mode = "first_hit", take_profit_pct = 50, stop_loss_pct = 30, final = "24h"

    [costs]                           # optional; defaults shown
    slippage_pct = 1.5
    round_trip_pct = 3.0

Optional `[tune]` tries several values, chosen **only on the LEARN days**. Every combination
counts as one idea. A typo in a section or column name stops the run with a message.

## What it can and cannot test

- Only three prices exist per token: 1 hour, 6 hours and 24 hours after the first check (so
  "up X% / down Y%" can only be judged at those three moments). Nothing in between.
- Entry is the price at the first check plus 1.5% slippage; no delay is modelled.
- Selling is assumed possible at the recorded price for 3% round trip. Real thin pools can be worse.
- A checkpoint that was asked but had no price counts as a total loss (-$10). A checkpoint not
  yet asked is left out and counted.
- Tokens with a blank value in a filtered column are left out (RugCheck columns exist for only
  a small share of tokens).
- Days are split by time: earliest 60% LEARN, latest 40% CHECK. A rule passes only with
  >= 30 CHECK trades, positive profit also without the best trade, trades on >= 7 days, and
  beating >= 95% of random draws (99% after the 10th idea tried; see `lab/results/history.csv`).
- Passing is not proof of a profit; it is only the minimum bar for a paper test.
