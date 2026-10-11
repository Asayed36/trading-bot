import unittest
from datetime import date

import helpers

from backtest.engine import Costs, Decision, simulate, stop_fill
from backtest import strategies

FEE, SLIP = 0.001, 0.002
COSTS = Costs(FEE, SLIP)
START = date(2022, 1, 1)


class Scripted(strategies.Strategy):
    """Does what a dict says: {day index at whose close: Decision}."""
    name = "scripted"

    def __init__(self, script):
        self.script, self.seen = script, []

    def on_close(self, i, in_position):
        self.seen.append((i, in_position))
        return self.script.get(i, Decision())


def candles(*rows):
    return list(rows)


class FillTests(unittest.TestCase):
    def test_buys_and_sells_at_the_next_open_with_fee_and_slippage(self):
        daily = helpers.flat_days(8)
        daily[5] = (100, 112, 100, 110)
        for k in (6, 7):
            daily[k] = (110, 110, 110, 110)
        coin = helpers.make_coin("T", START, daily)
        s = simulate(coin, Scripted({1: Decision(buy=True), 5: Decision(sell=True)}), 1, 7, COSTS)
        (t,) = s.trades
        self.assertEqual((t.entry_i, t.exit_i, t.reason), (2, 6, "signal"))   # the day AFTER each decision
        self.assertAlmostEqual(t.entry_price, 100 * (1 + SLIP))
        self.assertAlmostEqual(t.exit_price, 110 * (1 - SLIP))
        expected = t.exit_price * (1 - FEE) / (t.entry_price * (1 + FEE)) - 1
        self.assertAlmostEqual(t.ret, expected, places=12)
        growth = 1.0
        for r in s.ret:
            growth *= 1 + r
        self.assertAlmostEqual(growth - 1, expected, places=12)               # the daily returns add up to it

    def test_a_decision_never_uses_a_price_of_the_day_it_fills(self):
        # the signal day closes at 100, the next day opens at 150: the fill is 150, not 100
        daily = helpers.flat_days(5)
        daily[2] = (150, 150, 150, 150)
        daily[3] = daily[4] = (150, 150, 150, 150)
        coin = helpers.make_coin("T", START, daily)
        s = simulate(coin, Scripted({1: Decision(buy=True)}), 1, 4, Costs(0, 0))
        self.assertAlmostEqual(s.trades[0].entry_price, 150)

    def test_open_position_is_sold_at_the_close_of_the_last_day(self):
        daily = helpers.flat_days(6)
        daily[5] = (100, 121, 100, 120)
        coin = helpers.make_coin("T", START, daily)
        s = simulate(coin, Scripted({0: Decision(buy=True)}), 1, 5, COSTS)
        (t,) = s.trades
        self.assertEqual((t.exit_i, t.reason), (5, "end of window"))
        self.assertAlmostEqual(t.exit_price, 120 * (1 - SLIP))
        self.assertEqual(len(s.ret), 5)

    def test_flat_days_return_zero_and_the_first_order_comes_from_the_day_before(self):
        coin = helpers.make_coin("T", START, helpers.flat_days(6))
        strat = Scripted({})
        s = simulate(coin, strat, 2, 5, COSTS)
        self.assertEqual(s.ret, [0.0] * 4)
        self.assertEqual(strat.seen[0], (1, False))          # decided at the close of day i_start - 1
        self.assertEqual(s.trade_of_day, [-1] * 4)
        # and an order decided then is filled at the open of i_start
        s = simulate(coin, Scripted({1: Decision(buy=True)}), 2, 5, COSTS)
        self.assertEqual(s.trades[0].entry_i, 2)


class StopTests(unittest.TestCase):
    def coin(self, day3, hourly=None):
        daily = helpers.flat_days(6)
        daily[3] = day3
        return helpers.make_coin("T", START, daily, hourly)

    def run_stop(self, coin, stop=95.0):
        return simulate(coin, Scripted({1: Decision(buy=True, stop=stop)}), 1, 5, COSTS)

    def test_a_gap_below_the_stop_fills_at_the_open_not_the_stop(self):
        s = self.run_stop(self.coin((90, 91, 88, 89)))
        (t,) = s.trades
        self.assertEqual((t.reason, t.exit_i), ("stop", 3))
        self.assertAlmostEqual(t.exit_price, 90 * (1 - SLIP))          # the open, worse than the 95 stop

    def test_crossing_the_stop_inside_the_day_fills_at_the_stop(self):
        hourly = {3: helpers.hours_for_day(100, 100, 94, 96)}          # falls through 95 in hour 6
        s = self.run_stop(self.coin((100, 100, 94, 96), hourly))
        (t,) = s.trades
        self.assertEqual(t.reason, "stop")
        self.assertAlmostEqual(t.exit_price, 95 * (1 - SLIP))

    def test_a_gap_between_two_hours_fills_at_that_hours_open(self):
        bars = [(100, 100.5, 99.5, 100)] * 6 + [(93, 93.5, 92, 93)] + [(93, 93.5, 92.5, 93)] * 17
        s = self.run_stop(self.coin((100, 100.5, 92, 93), {3: bars}))
        (t,) = s.trades
        self.assertAlmostEqual(t.exit_price, 93 * (1 - SLIP))

    def test_the_stop_also_works_on_the_day_of_the_buy(self):
        daily = helpers.flat_days(6)
        daily[2] = (100, 100, 90, 96)                                  # bought at this open, stopped the same day
        coin = helpers.make_coin("T", START, daily)
        (t,) = simulate(coin, Scripted({1: Decision(buy=True, stop=95)}), 1, 5, COSTS).trades
        self.assertEqual((t.entry_i, t.exit_i, t.reason), (2, 2, "stop"))
        self.assertAlmostEqual(t.exit_price, 95 * (1 - SLIP))

    def test_entry_below_the_stop_is_stopped_at_once_with_both_costs(self):
        daily = helpers.flat_days(6)
        daily[2] = (92, 92, 92, 92)
        daily[3] = daily[4] = daily[5] = (92, 92, 92, 92)
        coin = helpers.make_coin("T", START, daily)
        (t,) = simulate(coin, Scripted({1: Decision(buy=True, stop=95)}), 1, 5, COSTS).trades
        self.assertEqual((t.entry_i, t.exit_i), (2, 2))
        self.assertLess(t.ret, 0)
        self.assertAlmostEqual(t.entry_price, 92 * (1 + SLIP))
        self.assertAlmostEqual(t.exit_price, 92 * (1 - SLIP))

    def test_without_hourly_candles_the_daily_ones_are_used(self):
        coin = self.coin((90, 91, 88, 89))
        coin.day_hours[3] = (coin.day_hours[3][0], coin.day_hours[3][0])      # no hourly data that day
        self.assertAlmostEqual(stop_fill(coin, 3, 95.0), 90.0)
        coin2 = self.coin((100, 100, 94, 96))
        coin2.day_hours[3] = (coin2.day_hours[3][0], coin2.day_hours[3][0])
        self.assertAlmostEqual(stop_fill(coin2, 3, 95.0), 95.0)
        self.assertIsNone(stop_fill(coin2, 2, 95.0))                          # a day that never reached it


class NoLookaheadTests(unittest.TestCase):
    """What a strategy decides at a close must not change if later candles change."""

    def decisions(self, coin, make, upto):
        strat = make()
        strat.prepare(coin)
        out = []
        for i in range(200, upto):
            d = strat.on_close(i, False)
            out.append((d.buy, d.sell, d.stop))
        return out

    def test_every_family(self):
        a = helpers.random_walk("T", START, 420, seed=3)
        b = helpers.random_walk("T", START, 420, seed=3)
        # change everything after day 350
        for k in range(350, 420):
            b.c[k] *= 1.4
            b.h[k] *= 1.4
            b.l[k] *= 0.6
            b.o[k] *= 0.8
        makers = [lambda: strategies.TrendFollowing((50, 200)), lambda: strategies.Breakout(20, 3),
                  lambda: strategies.MeanReversion("rsi", True), lambda: strategies.MeanReversion("laguerre", False)]
        for make in makers:
            self.assertEqual(self.decisions(a, make, 350), self.decisions(b, make, 350), make().name)

    def test_momentum_schedule_uses_only_the_past(self):
        coins_a = [helpers.random_walk(l, START, 420, seed=s) for l, s in (("A", 1), ("B", 2), ("C", 3), ("D", 4))]
        coins_b = [helpers.random_walk(l, START, 420, seed=s) for l, s in (("A", 1), ("B", 2), ("C", 3), ("D", 4))]
        for c in coins_b:
            for k in range(350, 420):
                c.c[k] *= 0.5
        sa = strategies.momentum_schedules(coins_a, True)
        sb = strategies.momentum_schedules(coins_b, True)
        cut = coins_a[0].day[349]
        for label in sa:
            self.assertEqual({d: v for d, v in sa[label].items() if d <= cut},
                             {d: v for d, v in sb[label].items() if d <= cut})


if __name__ == "__main__":
    unittest.main()
