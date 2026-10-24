```
==============================================================================
RULE top10_under_20  (file version 116a0d492a)   data: main-1min
  Only tokens where the 10 biggest holders own under 20 percent (RugCheck data, few tokens have it); sell at 1h.
  filters: rc_top10_pct lt 20
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-24 (6 days)
  left out (CHECK): 203 with no entry price, 13 whose exit checkpoint has no answer yet/missed, 1953 with no rc_top10_pct; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 97   win rate 27.8%   average -21.8%   median -101.5%
    profit on $10 a trade $-211.65   without the best trade $-259.56   without the best 3 $-348.07   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-221.29, the best 5% reach $+65.83; 39.8% of draws beat the rule, the rule beats 60.2%
  CHECK (latest 40% of days)
    trades 71   win rate 16.9%   average -61.5%   median -101.2%
    profit on $10 a trade $-436.55   without the best trade $-456.29   without the best 3 $-483.81   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-207.26, the best 5% reach $-49.14; 100.0% of draws beat the rule, the rule beats 0.0%

  Ideas tried so far: 6 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-436.55); profit without the best trade is not positive in CHECK ($-456.29); trades on fewer than 7 different days in CHECK (6); does not beat 95% of random draws in CHECK (0.0%)
```
