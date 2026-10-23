```
==============================================================================
RULE top10_under_20  (file version 116a0d492a)   data: main-1min
  Only tokens where the 10 biggest holders own under 20 percent (RugCheck data, few tokens have it); sell at 1h.
  filters: rc_top10_pct lt 20
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-23 (5 days)
  left out (CHECK): 181 with no entry price, 16 whose exit checkpoint has no answer yet/missed, 1688 with no rc_top10_pct; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 97   win rate 27.8%   average -21.8%   median -101.5%
    profit on $10 a trade $-211.65   without the best trade $-259.56   without the best 3 $-348.07   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-221.29, the best 5% reach $+65.83; 39.8% of draws beat the rule, the rule beats 60.2%
  CHECK (latest 40% of days)
    trades 60   win rate 18.3%   average -58.7%   median -101.2%
    profit on $10 a trade $-352.12   without the best trade $-371.85   without the best 3 $-399.38   days with trades 5
    random draws (1000, same number of tokens on the same days): average $-177.03, the best 5% reach $-35.40; 99.7% of draws beat the rule, the rule beats 0.3%

  Ideas tried so far: 6 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-352.12); profit without the best trade is not positive in CHECK ($-371.85); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (0.3%)
```
