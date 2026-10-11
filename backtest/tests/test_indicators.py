import unittest

import helpers  # noqa: F401  (puts the repo on the path)

from backtest import indicators as ind


class IndicatorTests(unittest.TestCase):
    def test_sma_and_highest_before(self):
        self.assertEqual(ind.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])
        # the highest of the 3 values BEFORE each index, never the index itself
        self.assertEqual(ind.highest_before([1, 5, 2, 9, 3], 3), [None, None, None, 5, 9])

    def test_atr_wilder(self):
        high, low, close = [10, 12, 11, 13], [8, 9, 9, 10], [9, 11, 10, 12]
        tr = ind.true_range(high, low, close)
        self.assertEqual(tr, [2, 3, 2, 3])        # max(h-l, |h-prev c|, |l-prev c|)
        atr = ind.atr(high, low, close, 2)
        self.assertEqual(atr[0], None)
        self.assertAlmostEqual(atr[1], 2.5)       # mean of the first 2
        self.assertAlmostEqual(atr[2], 2.25)      # (2.5 * 1 + 2) / 2
        self.assertAlmostEqual(atr[3], 2.625)

    def test_rsi2_by_hand(self):
        # changes: +2, -1, +1 ; n=2 -> first value at index 2
        close = [10, 12, 11, 12]
        r = ind.rsi(close, 2)
        self.assertEqual(r[:2], [None, None])
        self.assertAlmostEqual(r[2], 100 - 100 / (1 + 1.0 / 0.5))     # avg gain 1.0, avg loss 0.5 -> 66.67
        # next: gain 1 -> avg gain (1*1+1)/2 = 1.0 ; avg loss (0.5*1+0)/2 = 0.25
        self.assertAlmostEqual(r[3], 100 - 100 / (1 + 1.0 / 0.25))
        self.assertEqual(ind.rsi([5, 6, 7, 8], 2)[-1], 100.0)         # only gains
        self.assertLess(ind.rsi([8, 7, 6, 5, 4], 2)[-1], 1e-9)        # only losses

    def test_adx_high_in_a_trend_low_in_a_range(self):
        up = [100 + 2 * i for i in range(80)]
        trend = ind.adx([x + 1 for x in up], [x - 1 for x in up], up, 14)
        wave = [100 + (3 if i % 2 else -3) for i in range(80)]
        rng = ind.adx([x + 1 for x in wave], [x - 1 for x in wave], wave, 14)
        self.assertGreater(trend[-1], 60)
        self.assertLess(rng[-1], 15)
        self.assertEqual(trend[:27], [None] * 27)

    def test_laguerre_rsi_range_and_direction(self):
        up = ind.laguerre_rsi([100 + i for i in range(60)])
        down = ind.laguerre_rsi([200 - i for i in range(60)])
        self.assertGreater(up[-1], 0.9)
        self.assertLess(down[-1], 0.1)
        self.assertTrue(all(0 <= v <= 1 for v in up if v is not None))

    def test_a_value_never_depends_on_later_data(self):
        base = [100 + (i * 7) % 13 + i * 0.3 for i in range(120)]
        high, low = [x + 2 for x in base], [x - 2 for x in base]
        altered = base[:80] + [x * 3 for x in base[80:]]
        a_high, a_low = [x + 2 for x in altered], [x - 2 for x in altered]
        for name, f, g in (
                ("sma", lambda: ind.sma(base, 20), lambda: ind.sma(altered, 20)),
                ("atr", lambda: ind.atr(high, low, base), lambda: ind.atr(a_high, a_low, altered)),
                ("rsi", lambda: ind.rsi(base, 2), lambda: ind.rsi(altered, 2)),
                ("adx", lambda: ind.adx(high, low, base), lambda: ind.adx(a_high, a_low, altered)),
                ("laguerre", lambda: ind.laguerre_rsi(base), lambda: ind.laguerre_rsi(altered)),
                ("highest", lambda: ind.highest_before(base, 20), lambda: ind.highest_before(altered, 20))):
            self.assertEqual(f()[:80], g()[:80], name)


if __name__ == "__main__":
    unittest.main()
