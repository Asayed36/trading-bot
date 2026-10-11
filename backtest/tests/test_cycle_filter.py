import unittest
from datetime import date

import helpers
from test_strategies import coin_from_closes

from backtest import indicators as ind
from backtest import report, run as runner, strategies
from backtest.engine import Costs, simulate

ZERO = Costs(0.0, 0.0)


def btc_closes():
    """About 250 days of steady rise, a long fall, then a rise again."""
    return ([100 + 0.4 * i for i in range(260)] + [204 - 1.5 * i for i in range(120)]
            + [24 + 0.8 * i for i in range(140)])


class Const:
    """A stand-in regime: above() is True except on the days in `off`."""

    def __init__(self, off=(), always=True):
        self.off, self.always = set(off), always

    def above(self, day):
        return self.always and day not in self.off


class RegimeTests(unittest.TestCase):
    def test_the_flag_is_btcs_close_above_its_200_day_average(self):
        closes = btc_closes()
        btc = coin_from_closes(closes, "BTC")
        regime = strategies.Regime(btc)
        sma = ind.sma(closes, 200)
        for i, (day, c) in enumerate(zip(btc.day, closes)):
            self.assertEqual(regime.above(day), sma[i] is not None and c > sma[i], i)
        self.assertTrue(any(regime.flags) and not all(regime.flags[200:]))   # it does change

    def test_cash_until_btc_has_200_days(self):
        btc = coin_from_closes([100 + i for i in range(150)], "BTC")
        regime = strategies.Regime(btc)
        self.assertFalse(any(regime.flags))
        self.assertFalse(regime.above(btc.day[0] - 5))               # before its first candle

    def test_a_day_uses_nothing_later(self):
        closes = btc_closes()
        a = strategies.Regime(coin_from_closes(closes, "BTC"))
        other = closes[:300] + [c * 0.3 for c in closes[300:]]       # a different future
        b = strategies.Regime(coin_from_closes(other, "BTC"))
        self.assertEqual(a.flags[:300], b.flags[:300])
        self.assertNotEqual(a.flags, b.flags)

    def test_a_missing_day_uses_the_last_known_flag_and_crossings_are_counted(self):
        class Btc:
            c = [1.0] * 200 + [2.0, 0.5, 3.0]
            day = list(range(100, 300)) + [300, 301, 303]            # day 302 is missing
            def __len__(self):
                return len(self.c)
        regime = strategies.Regime(Btc())
        self.assertTrue(regime.above(300))
        self.assertFalse(regime.above(301))
        self.assertFalse(regime.above(302))                          # no candle: yesterday's flag
        self.assertTrue(regime.above(303))
        self.assertEqual(regime.switches(100, 303), 3)               # off->on, on->off, off->on
        self.assertAlmostEqual(regime.share_above(300, 303), 2 / 3)   # 300 and 303 of the 3 candles

    def test_btc_is_required(self):
        coin = coin_from_closes([100.0] * 300, "ETH")
        with self.assertRaises(ValueError):
            runner.btc_regime([coin])


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.closes = btc_closes()
        self.btc = coin_from_closes(self.closes, "BTC")
        self.regime = strategies.Regime(self.btc)

    def test_buy_and_hold_behind_the_filter_holds_only_after_a_true_close(self):
        coin = coin_from_closes(self.closes, "ETH")
        start, end = 205, len(self.closes) - 1
        s = simulate(coin, strategies.CycleFilter(strategies.BuyHold(), self.regime), start, end, ZERO)
        flags = self.regime.flags
        growth = 1.0
        for i in range(start, end + 1):
            if flags[i - 1]:
                growth *= self.closes[i] / self.closes[i - 1]
        got = 1.0
        for r in s.ret:
            got *= 1 + r
        self.assertAlmostEqual(got, growth, places=9)
        runs = sum(1 for i in range(start, end + 1) if flags[i - 1] and (i == start or not flags[i - 2]))
        self.assertEqual(len(s.trades), runs)
        # in cash (a zero return) on every day that began after a False close
        for day, r in zip(s.days, s.ret):
            i = coin.day.index(day)
            if not flags[i - 1] and (i == start or not flags[i - 2]):
                self.assertEqual(r, 0.0)

    def test_a_regime_that_is_always_true_changes_nothing(self):
        coin = coin_from_closes(self.closes, "ETH", wiggle=0.01)
        for make in (lambda: strategies.TrendFollowing((50,)), lambda: strategies.Breakout(20, 3),
                     lambda: strategies.MeanReversion("rsi", False), strategies.BuyHold):
            plain = simulate(coin, make(), 205, len(self.closes) - 1, Costs(0.001, 0.002))
            filt = simulate(coin, strategies.CycleFilter(make(), Const()), 205, len(self.closes) - 1,
                            Costs(0.001, 0.002))
            self.assertEqual(plain.ret, filt.ret)
            self.assertEqual([(t.entry_i, t.exit_i, t.reason) for t in plain.trades],
                             [(t.entry_i, t.exit_i, t.reason) for t in filt.trades])

    def test_a_regime_that_is_always_false_never_trades(self):
        coin = coin_from_closes(self.closes, "ETH", wiggle=0.01)
        for make in (lambda: strategies.TrendFollowing((50,)), lambda: strategies.Breakout(20, 3),
                     lambda: strategies.MeanReversion("rsi", False), strategies.BuyHold):
            s = simulate(coin, strategies.CycleFilter(make(), Const(always=False)), 205,
                         len(self.closes) - 1, Costs(0.001, 0.002))
            self.assertEqual(s.trades, [])
            self.assertTrue(all(r == 0.0 for r in s.ret))

    def test_a_position_is_sold_at_the_next_open_after_the_flag_turns_false(self):
        coin = coin_from_closes([100 + 0.5 * i for i in range(300)], "ETH")
        off_from = coin.day[250]
        regime = Const(off=range(off_from, coin.day[-1] + 1))
        s = simulate(coin, strategies.CycleFilter(strategies.TrendFollowing((50,)), regime), 205, 299, ZERO)
        (t,) = s.trades                                  # day 250's close is the first False one ...
        self.assertEqual(t.exit_i, 251)                  # ... so it is sold at day 251's open
        self.assertEqual(t.reason, "signal")
        plain = simulate(coin, strategies.TrendFollowing((50,)), 205, 299, ZERO)
        self.assertEqual(plain.trades[0].exit_i, 299)    # unfiltered: held to the end of the window

    def test_blocked_entries_resume_when_the_flag_returns(self):
        coin = coin_from_closes([100.0] * 60 + [100 + 2 * i for i in range(60)] + [220.0] * 40
                                + [220 + 3 * i for i in range(60)], "ETH", wiggle=0.002)
        window = range(coin.day[60], coin.day[130])
        s = simulate(coin, strategies.CycleFilter(strategies.Breakout(20, 3), Const(off=window)), 40,
                     len(coin) - 1, ZERO)
        entries = [t.entry_i for t in s.trades]
        self.assertTrue(entries)
        self.assertTrue(all(i - 1 >= 130 or i - 1 < 60 for i in entries))      # none decided inside it
        self.assertTrue(any(i > 130 for i in entries))
        plain = simulate(coin, strategies.Breakout(20, 3), 40, len(coin) - 1, ZERO)
        self.assertTrue(any(60 <= t.entry_i - 1 < 130 for t in plain.trades))

    def test_momentum_slots_sit_in_cash_while_the_flag_is_false(self):
        coin = coin_from_closes([100 + i for i in range(300)], "ETH")
        schedule = {d: True for d in coin.day}
        off = range(coin.day[220], coin.day[260])
        s = simulate(coin, strategies.CycleFilter(strategies.Scheduled("m", schedule), Const(off=off)),
                     205, 299, ZERO)
        for day, r in zip(s.days, s.ret):
            if coin.day[221] <= day <= coin.day[260]:
                self.assertEqual(r, 0.0)
        self.assertEqual(len(s.trades), 2)

    def test_costs_are_still_charged_on_every_fill(self):
        coin = coin_from_closes([100 + 0.5 * i for i in range(300)], "ETH")
        regime = Const(off=range(coin.day[250], coin.day[-1] + 1))
        free = simulate(coin, strategies.CycleFilter(strategies.BuyHold(), regime), 205, 299, ZERO)
        paid = simulate(coin, strategies.CycleFilter(strategies.BuyHold(), regime), 205, 299,
                        Costs(0.001, 0.002))
        self.assertLess(paid.trades[0].ret, free.trades[0].ret)
        self.assertEqual(paid.trades[0].entry_price, coin.o[205] * 1.002)

    def test_the_twin_keeps_the_family_and_says_so_in_its_name(self):
        f = strategies.CycleFilter(strategies.Breakout(20, 3), Const())
        self.assertEqual(f.family, "breakout")
        self.assertTrue(f.name.endswith(" + cycle filter"))


def metrics(ret, fall=-0.3, trades=40, without=None, yearly=None):
    return {"total_return": ret, "max_drawdown": fall, "sharpe": 1.0, "trades": trades,
            "win_rate": 0.5, "profit_factor": 1.5,
            "total_return_without_best_1": ret * 0.5 if without is None else without,
            "total_return_without_best_3": 0.0, "yearly": yearly or {}}


def twin(plain, filt, t):
    return {"return_difference": filt["total_return"] - plain["total_return"],
            "worst_fall_difference": filt["max_drawdown"] - plain["max_drawdown"],
            "trades_difference": filt["trades"] - plain["trades"], "t_stat": t}


def fake_cycle(tuning, test, t_tune=3.0, t_test=3.0, years=None):
    """One strategy ('a') and buy-and-hold; tuning/test = (plain return, filtered return)."""
    years = years or {}
    plain_tune = metrics(tuning[0], yearly=years.get("plain_tune"))
    filt_tune = metrics(tuning[1], fall=-0.2, yearly=years.get("filt_tune"))
    plain_test = metrics(test[0], yearly=years.get("plain_test"))
    filt_test = metrics(test[1], fall=-0.2, yearly=years.get("filt_test"))
    tw_tune, tw_test = twin(plain_tune, filt_tune, t_tune), twin(plain_test, filt_test, t_test)
    bh = metrics(0.5)
    return {
        "protocol": {"test_window": ["2024-01-01", "2026-10-09"], "tuning_window": ["2020-01-01", "2023-12-31"]},
        "regime": {"tuning": {"share_of_days_above": 0.55, "switches": 9},
                   "test": {"share_of_days_above": 0.6, "switches": 4}, "by_year": {2022: 0.1, 2024: 0.8}},
        "tuning": {"benchmark": bh, "filtered_benchmark": bh, "filtered_benchmark_vs_unfiltered":
                   twin(bh, bh, 0.0), "variants": [], "filtered_variants": []},
        "test": {"benchmark": bh, "filtered_benchmark": bh,
                 "filtered_benchmark_vs_unfiltered": twin(bh, bh, 0.0),
                 "strategies": [{"family": "a", "name": "x", "metrics": plain_test,
                                 "tuning_metrics": plain_tune}],
                 "filtered": [dict({"family": "a", "name": "x", "metrics": filt_test,
                                    "tuning_metrics": filt_tune,
                                    "tuning_vs_unfiltered": tw_tune}, **tw_test)]},
    }


class VerdictTests(unittest.TestCase):
    def lines(self, *a, **k):
        return "\n".join(report.cycle_verdicts(fake_cycle(*a, **k)))

    def test_a_gain_in_both_periods_beyond_luck(self):
        text = self.lines((1.0, 1.5), (0.2, 0.4))
        self.assertIn("a higher total return in **both** periods: a.", text)
        self.assertIn("Gains that pass the rough luck test", text)
        self.assertNotIn("Within luck", text)
        self.assertNotIn("only one of the two periods", text)

    def test_a_gain_in_only_one_period_is_said_plainly(self):
        text = self.lines((1.0, 1.5), (0.2, 0.1))
        self.assertIn("Only in 2020-2023: a.", text)
        self.assertIn("**The filter's return gain shows in only one of the two periods** for: a", text)
        text = self.lines((1.0, 0.8), (0.2, 0.4))
        self.assertIn("Only in the test period: a.", text)

    def test_a_gain_that_could_be_luck_is_called_that(self):
        text = self.lines((1.0, 1.5), (0.2, 0.4), t_tune=0.8, t_test=1.9)
        self.assertIn("**Within luck**", text)
        self.assertIn("a in 2020-2023", text)
        self.assertIn("t = 0.80", text)
        self.assertNotIn("Gains that pass", text)

    def test_no_gain_at_all(self):
        text = self.lines((1.0, 0.9), (0.2, 0.1))
        self.assertIn("did not raise the total return of any strategy in either period", text)
        self.assertIn("In neither: a, buy-and-hold" if False else "In neither: a", text)

    def test_a_clear_cost_is_reported(self):
        text = self.lines((1.0, 0.5), (0.2, 0.1), t_tune=-3.0, t_test=-0.5)
        self.assertIn("clearly cost return", text)
        self.assertIn("a in 2020-2023 (-50.0%, t = -3.00)", text)

    def test_a_gain_that_comes_from_one_year_is_flagged(self):
        years = {"plain_tune": {2022: -0.5, 2023: 0.4}, "filt_tune": {2022: -0.1, 2023: 0.35},
                 "plain_test": {2024: 0.3, 2025: 0.2}, "filt_test": {2024: 0.28, 2025: 0.19}}
        text = self.lines((1.0, 1.1), (0.2, 0.2), years=years)
        self.assertIn("single calendar year", text)
        self.assertIn("a (2022)", text)
        self.assertIn("had the higher return: a: 1 of 4", text)
        years = {"plain_tune": {2022: 0.0, 2023: 0.0}, "filt_tune": {2022: 0.1, 2023: 0.1},
                 "plain_test": {2024: 0.0}, "filt_test": {2024: 0.1}}
        self.assertNotIn("single calendar year", self.lines((1.0, 1.1), (0.2, 0.3), years=years))

    def test_the_crossings_and_time_in_cash_are_stated(self):
        text = self.lines((1.0, 1.5), (0.2, 0.4))
        self.assertIn("above its 200-day average on 55.0% of the days in 2020-2023 (9 crossings)", text)
        self.assertIn("60.0% in the test period (4 crossings)", text)
        self.assertIn("only 9 + 4 crossings", text)

    def test_the_summary_has_the_side_by_side_tables(self):
        results = fake_cycle((1.0, 1.5), (0.2, 0.4))
        text = "\n".join(report.cycle_sections(results))
        self.assertIn("| Strategy | Return | Return, filtered | Worst fall | Worst fall, filtered | Trades | "
                      "Trades, filtered | Without best trade | Without best trade, filtered |", text)
        self.assertIn("| a | +20.0% | +40.0% | -30.0% | -20.0% | 40 | 40 | +10.0% | +20.0% |", text)
        self.assertIn("| buy-and-hold |", text)
        self.assertIn("Calendar years", text)


if __name__ == "__main__":
    unittest.main()
