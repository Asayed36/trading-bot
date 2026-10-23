```
==============================================================================
RULE baseline_24h  (file version 2522dbff67)   data: main-1min
  Buy every token at the first check, sell at the 24 hour price.
  filters: none (every token)
  entry: first-check price + 1.5% slippage; exit: sell at the 24h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-17 (7 days), CHECK 2026-10-18 .. 2026-10-22 (5 days)
  left out (CHECK): 188 with no entry price, 198 whose exit checkpoint has no answer yet/missed; total losses among the trades: 2

  LEARN (earliest 60% of days)
    trades 3104   win rate 8.8%   average 654.5%   median -80.2%
    profit on $10 a trade $+203163.99   without the best trade $+57363.24   without the best 3 $-14816.28   days with trades 7
    random draws (1000, same number of tokens on the same days): average $+203163.99, the best 5% reach $+203163.99; 100.0% of draws beat the rule, the rule beats 0.0%
  CHECK (latest 40% of days)
    trades 1839   win rate 6.9%   average -59.0%   median -81.7%
    profit on $10 a trade $-10843.41   without the best trade $-11510.27   without the best 3 $-11804.08   days with trades 5
    random draws (1000, same number of tokens on the same days): average $-10843.41, the best 5% reach $-10843.41; 100.0% of draws beat the rule, the rule beats 0.0%

  Ideas tried so far: 2 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-10843.41); profit without the best trade is not positive in CHECK ($-11510.27); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (0.0%)
```
