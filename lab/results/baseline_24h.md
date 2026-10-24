```
==============================================================================
RULE baseline_24h  (file version 2522dbff67)   data: main-1min
  Buy every token at the first check, sell at the 24 hour price.
  filters: none (every token)
  entry: first-check price + 1.5% slippage; exit: sell at the 24h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-23 (5 days)
  left out (CHECK): 199 with no entry price, 236 whose exit checkpoint has no answer yet/missed; total losses among the trades: 2

  LEARN (earliest 60% of days)
    trades 3480   win rate 8.4%   average 577.7%   median -80.3%
    profit on $10 a trade $+201044.60   without the best trade $+55243.85   without the best 3 $-16935.67   days with trades 8
    random draws (1000, same number of tokens on the same days): average $+201044.60, the best 5% reach $+201044.60; 100.0% of draws beat the rule, the rule beats 0.0%
  CHECK (latest 40% of days)
    trades 1734   win rate 7.6%   average -59.4%   median -81.8%
    profit on $10 a trade $-10304.82   without the best trade $-10971.69   without the best 3 $-11193.05   days with trades 5
    random draws (1000, same number of tokens on the same days): average $-10304.82, the best 5% reach $-10304.82; 100.0% of draws beat the rule, the rule beats 0.0%

  Ideas tried so far: 2 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-10304.82); profit without the best trade is not positive in CHECK ($-10971.69); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (0.0%)
```
