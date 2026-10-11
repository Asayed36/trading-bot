import unittest
from datetime import date

import helpers  # noqa: F401  (puts the repo on the path)

from backtest import portfolio as pf
from backtest.engine import Sleeve, Trade


def sleeve(label, days, rets, trade_of_day, trades):
    s = Sleeve(label)
    s.days, s.ret, s.trade_of_day, s.trades = list(days), list(rets), list(trade_of_day), trades
    return s


def trade(label, ret, first, last, entry_i=0, exit_i=1):
    return Trade(label, entry_i, exit_i, 1.0, 1.0, "signal", ret, first, last)


class MeasureTests(unittest.TestCase):
    def test_drawdown_return_and_sharpe(self):
        r = [0.1, -0.2, 0.05]
        self.assertAlmostEqual(pf.total_return(r), 1.1 * 0.8 * 1.05 - 1)
        self.assertAlmostEqual(pf.max_drawdown(r), 0.88 / 1.1 - 1)
        self.assertEqual(pf.max_drawdown([0.1, 0.1]), 0.0)
        self.assertEqual(pf.sharpe([0.01, 0.01, 0.01]), 0.0)         # no variation
        self.assertGreater(pf.sharpe([0.01, 0.02, 0.0, 0.03]), 0)

    def test_profit_factor_win_rate_and_no_losses(self):
        trades = [("A", 0, trade("A", 0.1, 1, 2)), ("A", 1, trade("A", -0.05, 3, 4)), ("B", 0, trade("B", 0.2, 1, 2))]
        st = pf.trade_stats(trades)
        self.assertEqual(st["trades"], 3)
        self.assertAlmostEqual(st["win_rate"], 2 / 3)
        self.assertAlmostEqual(st["profit_factor"], 0.3 / 0.05)
        self.assertIsNone(pf.trade_stats([("A", 0, trade("A", 0.1, 1, 2))])["profit_factor"])
        self.assertIsNone(pf.trade_stats([])["win_rate"])

    def test_yearly_groups_by_calendar_year(self):
        d = lambda y, m, k: date(y, m, k).toordinal() - 719163
        days = [d(2023, 12, 30), d(2023, 12, 31), d(2024, 1, 1), d(2024, 1, 2)]
        y = pf.yearly(days, [0.1, 0.1, -0.1, 0.0])
        self.assertAlmostEqual(y[2023], 1.1 * 1.1 - 1)
        self.assertAlmostEqual(y[2024], -0.1)


class PairedTTests(unittest.TestCase):
    def run_of(self, rets):
        days = list(range(len(rets)))
        return pf.Run({"A": sleeve("A", days, rets, [-1] * len(rets), [])})

    def test_t_stat_uses_growth_rates_and_has_the_sign_of_the_gap(self):
        import math
        a, b = self.run_of([0.01, 0.02, 0.03]), self.run_of([0.0, 0.0, 0.0])
        d = [math.log1p(x) for x in (0.01, 0.02, 0.03)]
        mean = sum(d) / 3
        sd = math.sqrt(sum((x - mean) ** 2 for x in d) / 2)
        self.assertAlmostEqual(pf.paired_t(a, b), mean / (sd / math.sqrt(3)))
        self.assertAlmostEqual(pf.paired_t(b, a), -pf.paired_t(a, b))
        self.assertIsNone(pf.paired_t(a, a))                      # identical: no spread, undefined
        self.assertIsNone(pf.paired_t(self.run_of([0.1]), self.run_of([0.0])))

    def test_a_steadier_run_with_the_same_average_beats_a_wilder_one(self):
        # same arithmetic average (1%), but the wild one compounds to less: the sign follows total return
        steady = self.run_of([0.01] * 40)
        wild = self.run_of([0.2, -0.18] * 20)
        self.assertGreater(pf.total_return(steady.daily_returns()[1]), pf.total_return(wild.daily_returns()[1]))
        self.assertGreater(pf.paired_t(steady, wild), 0)


class RunTests(unittest.TestCase):
    def two_coins(self):
        a = sleeve("A", [10, 11, 12], [0.10, 0.00, -0.05], [0, 0, 0], [trade("A", 0.045, 10, 12)])
        b = sleeve("B", [11, 12], [0.00, 0.20], [-1, 0], [trade("B", 0.20, 12, 12)])
        return {"A": a, "B": b}

    def test_money_is_split_between_the_coins_that_exist_that_day(self):
        run = pf.Run(self.two_coins())
        days, r = run.daily_returns()
        self.assertEqual(days, [10, 11, 12])
        self.assertAlmostEqual(r[0], 0.10)                    # only A exists: all of it
        self.assertAlmostEqual(r[1], 0.0)
        self.assertAlmostEqual(r[2], (-0.05 + 0.20) / 2)

    def test_fixed_slots(self):
        run = pf.Run(self.two_coins(), slots=3)
        _, r = run.daily_returns()
        self.assertAlmostEqual(r[0], 0.10 / 3)
        self.assertAlmostEqual(r[2], 0.15 / 3)

    def test_best_trade_removal(self):
        run = pf.Run(self.two_coins())
        m = pf.measure(run)
        # A adds 0.10 - 0.025 = 0.075 to the portfolio; B adds 0.20 / 2 = 0.10: B is the best
        self.assertEqual(m["best_trade"]["coin"], "B")
        _, r = run.daily_returns(drop={("B", 0)})
        self.assertAlmostEqual(r[2], -0.05 / 2)               # B's day is gone, A's -5% stays
        self.assertAlmostEqual(m["total_return_without_best_1"], pf.total_return(r))
        self.assertLess(m["total_return_without_best_1"], m["total_return"])
        self.assertEqual(m["trades"], 2)
        self.assertAlmostEqual(m["total_return_without_best_3"], 0.0 + pf.total_return([0, 0, 0]))   # both trades removed


if __name__ == "__main__":
    unittest.main()
