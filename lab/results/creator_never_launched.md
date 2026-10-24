```
==============================================================================
RULE creator_never_launched  (file version 5203254197)   data: main-1min
  Only tokens whose creator has no earlier launch in our ledger; sell at 1h.
  filters: creator_ledger_launches eq 0
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-24 (6 days)
  left out (CHECK): 203 with no entry price, 13 whose exit checkpoint has no answer yet/missed, 1954 with no creator_ledger_launches; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 128   win rate 29.7%   average -19.2%   median -100.7%
    profit on $10 a trade $-245.13   without the best trade $-293.04   without the best 3 $-381.55   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-295.06, the best 5% reach $+43.62; 33.9% of draws beat the rule, the rule beats 66.1%
  CHECK (latest 40% of days)
    trades 94   win rate 20.2%   average -54.4%   median -100.4%
    profit on $10 a trade $-511.63   without the best trade $-531.36   without the best 3 $-558.89   days with trades 6
    random draws (1000, same number of tokens on the same days): average $-280.20, the best 5% reach $-92.79; 100.0% of draws beat the rule, the rule beats 0.0%

  Ideas tried so far: 3 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-511.63); profit without the best trade is not positive in CHECK ($-531.36); trades on fewer than 7 different days in CHECK (6); does not beat 95% of random draws in CHECK (0.0%)
```
