```
==============================================================================
RULE btc_not_falling  (file version 521018e9db)   data: main-1min
  Skip tokens first seen while BTC fell over the last hour; sell at 1h.
  filters: btc_change_1h_pct gte 0
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-24 (6 days)
  left out (CHECK): 203 with no entry price, 13 whose exit checkpoint has no answer yet/missed, 18 with no btc_change_1h_pct; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 1190   win rate 19.6%   average -29.9%   median -61.8%
    profit on $10 a trade $-3554.52   without the best trade $-3721.11   without the best 3 $-4001.35   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-3297.98, the best 5% reach $-2762.05; 77.4% of draws beat the rule, the rule beats 22.6%
  CHECK (latest 40% of days)
    trades 1066   win rate 18.0%   average -32.2%   median -61.7%
    profit on $10 a trade $-3428.97   without the best trade $-3530.65   without the best 3 $-3710.80   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-3190.73, the best 5% reach $-2824.87; 83.4% of draws beat the rule, the rule beats 16.6%

  Ideas tried so far: 8 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-3428.97); profit without the best trade is not positive in CHECK ($-3530.65); trades on fewer than 7 different days in CHECK (6); does not beat 95% of random draws in CHECK (16.6%)
```
