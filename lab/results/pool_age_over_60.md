```
==============================================================================
RULE pool_age_over_60  (file version 776765ff45)   data: main-1min
  Only tokens whose pool was already over 60 minutes old at the first check; sell at 1h.
  filters: pool_age_minutes gt 60
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-24 (6 days)
  left out (CHECK): 203 with no entry price, 13 whose exit checkpoint has no answer yet/missed, 10 with no pool_age_minutes; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 533   win rate 28.9%   average -3.3%   median -7.1%
    profit on $10 a trade $-174.97   without the best trade $-338.73   without the best 3 $-470.17   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-1250.74, the best 5% reach $-653.06; 0.0% of draws beat the rule, the rule beats 100.0%
  CHECK (latest 40% of days)
    trades 278   win rate 35.6%   average -5.0%   median -6.7%
    profit on $10 a trade $-140.23   without the best trade $-213.40   without the best 3 $-306.69   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-831.77, the best 5% reach $-559.92; 0.0% of draws beat the rule, the rule beats 100.0%

  Ideas tried so far: 4 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-140.23); profit without the best trade is not positive in CHECK ($-213.40); trades on fewer than 7 different days in CHECK (6)
```
