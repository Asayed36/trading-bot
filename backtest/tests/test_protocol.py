import json
import os
import tempfile
import unittest
from datetime import date

import helpers

from backtest import data, report, run as runner

START = date(2018, 1, 1)
TUNE_DAYS = (date(2023, 12, 31) - START).days + 1          # candles up to the end of the tuning period
TAIL_DAYS = 380                                            # 2024 and a bit of 2025


def build(tail_seed_offset):
    """Four coins: the same history up to 2023-12-31, a different future after it."""
    coins = []
    for k, label in enumerate(("BTC", "ETH", "SOL", "LINK")):
        prefix = helpers.random_daily(TUNE_DAYS, seed=10 + k, drift=0.0008)
        tail = helpers.random_daily(TAIL_DAYS, seed=500 + k + tail_seed_offset, price=prefix[-1][3],
                                    drift=-0.001, vol=0.04)
        coins.append(helpers.make_coin(label, START, prefix + tail))
    return coins


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = []
        original = runner.evaluate

        def spy(coins, variant, start, end):
            cls.seen.append((end, max(c.day[-1] for c in coins)))
            return original(coins, variant, start, end)

        runner.evaluate = spy
        try:
            cls.a = runner.run_protocol(build(0), log=lambda s: None)
            cls.calls_a = list(cls.seen)
            cls.b = runner.run_protocol(build(1000), log=lambda s: None)
        finally:
            runner.evaluate = original

    def test_the_future_cannot_change_the_choice_or_the_tuning_numbers(self):
        self.assertEqual(self.a["selection"], self.b["selection"])
        self.assertEqual(json.dumps(self.a["tuning"], sort_keys=True, default=str),
                         json.dumps(self.b["tuning"], sort_keys=True, default=str))
        self.assertEqual(self.a["trades"]["tuning"], self.b["trades"]["tuning"])
        # ... while the test period, of course, does depend on its own data
        self.assertNotEqual(self.a["test"]["benchmark"]["total_return"],
                            self.b["test"]["benchmark"]["total_return"])

    def test_tuning_runs_never_saw_a_later_candle(self):
        end_of_tuning = date(2023, 12, 31).toordinal() - data.EPOCH_ORDINAL
        tuning_calls = [c for c in self.calls_a if c[0] == date(2023, 12, 31)]
        test_calls = [c for c in self.calls_a if c[0] != date(2023, 12, 31)]
        # 13 variants for the tuning grid + 4 re-runs for the trade list, all on cut-off data
        self.assertEqual(len(tuning_calls), 13 + 4)
        self.assertTrue(all(last <= end_of_tuning for _, last in tuning_calls))
        self.assertTrue(all(last > end_of_tuning for _, last in test_calls))

    def test_the_test_period_is_run_once_for_the_chosen_variants_only(self):
        test_calls = [c for c in self.calls_a if c[0] != date(2023, 12, 31)]
        self.assertEqual(len(test_calls), 4)
        proto = self.a["protocol"]
        self.assertEqual(proto["test_evaluations_of_the_chosen_variants"], 4)
        self.assertEqual(proto["variants_tried"], 13)
        names = [(s["family"], s["name"]) for s in self.a["test"]["strategies"]]
        self.assertEqual(sorted(f for f, _ in names),
                         ["breakout", "mean reversion", "momentum", "trend following"])
        for family, name in names:
            self.assertEqual(self.a["selection"][family], name)

    def test_the_choice_follows_the_rule(self):
        for family, name in self.a["selection"].items():
            rows = [g for g in self.a["tuning"]["variants"] if g["family"] == family]
            best = max(g["metrics"]["sharpe"] for g in rows)
            chosen = next(g for g in rows if g["name"] == name)
            self.assertEqual(chosen["metrics"]["sharpe"], best)

    def test_outputs_and_a_summary_that_matches_the_numbers(self):
        with tempfile.TemporaryDirectory() as out:
            report.write_outputs(self.a, [{"coin": "BTC"}], {"made_at": "now", "fee_per_side": 0.001,
                                                             "slippage_majors": 0.0005, "slippage_others": 0.002,
                                                             "majors": ["BTC", "ETH", "SOL"]}, out)
            names = set(os.listdir(out))
            for f in ("SUMMARY.md", "results.json", "tuning_grid.csv", "test_results.csv", "trades_test.csv",
                      "trades_tuning.csv", "data_report.csv", "run_info.json"):
                self.assertIn(f, names)
            with open(os.path.join(out, "SUMMARY.md")) as fh:
                text = fh.read()
        beat = any(s["beats_buy_and_hold_on_return"] for s in self.a["test"]["strategies"])
        self.assertEqual("Nothing beat buy-and-hold" in text, not beat)
        self.assertIn("13 variants were tried", text)
        self.assertIn("once (4 runs)", text)


def fake_results(beats, tuning_beats, total=0.5, without_best=0.2, trades=40, t_stat=3.0):
    def strat(family, b, tb):
        m = {"total_return": total, "max_drawdown": -0.2, "sharpe": 1.0, "trades": trades,
             "win_rate": 0.5, "profit_factor": 1.5, "total_return_without_best_1": without_best,
             "total_return_without_best_3": 0.0, "yearly": {}}
        return {"family": family, "name": "x", "metrics": m, "excess_return": 0.1 if b else -0.1,
                "excess_t_stat": t_stat, "beats_buy_and_hold_on_return": b, "beats_buy_and_hold_on_sharpe": b,
                "smaller_drawdown_than_buy_and_hold": True, "tuning_metrics": m,
                "tuning_excess_return": 0.0, "tuning_beats_buy_and_hold_on_return": tb}
    bh = {"total_return": 0.3, "max_drawdown": -0.5, "sharpe": 0.5}
    return {"protocol": {"test_window": ["2024-01-01", "2026-10-09"]},
            "test": {"benchmark": bh, "strategies": [strat("a", beats, tuning_beats)]}}


class VerdictTests(unittest.TestCase):
    def test_nothing_beat_buy_and_hold(self):
        lines = report.verdicts(fake_results(False, False))
        self.assertTrue(lines[0].startswith("**Nothing beat buy-and-hold"))

    def test_a_winner_is_named_and_nothing_else_is_claimed(self):
        lines = "\n".join(report.verdicts(fake_results(True, True)))
        self.assertIn("Beat buy-and-hold on total return", lines)
        self.assertNotIn("Nothing beat", lines)
        self.assertNotIn("only in the tuning period", lines)

    def test_a_gap_that_could_be_luck_is_called_that(self):
        lines = "\n".join(report.verdicts(fake_results(True, True, t_stat=1.2)))
        self.assertIn("not clearly bigger than luck", lines)
        lines = "\n".join(report.verdicts(fake_results(True, True, t_stat=3.0)))
        self.assertNotIn("not clearly bigger than luck", lines)

    def test_works_only_in_the_tuning_period(self):
        lines = "\n".join(report.verdicts(fake_results(False, True)))
        self.assertIn("Worked only in the tuning period", lines)

    def test_one_trade_dependence_and_thin_samples_are_flagged(self):
        lines = "\n".join(report.verdicts(fake_results(True, True, total=0.5, without_best=-0.1, trades=12)))
        self.assertIn("Depended on one trade", lines)
        self.assertIn("Fewer than 30 trades", lines)


if __name__ == "__main__":
    unittest.main()
