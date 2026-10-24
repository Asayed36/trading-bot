```
==============================================================================
RULE many_buys_young  (file version a6135ef422)   data: main-1min
  Young pools (30 min or less) with many buys in the last hour; sell at 1h.
  filters: pool_age_minutes lte 30; buys_1h gte 100
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-24 (6 days)
  left out (CHECK): 203 with no entry price, 13 whose exit checkpoint has no answer yet/missed, 10 with no pool_age_minutes; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 2323   win rate 16.3%   average -29.5%   median -72.2%
    profit on $10 a trade $-6844.61   without the best trade $-7271.15   without the best 3 $-7731.63   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-5713.27, the best 5% reach $-5027.44; 99.4% of draws beat the rule, the rule beats 0.6%
  CHECK (latest 40% of days)
    trades 1437   win rate 16.0%   average -37.0%   median -71.6%
    profit on $10 a trade $-5314.80   without the best trade $-5438.21   without the best 3 $-5637.25   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-4329.35, the best 5% reach $-3966.76; 100.0% of draws beat the rule, the rule beats 0.0%

  Ideas tried so far: 9 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-5314.80); profit without the best trade is not positive in CHECK ($-5438.21); trades on fewer than 7 different days in CHECK (6); does not beat 95% of random draws in CHECK (0.0%)
```
