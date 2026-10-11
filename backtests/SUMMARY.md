# Backtest summary

Made 2026-10-11T00:42:00+00:00 from Binance spot prices (USDT pairs) up to 2026-10-09, for 18 coins. History only: nothing here trades, and no wallet or key is used.

## The short answer

- Beat buy-and-hold on total return after costs in 2024-01-01 to 2026-10-09 (buy-and-hold +8.8%): trend following (+45.9%); breakout (+21.1%); momentum (+16.8%).
- But for trend following (t = -0.20); breakout (t = -0.46); momentum (t = 0.10) the gap to buy-and-hold is not clearly bigger than luck could produce (t below 2).
- Higher return per unit of risk (Sharpe ratio) than buy-and-hold (0.39): trend following (0.55); momentum (0.43).
- Smaller worst fall than buy-and-hold (-73.4%): trend following (-52.0%, return +45.9%); breakout (-38.2%, return +21.1%); mean reversion (-32.9%, return -6.2%).
- Beat buy-and-hold only in the test period, not in 2020-2023: breakout.
- Depended on one trade (the return is zero or negative without the best trade): momentum.

## How it was tested (so you can judge it)

- **Coins:** BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK, AVAX, DOT, LTC, ATOM, NEAR, UNI, SUI, ONDO, TAO, RENDER. Hourly and daily candles from data.binance.vision, as far back as the archive goes. Newer coins (SUI, ONDO, TAO) have only a short history.
- **Costs:** 0.10% fee per side, plus slippage per side of 0.05% for BTC, ETH, SOL and 0.20% for the others. A stop that is hit by a gap fills at the next candle's open, never at the stop price.
- **No peeking:** a decision is made at a daily close and filled at the next open. Long only, no leverage.
- **Tuning period 2020-01-01 to 2023-12-31:** 13 variants were tried (3 trend, 4 breakout, 2 momentum, 4 mean-reversion). For each family the one with the highest Sharpe ratio of the daily portfolio returns in 2020-2023 (ties: fewer trades, then name) was chosen. Candles after the end of this period were not loaded.
- **Test period 2024-01-01 to 2026-10-09:** only the four chosen variants and buy-and-hold were run, once (4 runs). Nothing was changed afterwards.
- **Portfolio:** the money is split equally between the coins that have 200 days of history; each share is invested while its rule says so and is cash otherwise (momentum: three equal slots). Moving money between shares is free for the strategies and for buy-and-hold alike.

## Test period results (2024-01-01 to 2026-10-09, run once)

| Strategy (chosen in 2020-2023) | Trades | Win rate | Profit factor | Total return | Worst fall | Return minus buy-and-hold (points) | t-stat of that gap | Return without best trade | Without best 3 |
|---|---|---|---|---|---|---|---|---|---|
| **trend following**: close above 50-day average | 598 | 16.7% | 1.58 | +45.9% | -52.0% | +37.1% | -0.20 | +30.9% | +10.9% |
| **breakout**: 20-day high, 3 ATR trailing stop | 257 | 38.5% | 1.34 | +21.1% | -38.2% | +12.3% | -0.46 | +11.9% | +0.8% |
| **mean reversion**: RSI(2), no ADX filter | 981 | 62.4% | 1.03 | -6.2% | -32.9% | -15.0% | -0.77 | -9.6% | -13.0% |
| **momentum**: top 3 by 30-day return, only if it is above zero | 142 | 39.4% | 1.39 | +16.8% | -77.5% | +8.0% | 0.10 | -21.8% | -55.7% |
| **buy-and-hold** of the same coins (each coin is one "trade") | 18 | – | – | +8.8% | -73.4% | – | – | +5.9% (best coin removed) | -0.4% |

The t-stat is the average daily gap to buy-and-hold divided by its standard error: below about 2 in size, a gap this big could easily be luck.

Each row's trades are round trips in one coin; the win rate and profit factor count them after costs. "Without best trade" removes the one trade that added most to the portfolio and recomputes the total return.

## The same strategies in the tuning period (2020-2023)

| Strategy | Total return | Buy-and-hold | Worst fall | Sharpe | Trades |
|---|---|---|---|---|---|
| trend following: close above 50-day average | +3318.5% | +3009.0% | -46.9% | 1.81 | 557 |
| breakout: 20-day high, 3 ATR trailing stop | +843.6% | +3009.0% | -33.6% | 1.52 | 274 |
| mean reversion: RSI(2), no ADX filter | +87.8% | +3009.0% | -43.2% | 0.55 | 954 |
| momentum: top 3 by 30-day return, only if it is above zero | +5312.6% | +3009.0% | -70.6% | 1.56 | 182 |
| buy-and-hold | +3009.0% | – | -79.3% | 1.42 | – |

## Every variant tried in 2020-2023

| Family | Variant | Chosen | Total return | Worst fall | Sharpe | Trades | Win rate |
|---|---|---|---|---|---|---|---|
| trend following | close above 50-day average | yes | +3318.5% | -46.9% | 1.81 | 557 | 25.0% |
| trend following | close above 200-day average |  | +1205.7% | -62.6% | 1.35 | 324 | 15.7% |
| trend following | close above 50-day average and 200-day average |  | +1521.1% | -41.6% | 1.59 | 425 | 22.8% |
| breakout | 20-day high, 2 ATR trailing stop |  | +369.7% | -28.7% | 1.36 | 380 | 42.4% |
| breakout | 20-day high, 3 ATR trailing stop | yes | +843.6% | -33.6% | 1.52 | 274 | 47.8% |
| breakout | 55-day high, 2 ATR trailing stop |  | +213.8% | -21.2% | 1.27 | 253 | 43.1% |
| breakout | 55-day high, 3 ATR trailing stop |  | +375.9% | -30.0% | 1.34 | 185 | 48.1% |
| mean reversion | RSI(2), no ADX filter | yes | +87.8% | -43.2% | 0.55 | 954 | 65.1% |
| mean reversion | RSI(2), only when ADX < 25 |  | +46.1% | -25.7% | 0.43 | 551 | 64.4% |
| mean reversion | Laguerre RSI, no ADX filter |  | +43.5% | -63.9% | 0.42 | 870 | 53.1% |
| mean reversion | Laguerre RSI, only when ADX < 25 |  | +70.6% | -43.0% | 0.54 | 496 | 51.0% |
| momentum | top 3 by 30-day return |  | +3361.3% | -78.1% | 1.39 | 217 | 47.0% |
| momentum | top 3 by 30-day return, only if it is above zero | yes | +5312.6% | -70.6% | 1.56 | 182 | 48.4% |

## Calendar years (the chosen strategies; buy-and-hold in the last row)

| Strategy | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| trend following | +193.7% | +804.2% | -36.9% | +103.9% | +62.9% | -21.0% | +13.4% |
| breakout | +127.6% | +201.4% | -22.1% | +76.5% | +30.3% | -7.5% | +0.4% |
| mean reversion | +45.7% | +51.8% | -17.6% | +3.0% | -5.2% | +14.9% | -13.9% |
| momentum | +189.5% | +984.1% | -51.6% | +256.1% | +150.7% | -34.8% | -28.5% |
| buy-and-hold | +272.2% | +1042.4% | -72.3% | +164.3% | +89.7% | -46.7% | +7.7% |

2020-2023 years come from the tuning run, 2024 onward from the single test run.

## Limits you should keep in mind

- **Survivorship bias.** The coins were picked by hand and all still trade and are liquid today, including the newer SUI, ONDO and TAO; coins that collapsed or were delisted (LUNA, FTT and others) are absent. This flatters every long-only result, buy-and-hold included.
- **A short test.** The test period is a few years of one market; a difference of a few percentage points over a period this short should not be treated as real.
- **Prices are Binance USDT pairs**, not dollars, and fills are simulated: real orders in a fast market can fill worse than the slippage assumed here.
- **Daily candles for decisions**, hourly candles only to decide where a stop fills. Rules were fixed in advance; 13 variants were tried in the tuning period, and picking the best of 13 still flatters the tuning result.
- **No tax, no funding of any kind, no cash interest.**
