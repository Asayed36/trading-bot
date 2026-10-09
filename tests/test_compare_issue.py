import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from compare import TITLE, post_issue
from screener.compare import MARKER, PASS_MARKER, checklist, report
from screener.paper_trader import JOURNAL_COLUMNS, append_row


class FakeGitHub:
    def __init__(self, issues):
        self.issues = issues
        self.created, self.closed = [], []

    def ensure_label(self, *args):
        pass

    def issues_with_label(self):
        return self.issues

    def create(self, title, body):
        self.created.append(title)
        return 99

    def close(self, number):
        self.closed.append(number)


class PostIssueTests(unittest.TestCase):
    def test_posts_and_closes_the_previous_day(self):
        gh = FakeGitHub([{"number": 5, "title": TITLE.format("2026-10-06"),
                          "body": MARKER.format("2026-10-06"), "state": "open"}])
        post_issue(gh, "2026-10-07", MARKER.format("2026-10-07"))
        self.assertEqual(gh.created, ["Daily comparison: 2026-10-07"])
        self.assertEqual(gh.closed, [5])

    def test_skips_when_an_issue_with_the_date_title_exists(self):
        # e.g. posted by the other run, or edited so the marker is gone
        gh = FakeGitHub([{"number": 331, "title": "Daily comparison: 2026-10-07",
                          "body": "edited", "state": "open"}])
        post_issue(gh, "2026-10-07", MARKER.format("2026-10-07"))
        self.assertEqual(gh.created, [])
        self.assertEqual(gh.closed, [])

    def test_skips_when_a_closed_issue_has_the_marker(self):
        gh = FakeGitHub([{"number": 331, "title": "something else",
                          "body": MARKER.format("2026-10-07"), "state": "closed"}])
        post_issue(gh, "2026-10-07", MARKER.format("2026-10-07"))
        self.assertEqual(gh.created, [])

    def test_another_day_with_a_similar_title_does_not_count(self):
        gh = FakeGitHub([{"number": 7, "title": "Daily comparison: 2026-10-07 (old)",
                          "body": "", "state": "open"}])
        post_issue(gh, "2026-10-07", MARKER.format("2026-10-07"))
        self.assertEqual(len(gh.created), 1)


def journal(folder, trades, open_positions=()):
    """A journal of closed trades: (day offset, P&L) each, bought at noon."""
    os.makedirs(folder, exist_ok=True)
    start = datetime(2026, 10, 1, 12)
    for n, (day, pnl) in enumerate(trades):
        when = start + timedelta(days=day)
        for action, at, value in (("BUY", when, 0.0), ("SELL", when + timedelta(hours=1), pnl)):
            append_row(os.path.join(folder, "journal.csv"), JOURNAL_COLUMNS, [
                at.strftime("%Y-%m-%d %H:%M:%S"), action, f"T{n}", f"addr{n}", "x", "1",
                "10.00", f"{value:.2f}", "0", "0", "DexScreener", ""])
    with open(os.path.join(folder, "positions.json"), "w") as fh:
        json.dump({"open_positions": list(open_positions)}, fh)


class ChecklistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def folder(self, name, trades, open_positions=()):
        path = os.path.join(self.tmp.name, name)
        journal(path, trades, open_positions)
        return path

    def test_pass_needs_all_four(self):
        good = [(i % 14, 1.0) for i in range(29)] + [(13, 10.0)]   # 30 trades, 14 days
        (row,) = checklist([("good", self.folder("good", good), 3)])
        self.assertEqual((row["closed"], row["days"], row["pnl"], row["without_1"],
                          row["without_3"]), (30, 14, 39.0, 29.0, 27.0))
        self.assertTrue(row["passed"])
        self.assertEqual(row["missing"], [])

    def test_what_is_missing(self):
        lucky = [(0, -1.0)] * 9 + [(1, 20.0)]                      # all from one trade
        (row,) = checklist([("lucky", self.folder("lucky", lucky), 3)])
        self.assertFalse(row["passed"])
        self.assertEqual(row["missing"], ["20 more closed trades",
                                          "not above $0 without the best trade",
                                          "trades on 12 more days"])
        (row,) = checklist([("empty", self.folder("empty", []), 3)])
        self.assertEqual(row["missing"], ["30 more closed trades", "P&L after costs not above $0",
                                          "not above $0 without the best trade",
                                          "trades on 14 more days"])

    def test_open_positions_and_stopped_strategies_left_out(self):
        path = self.folder("held", [(0, 5.0), (1, 2.0)], [{"address": "addr1"}])
        rows = checklist([("held", path, 3), ("old (stopped)", path, 3)])
        self.assertEqual([(r["name"], r["closed"], r["pnl"]) for r in rows], [("held", 1, 5.0)])

    def test_at_the_top_of_the_comparison(self):
        good = [(i % 14, 1.0) for i in range(29)] + [(13, 10.0)]
        body = report([("good", self.folder("good", good), 3),
                       ("bad", self.folder("bad", [(0, -2.0)]), 3)], "2026-10-14",
                      health=["### Health", ""])
        lines = body.splitlines()
        self.assertEqual(lines[3], "### Real-money checklist")
        self.assertIn("| good | 30 | 14 (10-01 – 10-14, 14 days) | $+39.00 | $+29.00 | $+27.00 | "
                      "**PASS** |", lines)
        self.assertIn("| bad | 1 | 1 (10-01 – 10-01, 1 day) | $-2.00 | $+0.00 | $+0.00 | "
                      "not yet: 29 more closed trades; P&L after costs not above $0; not above "
                      "$0 without the best trade; trades on 13 more days |", lines)
        self.assertIn(PASS_MARKER.format("good"), body)
        self.assertNotIn(PASS_MARKER.format("bad"), body)


class PassTitleTests(unittest.TestCase):
    def test_first_pass_is_named_in_the_title(self):
        gh = FakeGitHub([])
        post_issue(gh, "2026-10-20", "body", ["main (1 min) B"])
        self.assertEqual(gh.created, ["Daily comparison: 2026-10-20 — PASS: main (1 min) B"])

    def test_not_again_once_an_earlier_issue_said_so(self):
        gh = FakeGitHub([{"number": 5, "title": "Daily comparison: 2026-10-19 — PASS: B",
                          "body": MARKER.format("2026-10-19") + PASS_MARKER.format("B"),
                          "state": "open"},
                         {"number": 4, "title": "x", "body": PASS_MARKER.format("C"),
                          "state": "closed"}])
        post_issue(gh, "2026-10-20", "body", ["B", "C", "news"])
        self.assertEqual(gh.created, ["Daily comparison: 2026-10-20 — PASS: news"])
        self.assertEqual(gh.closed, [5])

    def test_a_pass_title_counts_as_posted(self):
        gh = FakeGitHub([{"number": 9, "title": "Daily comparison: 2026-10-20 — PASS: B",
                          "body": "edited", "state": "open"}])
        post_issue(gh, "2026-10-20", "body", ["B"])
        self.assertEqual(gh.created, [])


class WorkflowTests(unittest.TestCase):
    def test_runs_one_at_a_time(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, ".github/workflows/daily-comparison.yml")) as fh:
            text = fh.read()
        self.assertIn("\nconcurrency:\n  group: daily-comparison\n"
                      "  cancel-in-progress: false\n", text)


if __name__ == "__main__":
    unittest.main()
