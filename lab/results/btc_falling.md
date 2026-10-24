```
==============================================================================
RULE btc_falling  (file version 91189c4526)   data: main-1min
  Only tokens first seen while BTC fell more than 0.5% in the last hour; sell at 1h.
  filters: btc_change_1h_pct lt -0.5
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-24 (6 days)
  left out (CHECK): 203 with no entry price, 13 whose exit checkpoint has no answer yet/missed, 18 with no btc_change_1h_pct; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 180   win rate 20.0%   average -40.7%   median -66.7%
    profit on $10 a trade $-732.27   without the best trade $-759.87   without the best 3 $-804.64   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-531.48, the best 5% reach $-286.37; 93.5% of draws beat the rule, the rule beats 6.5%
  CHECK (latest 40% of days)
    trades 89   win rate 16.9%   average -32.6%   median -63.8%
    profit on $10 a trade $-290.34   without the best trade $-383.10   without the best 3 $-446.97   days with trades 5
    random draws (1000, same number of tokens on the same days): average $-278.88, the best 5% reach $-121.31; 50.5% of draws beat the rule, the rule beats 49.5%

  Ideas tried so far: 7 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-290.34); profit without the best trade is not positive in CHECK ($-383.10); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (49.5%)
```
