```
==============================================================================
RULE skip_up_100_in_1h  (file version c36a50efcf)   data: main-1min
  Skip tokens already up over 100 percent in the last hour at the first check; sell at 1h.
  filters: price_change_1h_pct max 100
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-24 (6 days)
  left out (CHECK): 203 with no entry price, 13 whose exit checkpoint has no answer yet/missed, 11 with no price_change_1h_pct; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 1327   win rate 22.2%   average -21.8%   median -39.9%
    profit on $10 a trade $-2895.56   without the best trade $-3154.74   without the best 3 $-3486.10   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-3130.77, the best 5% reach $-2400.62; 31.0% of draws beat the rule, the rule beats 69.0%
  CHECK (latest 40% of days)
    trades 672   win rate 22.2%   average -24.2%   median -40.9%
    profit on $10 a trade $-1624.69   without the best trade $-1722.04   without the best 3 $-1868.74   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-2028.15, the best 5% reach $-1648.73; 4.0% of draws beat the rule, the rule beats 96.0%

  Ideas tried so far: 5 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-1624.69); profit without the best trade is not positive in CHECK ($-1722.04); trades on fewer than 7 different days in CHECK (6)
```
