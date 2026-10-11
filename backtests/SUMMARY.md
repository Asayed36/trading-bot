# Backtest summary

Made 2026-10-11T07:12:25+00:00 from Binance spot prices (USDT pairs) up to 2026-10-10, for 18 coins. History only: nothing here trades, and no wallet or key is used.

## The short answer

- Beat buy-and-hold on total return after costs in 2024-01-01 to 2026-10-10 (buy-and-hold +10.6%): trend following (+48.1%); breakout (+21.6%); momentum (+21.8%).
- But for trend following (t = 0.36); breakout (t = 0.10); momentum (t = 0.13) the gap to buy-and-hold is not clearly bigger than luck could produce (t below 2).
- Higher return per unit of risk (Sharpe ratio) than buy-and-hold (0.40): trend following (0.56); momentum (0.45).
- Smaller worst fall than buy-and-hold (-73.4%): trend following (-52.0%, return +48.1%); breakout (-38.2%, return +21.6%); mean reversion (-32.9%, return -5.0%).
- Beat buy-and-hold only in the test period, not in 2020-2023: breakout.
- Depended on one trade (the return is zero or negative without the best trade): momentum.

## How it was tested (so you can judge it)

- **Coins:** BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK, AVAX, DOT, LTC, ATOM, NEAR, UNI, SUI, ONDO, TAO, RENDER. Hourly and daily candles from data.binance.vision, as far back as the archive goes. Newer coins (SUI, ONDO, TAO) have only a short history; coverage, gaps and any disagreement between hourly and daily candles are listed per coin in data_report.csv.
- **Costs:** 0.10% fee per side, plus slippage per side of 0.05% for BTC, ETH, SOL and 0.20% for the others. A stop that is hit by a gap fills at the next candle's open, never at the stop price.
- **No peeking:** a decision is made at a daily close and filled at the next open. Long only, no leverage.
- **Tuning period 2020-01-01 to 2023-12-31:** 13 variants were tried (3 trend, 4 breakout, 2 momentum, 4 mean-reversion). For each family the one with the highest Sharpe ratio of the daily portfolio returns in 2020-2023 (ties: fewer trades, then name) was chosen. Candles after the end of this period were not loaded.
- **Test period 2024-01-01 to 2026-10-10:** only the four chosen variants and buy-and-hold were run, once (4 runs). Nothing was changed afterwards.
- **Cycle filter:** each strategy also ran behind a filter (hold only while BTC's close is above its 200-day average); it is shown separately below, and nothing was chosen using it.
- **Portfolio:** the money is split equally between the coins that have 200 days of history; each share is invested while its rule says so and is cash otherwise (momentum: three equal slots). Moving money between shares is free for the strategies and for buy-and-hold alike.

## Test period results (2024-01-01 to 2026-10-10, run once)

| Strategy (chosen in 2020-2023) | Trades | Win rate | Profit factor | Total return | Worst fall | Return minus buy-and-hold (points) | t-stat of that gap | Return without best trade | Without best 3 |
|---|---|---|---|---|---|---|---|---|---|
| **trend following**: close above 50-day average | 599 | 16.9% | 1.60 | +48.1% | -52.0% | +37.5% | 0.36 | +32.9% | +12.6% |
| **breakout**: 20-day high, 3 ATR trailing stop | 258 | 38.8% | 1.35 | +21.6% | -38.2% | +10.9% | 0.10 | +12.4% | +0.7% |
| **mean reversion**: RSI(2), no ADX filter | 981 | 62.4% | 1.04 | -5.0% | -32.9% | -15.6% | -0.18 | -8.4% | -11.8% |
| **momentum**: top 3 by 30-day return, only if it is above zero | 142 | 39.4% | 1.41 | +21.8% | -77.5% | +11.2% | 0.13 | -18.5% | -53.8% |
| **buy-and-hold** of the same coins (each coin is one "trade") | 18 | – | – | +10.6% | -73.4% | – | – | +7.4% (best coin removed) | +0.5% |

The t-stat is a rough check on that gap: the average daily difference in growth rate from buy-and-hold, divided by its standard error. Below about 2 in size, a gap this big could easily be luck (days are not independent, so treat it as a guide only).

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
| trend following | +193.7% | +804.2% | -36.9% | +103.9% | +62.9% | -21.0% | +15.2% |
| breakout | +127.6% | +201.4% | -22.1% | +76.5% | +30.3% | -7.5% | +0.9% |
| mean reversion | +45.7% | +51.8% | -17.6% | +3.0% | -5.2% | +14.9% | -12.8% |
| momentum | +189.5% | +984.1% | -51.6% | +256.1% | +150.7% | -34.8% | -25.5% |
| buy-and-hold | +272.2% | +1042.4% | -72.3% | +164.3% | +89.7% | -46.7% | +9.5% |

2020-2023 years come from the tuning run, 2024 onward from the single test run.

## The cycle filter: only hold while BTC's close is above its 200-day average

Each strategy (and buy-and-hold) was also run behind a filter: it opens or keeps a position only while BTC's daily close is above BTC's 200-day average, and sits in cash otherwise (a position is sold at the next open after the close that breaks the rule; its own stops still work meanwhile). Same rules and costs as the unfiltered version. The filter is one fixed rule, not tuned. The variant is the one chosen without it in 2020-2023 (nothing was chosen using the filter); in the test period each filtered version was run once.

- With the filter, a higher total return in **both** periods: none. Only in 2020-2023: none. Only in the test period: trend following, breakout, mean reversion, momentum. In neither: buy-and-hold.
- With the filter, a smaller worst fall in **both** periods: trend following, breakout, mean reversion, momentum, buy-and-hold. Only in 2020-2023: none. Only in the test period: none. In neither: none.
- **The filter's return gain shows in only one of the two periods** for: trend following, breakout, mean reversion, momentum (see the first line for which).
- **Within luck** (the return gain is not clearly bigger than chance could produce, t below 2 in size): trend following in the test period (+15.7%, t = 0.47); breakout in the test period (+30.8%, t = 1.20); mean reversion in the test period (+25.0%, t = 0.56); momentum in the test period (+85.0%, t = 0.88).
- The filter **lowered** the total return (but by a margin that could be luck, t below 2 in size) for: trend following in 2020-2023 (-1256.9%, t = -1.04); breakout in 2020-2023 (-508.4%, t = -1.81); mean reversion in 2020-2023 (-8.0%, t = -0.06); momentum in 2020-2023 (-2786.7%, t = -0.71); buy-and-hold in 2020-2023 (-464.7%, t = -0.13); buy-and-hold in the test period (-7.5%, t = -0.11).
- Calendar years in which the filtered version had the higher return: trend following: 3 of 7; breakout: 4 of 7; mean reversion: 3 of 7; momentum: 3 of 7; buy-and-hold: 2 of 7.
- **The filter's overall gain comes from a single calendar year** (leave that year out and the yearly gains add up to zero or less): mean reversion (2026).
- BTC's daily close was above its 200-day average on 57.2% of the days in 2020-2023 (29 crossings) and 60.5% in the test period (28 crossings); the filtered versions sat in cash the rest of the time.
- There are only 29 + 28 crossings in all: the filter makes that few independent calls, so even a clear difference rests on very few market cycles.

### Test period (2024-01-01 to 2026-10-10), side by side

| Strategy | Return | Return, filtered | Worst fall | Worst fall, filtered | Trades | Trades, filtered | Without best trade | Without best trade, filtered | Return difference | t-stat |
|---|---|---|---|---|---|---|---|---|---|---|
| trend following | +48.1% | +63.8% | -52.0% | -39.7% | 599 | 432 | +32.9% | +48.8% | +15.7% | 0.47 |
| breakout | +21.6% | +52.3% | -38.2% | -31.8% | 258 | 199 | +12.4% | +40.8% | +30.8% | 1.20 |
| mean reversion | -5.0% | +20.1% | -32.9% | -22.3% | 981 | 496 | -8.4% | +15.7% | +25.0% | 0.56 |
| momentum | +21.8% | +106.7% | -77.5% | -51.5% | 142 | 99 | -18.5% | +38.4% | +85.0% | 0.88 |
| buy-and-hold | +10.6% | +3.1% | -73.4% | -61.0% | 18 | 253 | +7.4% | -4.9% | -7.5% | -0.11 |

"Without best trade" removes the one trade that added most to the portfolio (for buy-and-hold: the best coin) and recomputes the total return. The t-stat is the rough luck check used above: below 2 in size, the difference in return could easily be chance.

### 2020-2023, side by side (the same variants as in the test table)

| Strategy | Return | Return, filtered | Worst fall | Worst fall, filtered | Trades | Trades, filtered | Without best trade | Without best trade, filtered | Return difference | t-stat |
|---|---|---|---|---|---|---|---|---|---|---|
| trend following | +3318.5% | +2061.6% | -46.9% | -36.2% | 557 | 419 | +1841.6% | +1127.7% | -1256.9% | -1.04 |
| breakout | +843.6% | +335.2% | -33.6% | -27.1% | 274 | 227 | +659.0% | +250.1% | -508.4% | -1.81 |
| mean reversion | +87.8% | +79.8% | -43.2% | -27.9% | 954 | 416 | +34.4% | +28.7% | -8.0% | -0.06 |
| momentum | +5312.6% | +2525.9% | -70.6% | -60.0% | 182 | 131 | +3384.0% | +1590.3% | -2786.7% | -0.71 |
| buy-and-hold | +3009.0% | +2544.3% | -79.3% | -54.6% | 16 | 204 | +1558.4% | +1138.9% | -464.7% | -0.13 |

### All 13 variants in 2020-2023, with and without the filter

| Family | Variant | Return | Return, filtered | Worst fall | Worst fall, filtered | Trades | Trades, filtered | Without best trade | Without best trade, filtered |
|---|---|---|---|---|---|---|---|---|---|
| trend following | close above 50-day average | +3318.5% | +2061.6% | -46.9% | -36.2% | 557 | 419 | +1841.6% | +1127.7% |
| trend following | close above 200-day average | +1205.7% | +1310.7% | -62.6% | -59.2% | 324 | 302 | +551.3% | +575.4% |
| trend following | close above 50-day average and 200-day average | +1521.1% | +1349.4% | -41.6% | -45.2% | 425 | 397 | +830.0% | +731.6% |
| breakout | 20-day high, 2 ATR trailing stop | +369.7% | +166.7% | -28.7% | -21.4% | 380 | 304 | +278.5% | +114.9% |
| breakout | 20-day high, 3 ATR trailing stop | +843.6% | +335.2% | -33.6% | -27.1% | 274 | 227 | +659.0% | +250.1% |
| breakout | 55-day high, 2 ATR trailing stop | +213.8% | +167.6% | -21.2% | -19.4% | 253 | 232 | +152.7% | +115.5% |
| breakout | 55-day high, 3 ATR trailing stop | +375.9% | +280.1% | -30.0% | -24.2% | 185 | 177 | +282.0% | +205.1% |
| mean reversion | RSI(2), no ADX filter | +87.8% | +79.8% | -43.2% | -27.9% | 954 | 416 | +34.4% | +28.7% |
| mean reversion | RSI(2), only when ADX < 25 | +46.1% | +46.4% | -25.7% | -26.2% | 551 | 262 | +3.2% | +3.4% |
| mean reversion | Laguerre RSI, no ADX filter | +43.5% | +79.4% | -63.9% | -45.2% | 870 | 438 | +3.6% | +29.5% |
| mean reversion | Laguerre RSI, only when ADX < 25 | +70.6% | +101.2% | -43.0% | -32.1% | 496 | 274 | +22.0% | +43.9% |
| momentum | top 3 by 30-day return | +3361.3% | +2292.2% | -78.1% | -63.2% | 217 | 138 | +2128.0% | +1439.9% |
| momentum | top 3 by 30-day return, only if it is above zero | +5312.6% | +2525.9% | -70.6% | -60.0% | 182 | 131 | +3384.0% | +1590.3% |

### Calendar years

| Strategy | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| trend following | +193.7% | +804.2% | -36.9% | +103.9% | +62.9% | -21.0% | +15.2% |
| trend following, filtered | +112.4% | +467.0% | +0.0% | +79.5% | +48.2% | -21.0% | +40.0% |
| breakout | +127.6% | +201.4% | -22.1% | +76.5% | +30.3% | -7.5% | +0.9% |
| breakout, filtered | +51.3% | +85.8% | +0.0% | +54.8% | +36.7% | -3.5% | +15.5% |
| mean reversion | +45.7% | +51.8% | -17.6% | +3.0% | -5.2% | +14.9% | -12.8% |
| mean reversion, filtered | +33.3% | +36.2% | +0.0% | -1.0% | -1.2% | +14.6% | +6.0% |
| momentum | +189.5% | +984.1% | -51.6% | +256.1% | +150.7% | -34.8% | -25.5% |
| momentum, filtered | +145.5% | +421.2% | +0.0% | +105.2% | +80.4% | -6.1% | +22.0% |
| buy-and-hold | +272.2% | +1042.4% | -72.3% | +164.3% | +89.7% | -46.7% | +9.5% |
| buy-and-hold, filtered | +146.0% | +451.9% | +0.0% | +94.8% | +35.7% | -47.8% | +45.4% |
| *share of the year BTC was above its 200-day average* | 77.6% | 70.7% | 0.0% | 80.5% | 80.1% | 73.2% | 18.7% |

## Limits you should keep in mind

- **Survivorship bias.** The coins were picked by hand and all still trade and are liquid today, including the newer SUI, ONDO and TAO; coins that collapsed or were delisted (LUNA, FTT and others) are absent. This flatters every long-only result, buy-and-hold included.
- **A short test.** The test period is a few years of one market; a difference of a few percentage points over a period this short should not be treated as real.
- **Prices are Binance USDT pairs**, not dollars, and fills are simulated: real orders in a fast market can fill worse than the slippage assumed here.
- **Daily candles for decisions**, hourly candles only to decide where a stop fills. Rules were fixed in advance; 13 variants were tried in the tuning period, and picking the best of 13 still flatters the tuning result.
- **No tax, no funding of any kind, no cash interest.**
