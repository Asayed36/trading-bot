```
==============================================================================
RULE skip_up_100_in_1h  (file version c36a50efcf)   data: main-1min
  Skip tokens already up over 100 percent in the last hour at the first check; sell at 1h.
  filters: price_change_1h_pct max 100
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-23 (5 days)
  left out (CHECK): 181 with no entry price, 16 whose exit checkpoint has no answer yet/missed, 10 with no price_change_1h_pct; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 1327   win rate 22.2%   average -21.8%   median -39.9%
    profit on $10 a trade $-2895.56   without the best trade $-3154.74   without the best 3 $-3486.10   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-3130.77, the best 5% reach $-2400.62; 31.0% of draws beat the rule, the rule beats 69.0%
  CHECK (latest 40% of days)
    trades 581   win rate 21.7%   average -24.8%   median -40.9%
    profit on $10 a trade $-1441.69   without the best trade $-1520.62   without the best 3 $-1647.91   days with trades 5
    random draws (1000, same number of tokens on the same days): average $-1768.69, the best 5% reach $-1423.75; 6.1% of draws beat the rule, the rule beats 93.9%

  Ideas tried so far: 5 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-1441.69); profit without the best trade is not positive in CHECK ($-1520.62); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (93.9%)
```
