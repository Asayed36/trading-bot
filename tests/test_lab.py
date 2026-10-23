"""Tests for lab/run_lab.py: the time split, the cost math, missing prices, the seeded random
baseline, the verdict rules, filters, first-hit exits and the idea counter."""

import contextlib
import csv
import io
import os
import tempfile
import unittest

from lab import run_lab as lab

HEADER = ["first_checked_utc", "price_usd", "price_1h_usd", "time_1h_utc", "price_6h_usd",
          "time_6h_utc", "price_24h_usd", "time_24h_utc", "pool_age_minutes",
          "creator_ledger_launches", "price_change_1h_pct"]


def row(day, p0, p1h="", t1h="x", p6h="", t6h="", p24h="", t24h="", age="", ledger="", ch=""):
    return {"first_checked_utc": f"2026-10-{day:02d}T10:00:00", "price_usd": p0,
            "price_1h_usd": p1h, "time_1h_utc": t1h, "price_6h_usd": p6h, "time_6h_utc": t6h,
            "price_24h_usd": p24h, "time_24h_utc": t24h, "pool_age_minutes": age,
            "creator_ledger_launches": ledger, "price_change_1h_pct": ch}


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)


def token(**kw):
    return lab.Token(row(**{"day": 1, "p0": "1.0", **kw}))


class SplitTest(unittest.TestCase):
    def test_earliest_sixty_percent_learn(self):
        days = [f"2026-10-{d:02d}" for d in range(1, 11)]
        learn, check = lab.split_days(days * 3)
        self.assertEqual(learn, days[:6])
        self.assertEqual(check, days[6:])
        self.assertLess(max(learn), min(check))

    def test_order_does_not_matter_and_both_parts_never_empty(self):
        learn, check = lab.split_days(["2026-10-03", "2026-10-01"])
        self.assertEqual((learn, check), (["2026-10-01"], ["2026-10-03"]))

    def test_one_day_is_refused(self):
        with self.assertRaises(lab.LabError):
            lab.split_days(["2026-10-01"])


class CostTest(unittest.TestCase):
    def test_unchanged_price_loses_slippage_and_fee(self):
        pnl = lab.trade_pnl(1.0, 1.0, 1.5, 3.0, 10)
        self.assertAlmostEqual(pnl, 10 * (1 / 1.015 - 1) - 0.30, places=9)

    def test_doubling(self):
        self.assertAlmostEqual(lab.trade_pnl(1.0, 2.0, 1.5, 3.0, 10), 10 * (2 / 1.015 - 1) - 0.3)

    def test_costs_can_be_changed(self):
        self.assertAlmostEqual(lab.trade_pnl(1.0, 1.0, 0.0, 0.0, 10), 0.0)


class MissingPriceTest(unittest.TestCase):
    def test_asked_but_blank_is_total_loss(self):
        t = token(p1h="", t1h="2026-10-01T11:00:00")
        self.assertEqual(t.out["1h"], lab.LOST)
        self.assertEqual(lab.trade_pnl(1.0, t.out["1h"], 1.5, 3.0, 10), -10)

    def test_never_asked_is_unknown_not_zero(self):
        t = token(t1h="")
        self.assertIsNone(t.out["1h"])
        trades, universe, counts = lab.evaluate([t], {"exit": {"mode": "fixed", "at": "1h"}})
        self.assertEqual(trades, [])
        self.assertEqual(counts["exit_not_answered"], 1)

    def test_lost_trade_is_counted_as_minus_ten(self):
        t = token(p1h="", t1h="y")
        trades, _, counts = lab.evaluate([t], {"exit": {"mode": "fixed", "at": "1h"}})
        self.assertEqual([p for _, p in trades], [-10])
        self.assertEqual(counts["lost"], 1)


class FilterTest(unittest.TestCase):
    def test_numbers(self):
        t = token(age="90")
        self.assertTrue(lab.passes(t, {"pool_age_minutes": {"gt": 60}})[0])
        self.assertFalse(lab.passes(t, {"pool_age_minutes": {"lt": 60}})[0])

    def test_blank_value_is_left_out_and_reported(self):
        ok, unknown = lab.passes(token(age=""), {"pool_age_minutes": {"gt": 60}})
        self.assertFalse(ok)
        self.assertEqual(unknown, "pool_age_minutes")

    def test_eq_zero(self):
        self.assertTrue(lab.passes(token(ledger="0"), {"creator_ledger_launches": {"eq": 0}})[0])
        self.assertFalse(lab.passes(token(ledger="2"), {"creator_ledger_launches": {"eq": 0}})[0])


class FirstHitTest(unittest.TestCase):
    EX = {"mode": "first_hit", "take_profit_pct": 50, "stop_loss_pct": 30, "final": "24h"}

    def test_take_profit_at_first_checkpoint_reached(self):
        t = token(p1h="1.0", t1h="x", p6h="2.0", t6h="x", p24h="0.1", t24h="x")
        self.assertEqual(lab.exit_price(t, self.EX), 2.0)

    def test_stop_loss_first(self):
        t = token(p1h="0.5", t1h="x", p6h="3.0", t6h="x", p24h="3.0", t24h="x")
        self.assertEqual(lab.exit_price(t, self.EX), 0.5)


class BaselineTest(unittest.TestCase):
    def setUp(self):
        self.universe = [(f"2026-10-{d:02d}", float(p)) for d in (1, 2) for p in range(-5, 5)]
        self.trades = [("2026-10-01", 4.0), ("2026-10-02", 3.0)]

    def test_same_seed_same_result(self):
        a = lab.baseline(self.trades, self.universe, 300, seed=7)
        b = lab.baseline(self.trades, self.universe, 300, seed=7)
        self.assertEqual(a, b)

    def test_other_seed_can_differ(self):
        a = lab.baseline(self.trades, self.universe, 300, seed=7)
        b = lab.baseline(self.trades, self.universe, 300, seed=8)
        self.assertNotEqual(a["mean"], b["mean"])

    def test_best_possible_rule_beats_almost_all(self):
        self.assertGreater(lab.baseline(self.trades, self.universe, 500, seed=1)["beaten"], 0.9)

    def test_no_trades(self):
        self.assertIsNone(lab.baseline([], self.universe, 10)["beaten"])


GOOD = {"trades": 40, "profit": 50.0, "profit_without_best": 20.0, "days": 8}


class VerdictTest(unittest.TestCase):
    def test_pass(self):
        ok, failed, need = lab.verdict(GOOD, {"beaten": 0.96}, 1)
        self.assertTrue(ok)
        self.assertEqual((failed, need), ([], 0.95))

    def test_each_test_fails_alone(self):
        for key, value, word in (("trades", 29, "fewer than 30"), ("profit", -1.0, "not positive"),
                                 ("profit_without_best", -1.0, "without the best"),
                                 ("days", 6, "fewer than 7")):
            ok, failed, _ = lab.verdict({**GOOD, key: value}, {"beaten": 0.99}, 1)
            self.assertFalse(ok)
            self.assertEqual(len(failed), 1)
            self.assertIn(word, failed[0])

    def test_random_bar(self):
        self.assertFalse(lab.verdict(GOOD, {"beaten": 0.94}, 1)[0])
        self.assertFalse(lab.verdict(GOOD, {"beaten": None}, 1)[0])

    def test_stricter_after_tenth_idea(self):
        self.assertTrue(lab.verdict(GOOD, {"beaten": 0.97}, 10)[0])
        ok, failed, need = lab.verdict(GOOD, {"beaten": 0.97}, 11)
        self.assertFalse(ok)
        self.assertEqual(need, 0.99)
        self.assertIn("99%", failed[0])


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        rows = []
        for d in range(1, 11):
            for i in range(6):
                rows.append(row(d, "1.0", "1.5" if i % 2 else "0.5", age="90" if i % 2 else "10"))
        write_csv(os.path.join(self.tmp, "data/main-1min/candidates.csv"), rows)
        self.rule = os.path.join(self.tmp, "r.toml")
        with open(self.rule, "w") as fh:
            fh.write('name = "r"\n[filter.pool_age_minutes]\ngt = 60\n[exit]\nmode = "fixed"\nat = "1h"\n')
        self.res = os.path.join(self.tmp, "results")

    def run_it(self, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return lab.run_rule(self.rule, self.tmp, self.res, draws=50, seed=1, **kw)

    def test_runs_and_writes_results(self):
        self.run_it()
        self.assertTrue(os.path.exists(os.path.join(self.res, "r.md")))
        self.assertTrue(os.path.exists(os.path.join(self.res, "history.csv")))

    def test_rerun_of_same_file_keeps_its_idea_number(self):
        self.run_it()
        self.run_it()
        with open(os.path.join(self.res, "history.csv")) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual({r["idea_number"] for r in rows}, {"1"})

    def test_unknown_column_and_section_are_refused(self):
        with open(self.rule, "w") as fh:
            fh.write('name = "r"\n[filters.age]\ngt = 1\n')
        with self.assertRaises(lab.LabError):
            self.run_it()
        with open(self.rule, "w") as fh:
            fh.write('name = "r"\n[filter.nonsense_column]\ngt = 1\n')
        with self.assertRaises(lab.LabError):
            self.run_it()

    def test_cli_returns_one_on_bad_rule(self):
        with open(self.rule, "w") as fh:
            fh.write("not toml [")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lab.main([self.rule, "--data-dir", self.tmp,
                                       "--results-dir", self.res]), 1)


if __name__ == "__main__":
    unittest.main()
