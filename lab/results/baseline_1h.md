```
==============================================================================
RULE baseline_1h  (file version 0c54ff7934)   data: main-1min
  Buy every token at the first check, sell at the 1 hour price (the baseline to beat).
  filters: none (every token)
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-24 (6 days)
  left out (CHECK): 203 with no entry price, 13 whose exit checkpoint has no answer yet/missed; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 3480   win rate 19.2%   average -24.2%   median -61.1%
    profit on $10 a trade $-8421.17   without the best trade $-8847.71   without the best 3 $-9308.20   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-8421.17, the best 5% reach $-8421.17; 100.0% of draws beat the rule, the rule beats 0.0%
  CHECK (latest 40% of days)
    trades 2050   win rate 19.8%   average -30.2%   median -61.4%
    profit on $10 a trade $-6181.56   without the best trade $-6304.97   without the best 3 $-6504.01   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-6181.56, the best 5% reach $-6181.56; 100.0% of draws beat the rule, the rule beats 0.0%

  Ideas tried so far: 1 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-6181.56); profit without the best trade is not positive in CHECK ($-6304.97); trades on fewer than 7 different days in CHECK (6); does not beat 95% of random draws in CHECK (0.0%)
```
