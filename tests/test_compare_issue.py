import os
import unittest

from compare import TITLE, post_issue
from screener.compare import MARKER


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


class WorkflowTests(unittest.TestCase):
    def test_runs_one_at_a_time(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, ".github/workflows/daily-comparison.yml")) as fh:
            text = fh.read()
        self.assertIn("\nconcurrency:\n  group: daily-comparison\n"
                      "  cancel-in-progress: false\n", text)


if __name__ == "__main__":
    unittest.main()
