# Backtest tool

Replays simple, standard strategies on historical prices of liquid coins, to
check many ideas quickly and honestly. **It is separate from the paper-trading
bots**: it shares no code, no data and no setting with them, trades nothing,
and uses no key, no secret and no wallet. The only thing it writes is the
`backtests/` folder.

## Run it

- **On GitHub:** Actions > *Backtest (price history)* > *Run workflow*. About
  3-5 minutes. It runs its own tests first, then the backtest, then saves
  `backtests/` to the repository (and attaches it to the run). The
  *quick* option runs 4 coins only and writes to `backtests/quick/`.
- **Anywhere with Python 3.11+** (nothing to install, standard library only):
  `python -m backtest` (`--quick`, `--out FOLDER`, `--cache FOLDER`, `--offline`).
- **Tests:** `python -m unittest discover -s backtest/tests`. They live apart
  from `tests/` on purpose, so the paper-trading run does not run them.

Start with `backtests/SUMMARY.md`: a plain-language account of what it found,
whose sentences are produced from the numbers by fixed rules (`report.py`).

## Where the prices come from

Binance's public data archive, **data.binance.vision**: monthly zip files of
hourly and daily candles for USDT pairs, back to 2017 for the oldest coins.
It was tested on 2026-10-11 from this kind of sandbox and from a GitHub Actions
runner:

| Source | From the sandbox | From GitHub Actions |
|---|---|---|
| **data.binance.vision** (file archive) | **works** | **works** (36 monthly files in 2 s) |
| Binance live API | blocked by the sandbox | refused (HTTP 451, restricted location) |
| Bybit live API | blocked by the sandbox | refused (HTTP 403) |
| Kraken, Coinbase Exchange, Bitstamp, OKX, KuCoin, Bitfinex, Gemini, Yahoo | blocked by the sandbox | answer (HTTP 200) |

Only the archive works from both, so it is the one used. The ones that answer
from GitHub were not chosen because they could not be reached from the sandbox,
and because their documented limits are small (Kraken's OHLC call returns only
its latest 720 candles, Coinbase's 300 per request). No key is needed.

## The test, step by step

1. **Coins:** BTC, ETH, SOL and 15 others (BNB, XRP, ADA, DOGE, LINK, AVAX, DOT,
   LTC, ATOM, NEAR, UNI, SUI, ONDO, TAO, RENDER), chosen by hand before any
   result was seen (`universe.py`). RNDR and RENDER are joined 1:1 (Binance
   renamed the coin in July 2024; the archive has a 3-day gap there, and
   prices carry on from $7.03 to $6.78). Each coin starts on its first day in
   the archive, so SUI starts in 2023, TAO in 2024 and ONDO in 2025.
2. **Costs** on every fill: 0.10% fee per side, plus slippage per side of
   0.05% for BTC/ETH/SOL and 0.20% for the others (buy higher, sell lower).
3. **Fills:** a decision is made at a daily close and filled at the next day's
   open. A stop is watched on the hourly candles; it fills at the stop price,
   but a candle that *opens* beyond the stop (a gap) fills at that open.
4. **Strategies and the whole grid** (13 variants, nothing else was tried):
   - trend following: close above its 50-day / 200-day / both averages (3)
   - breakout: a new 20- or 55-day high, trailing stop 2 or 3 ATRs (4)
   - momentum: top 3 coins by 30-day return, rebalanced every Monday open,
     with or without "only if that return is above zero" (2)
   - mean reversion: RSI(2) or Laguerre RSI, with or without ADX < 25 (4)
   - the benchmark: buy-and-hold of the same coins
5. **Validation:** the 13 variants are run on 2020-01-01 to 2023-12-31 only
   (later candles are cut off before this step, so they are not even in
   memory). For each family, the variant with the best Sharpe ratio is chosen.
   Only those four, and buy-and-hold, are then run once on 2024-01-01 to the
   last day. The result tables show both periods side by side.
6. **Portfolio:** the money is split equally between the coins that have 200
   days of history; each coin's share is in the coin while its rule says so and
   in cash otherwise (momentum: three equal slots). Moving money between
   shares is free, for the strategies and for buy-and-hold alike.

## What is in `backtests/`

| File | What |
|---|---|
| `SUMMARY.md` | the findings in plain language, then the tables |
| `test_results.csv` | the four chosen strategies in 2024-now: trades, win rate, profit factor, total return, max drawdown, return minus buy-and-hold, return without the best 1 and 3 trades |
| `tuning_grid.csv` | all 13 variants in 2020-2023 |
| `trades_tuning.csv`, `trades_test.csv` | every trade of the chosen strategies |
| `data_report.csv` | per coin: first and last day, hours missing, days where hourly and daily candles disagree |
| `results.json`, `run_info.json` | everything, and when/with what it was made |

## How "run once" was kept

While the tool was being built it was run several times (4 coins, then all 18,
on the sandbox and on GitHub). No rule, parameter or cost was changed after any
of those runs; only the report (layout, a noise check) was added. Every run of
the finished tool is the full protocol, start to end.

## What it cannot tell you

- **Survivorship bias:** the coins all still trade today. Coins that collapsed
  (LUNA, FTT, ...) are absent, so every long-only result is flattered.
- **A few years of one market** is a small sample; small differences are noise,
  and picking the best of 13 variants flatters the tuning period.
- Prices are Binance USDT pairs; real fills in a fast market can be worse than
  the slippage assumed; no tax, no interest on cash.

## Files

`universe.py` coins and costs - `data.py` download and parsing - `indicators.py`
SMA, ATR, RSI, ADX, Laguerre RSI - `engine.py` the day-by-day replay of one coin -
`strategies.py` the strategies and the grid - `portfolio.py` combining coins and
the measures - `run.py` the protocol and the command line - `report.py` the
output files and `SUMMARY.md`.
