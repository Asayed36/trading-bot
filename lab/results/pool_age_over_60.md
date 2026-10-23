```
==============================================================================
RULE pool_age_over_60  (file version 776765ff45)   data: main-1min
  Only tokens whose pool was already over 60 minutes old at the first check; sell at 1h.
  filters: pool_age_minutes gt 60
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-23 (5 days)
  left out (CHECK): 181 with no entry price, 16 whose exit checkpoint has no answer yet/missed, 9 with no pool_age_minutes; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 533   win rate 28.9%   average -3.3%   median -7.1%
    profit on $10 a trade $-174.97   without the best trade $-338.73   without the best 3 $-470.17   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-1250.74, the best 5% reach $-653.06; 0.0% of draws beat the rule, the rule beats 100.0%
  CHECK (latest 40% of days)
    trades 234   win rate 35.0%   average -4.4%   median -6.9%
    profit on $10 a trade $-103.42   without the best trade $-176.60   without the best 3 $-269.89   days with trades 5
    random draws (1000, same number of tokens on the same days): average $-713.75, the best 5% reach $-458.69; 0.1% of draws beat the rule, the rule beats 99.9%

  Ideas tried so far: 4 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-103.42); profit without the best trade is not positive in CHECK ($-176.60); trades on fewer than 7 different days in CHECK (5)
```
