# Strategy lab summary

One row per rule (CHECK = the latest 40% of days; the rule's parameters were fixed on the earlier days). Profit is on $10 a trade after costs. Only the 1h, 6h and 24h prices exist, so these are the only exits that can be tested.

| Rule | Idea | LEARN trades | LEARN avg | CHECK trades | CHECK avg | CHECK profit | without best | CHECK days | beats random | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline_1h | 1 | 3480 | -24.2% | 1769 | -30.5% | $-5392.45 | $-5515.86 | 5 | 0.0% (need 95%) | FAIL: profit after costs is not positive in CHECK ($-5392.45); profit without the best trade is not positive in CHECK ($-5515.86); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (0.0%) |
| baseline_24h | 2 | 3104 | 654.5% | 1839 | -59.0% | $-10843.41 | $-11510.27 | 5 | 0.0% (need 95%) | FAIL: profit after costs is not positive in CHECK ($-10843.41); profit without the best trade is not positive in CHECK ($-11510.27); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (0.0%) |
| creator_never_launched | 3 | 128 | -19.2% | 79 | -52.3% | $-412.88 | $-432.61 | 5 | 1.6% (need 95%) | FAIL: profit after costs is not positive in CHECK ($-412.88); profit without the best trade is not positive in CHECK ($-432.61); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (1.6%) |
| pool_age_over_60 | 4 | 533 | -3.3% | 234 | -4.4% | $-103.42 | $-176.60 | 5 | 99.9% (need 95%) | FAIL: profit after costs is not positive in CHECK ($-103.42); profit without the best trade is not positive in CHECK ($-176.60); trades on fewer than 7 different days in CHECK (5) |
| skip_up_100_in_1h | 5 | 1327 | -21.8% | 581 | -24.8% | $-1441.69 | $-1520.62 | 5 | 93.9% (need 95%) | FAIL: profit after costs is not positive in CHECK ($-1441.69); profit without the best trade is not positive in CHECK ($-1520.62); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (93.9%) |
| top10_under_20 | 6 | 97 | -21.8% | 60 | -58.7% | $-352.12 | $-371.85 | 5 | 0.3% (need 95%) | FAIL: profit after costs is not positive in CHECK ($-352.12); profit without the best trade is not positive in CHECK ($-371.85); trades on fewer than 7 different days in CHECK (5); does not beat 95% of random draws in CHECK (0.3%) |

Ideas tried so far: 6. Chance alone passes some rules: after the 10th idea the bar is 99% of random draws.
