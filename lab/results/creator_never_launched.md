```
==============================================================================
RULE creator_never_launched  (file version 5203254197)   data: main-1min
  Only tokens whose creator has no earlier launch in our ledger; sell at 1h.
  filters: creator_ledger_launches eq 0
  entry: first-check price + 1.5% slippage; exit: sell at the 1h price
  costs: 3% round trip + the buy slippage; a missing exit price is a total loss
  NOTE: only the 1h, 6h and 24h prices are recorded; no other exit moment can be tested.
  days: LEARN 2026-10-11 .. 2026-10-18 (8 days), CHECK 2026-10-19 .. 2026-10-23 (5 days)
  left out (CHECK): 181 with no entry price, 16 whose exit checkpoint has no answer yet/missed, 1688 with no creator_ledger_launches; total losses among the trades: 0

  LEARN (earliest 60% of days)
    trades 128   win rate 29.7%   average -19.2%   median -100.7%
    profit on $10 a trade $-245.13   without the best trade $-293.04   without the best 3 $-381.55   days with trades 8
    random draws (1000, same number of tokens on the same days): average $-295.06, the best 5% reach $+43.62; 33.9% of draws beat the rule, the rule beats 66.1%
  CHECK (latest 40% of days)
    trades 79   win rate 20.3%   average -52.3%   median -100.5%
    profit on $10 a trade $-412.88   without the best trade $-432.61   without the best 3 $-460.14   days with trades 5
    random draws (1000, same number of tokens on the same days): average $-236.96, the best 5% reach $-66.72; 98.4% of draws beat the rule, the rule beats 1.6%

  Ideas tried so far: 3 (after the 10th idea the bar rises to 99% of random draws).
  VERDICT: FAIL - profit after costs is not positive in CHECK ($-412.88); profit without the best trade is not positive in CHECK ($-432.61); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (1.6%)
```
