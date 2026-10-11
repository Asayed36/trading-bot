import unittest
from datetime import date, timedelta

import helpers

from backtest import data, strategies
from backtest.engine import Costs, simulate

START = date(2021, 1, 1)
ZERO = Costs(0.0, 0.0)


def coin_from_closes(closes, label="T", wiggle=0.0):
    daily, prev = [], closes[0]
    for c in closes:
        o = prev
        daily.append((o, max(o, c) * (1 + wiggle), min(o, c) * (1 - wiggle), c))
        prev = c
    return helpers.make_coin(label, START, daily)


class TrendTests(unittest.TestCase):
    def test_in_while_above_the_average_out_when_not(self):
        closes = [100.0] * 60 + [110.0] * 20 + [90.0] * 20      # the 50-day average lags the moves
        coin = coin_from_closes(closes)
        s = simulate(coin, strategies.TrendFollowing((50,)), 50, len(closes) - 1, ZERO)
        sma = __import__("backtest.indicators", fromlist=["sma"]).sma(closes, 50)
        first_above = next(i for i in range(50, len(closes)) if closes[i] > sma[i])
        first_below_after = next(i for i in range(first_above, len(closes)) if closes[i] <= sma[i])
        (t,) = s.trades
        self.assertEqual(t.entry_i, first_above + 1)             # decided at the close, filled next open
        self.assertEqual(t.exit_i, first_below_after + 1)
        self.assertEqual(t.reason, "signal")

    def test_both_averages_must_agree(self):
        rising = [100 + i * 0.5 for i in range(260)]
        coin = coin_from_closes(rising)
        both = simulate(coin, strategies.TrendFollowing((50, 200)), 200, 259, ZERO).trades
        only50 = simulate(coin, strategies.TrendFollowing((50,)), 200, 259, ZERO).trades
        self.assertEqual(len(both), 1)
        self.assertEqual(len(only50), 1)


class BreakoutTests(unittest.TestCase):
    def test_buys_a_new_high_and_the_stop_only_moves_up(self):
        closes = [100.0] * 40 + [102 + 2 * k for k in range(30)] + [160 - 6 * k for k in range(1, 20)]
        coin = coin_from_closes(closes, wiggle=0.002)
        strat = strategies.Breakout(20, 3)
        s = simulate(coin, strat, 30, len(closes) - 1, ZERO)
        self.assertGreaterEqual(len(s.trades), 1)
        t = s.trades[0]
        self.assertEqual(t.entry_i, 41)                          # 102 is the first close above the prior 20-day high
        self.assertEqual(t.reason, "stop")                       # the fall in the end hits the trailing stop
        self.assertGreater(t.exit_price, 100)                    # ... above where it was bought: the stop had risen
        # the stop never moves down
        strat.prepare(coin)
        seen = []
        for i in range(40, 70):
            d = strat.on_close(i, i > 40)
            if d.stop is not None:
                seen.append(d.stop)
        self.assertEqual(seen, sorted(seen))

    def test_no_breakout_in_a_flat_market(self):
        coin = coin_from_closes([100.0] * 100, wiggle=0.01)
        self.assertEqual(simulate(coin, strategies.Breakout(20, 2), 30, 99, ZERO).trades, [])


class MeanReversionTests(unittest.TestCase):
    def dip(self, n_after=40):
        # a long calm stretch with a two-day drop, then a recovery
        calm = [100.0 if i % 2 == 0 else 102.0 for i in range(120)]
        closes = calm + [95.0, 90.0] + [98.0, 101.0, 103.0] + calm[:n_after]
        return coin_from_closes(closes, wiggle=0.005), closes

    def test_buys_the_oversold_dip_and_sells_the_recovery(self):
        coin, closes = self.dip()
        s = simulate(coin, strategies.MeanReversion("rsi", False), 60, len(closes) - 1, ZERO)
        self.assertGreaterEqual(len(s.trades), 1)
        t = [x for x in s.trades if x.entry_i >= 120][0]
        self.assertEqual(t.entry_i, 122)                          # decided at the close of the 90
        self.assertEqual(t.reason, "signal")
        self.assertGreater(t.ret, 0)

    def test_the_adx_filter_can_block_a_trade(self):
        # a strong downtrend: RSI(2) is oversold all the time but ADX is high
        closes = [200 - i * 1.5 for i in range(120)]
        coin = coin_from_closes(closes, wiggle=0.002)
        free = simulate(coin, strategies.MeanReversion("rsi", False), 40, 119, ZERO).trades
        filtered = simulate(coin, strategies.MeanReversion("rsi", True), 40, 119, ZERO).trades
        self.assertGreater(len(free), 0)
        self.assertEqual(len(filtered), 0)

    def test_sold_after_ten_days_at_most(self):
        # oversold, then the price just sits there: no recovery, no stop hit
        closes = [100.0] * 80 + [98.0] + [97.9] * 40
        coin = coin_from_closes(closes, wiggle=0.001)
        s = simulate(coin, strategies.MeanReversion("rsi", False), 60, len(closes) - 1, ZERO)
        held = [t.exit_i - t.entry_i for t in s.trades if t.reason == "signal"]
        self.assertTrue(held and max(held) <= strategies.MEAN_REVERSION_MAX_DAYS + 1)


class MomentumTests(unittest.TestCase):
    def coins(self):
        out = []
        for label, drift in (("A", 0.02), ("B", 0.01), ("C", 0.005), ("D", -0.004), ("E", 0.0)):
            closes, p = [], 100.0
            for _ in range(260):
                p *= 1 + drift
                closes.append(p)
            out.append(coin_from_closes(closes, label))
        return out

    def test_the_three_strongest_are_held_weekly_from_a_sunday_close(self):
        coins = self.coins()
        sched = strategies.momentum_schedules(coins, positive_only=False)
        days = sorted(sched["A"])
        for d in days:
            self.assertEqual(date.fromordinal(data.EPOCH_ORDINAL + d).weekday(), 6)    # Sunday
        last = days[-1]
        self.assertEqual({l: sched[l][last] for l in sched},
                         {"A": True, "B": True, "C": True, "D": False, "E": False})

    def test_positive_only_leaves_a_slot_empty(self):
        coins = self.coins()
        plain = strategies.momentum_schedules(coins, positive_only=False)
        pos = strategies.momentum_schedules(coins, positive_only=True)
        # with D and E not among the top 3 nothing changes; make the top 3 include a loser
        coins2 = [c for c in coins if c.label in ("A", "D", "E")]
        plain2 = strategies.momentum_schedules(coins2, positive_only=False)
        pos2 = strategies.momentum_schedules(coins2, positive_only=True)
        last = sorted(plain2["A"])[-1]
        self.assertTrue(plain2["D"][last])
        self.assertFalse(pos2["D"][last])
        self.assertTrue(pos2["A"][last])
        self.assertEqual(plain["A"], pos["A"])

    def test_coins_without_200_days_are_not_ranked(self):
        coins = self.coins()
        short = coin_from_closes([100 + i for i in range(150)], "S")
        sched = strategies.momentum_schedules(coins + [short], False)
        self.assertEqual(sched["S"], {})

    def test_the_scheduled_strategy_follows_it(self):
        coins = self.coins()
        sched = strategies.momentum_schedules(coins, False)
        a = coins[0]
        s = simulate(a, strategies.Scheduled("x", sched["A"]), 210, 259, ZERO)
        self.assertGreaterEqual(len(s.trades), 1)
        for t in s.trades:
            self.assertEqual(date.fromordinal(data.EPOCH_ORDINAL + a.day[t.entry_i]).weekday(), 0)   # a Monday


class GridTests(unittest.TestCase):
    def test_thirteen_variants(self):
        from backtest.run import all_variants
        variants = all_variants()
        self.assertEqual(len(variants), 13)
        counts = {}
        for v in variants:
            counts[v.family] = counts.get(v.family, 0) + 1
        self.assertEqual(counts, {"trend following": 3, "breakout": 4, "mean reversion": 4, "momentum": 2})


if __name__ == "__main__":
    unittest.main()
