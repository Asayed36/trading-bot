"""Checks for the server's paper-run trigger (deploy/trigger_paper_run.py),
with a made-up GitHub instead of the real one.
Run with:  python -m unittest -v
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "trigger_paper_run", os.path.join(HERE, "deploy", "trigger_paper_run.py"))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

NOW = datetime(2026, 10, 3, 21, 0, tzinfo=timezone.utc)
TOKEN = "github_pat_SECRETVALUE"


def run_(minutes_ago, status="completed", event="schedule"):
    when = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return {"status": status, "event": event, "created_at": when, "run_started_at": when}


class FakeResponse:
    def __init__(self, status, body=None):
        self.status, self._body = status, body

    def read(self):
        return b"" if self._body is None else json.dumps(self._body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def issue(day, number=1):
    return {"number": number, "title": f"Daily comparison: {day}",
            "body": f"<!-- daily-comparison: {day} -->\n# Daily comparison"}


class FakeGitHub:
    def __init__(self, runs, fail=None, issues=(), daily_runs=(), issues_need_no_token=False):
        self.runs, self.fail, self.requests = runs, fail, []
        self.issues, self.daily_runs = list(issues), list(daily_runs)
        self.issues_need_no_token = issues_need_no_token

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.fail:
            raise self.fail
        if req.get_method() == "GET" and "/issues?" in req.full_url:
            if self.issues_need_no_token and req.get_header("Authorization"):
                raise urllib.error.HTTPError(req.full_url, 403, "Resource not accessible by "
                                             "personal access token", {}, io.BytesIO(b""))
            return FakeResponse(200, self.issues)
        if req.get_method() == "GET":
            daily = "daily-comparison.yml" in req.full_url
            return FakeResponse(200, {"workflow_runs": self.daily_runs if daily else self.runs})
        return FakeResponse(204)


class DecideTests(unittest.TestCase):
    def test_skips_when_a_run_is_queued_or_running(self):
        for status in ("queued", "in_progress"):
            start, why = tr.decide([run_(30, status=status), run_(40)], NOW)
            self.assertFalse(start)
            self.assertIn(status, why)

    def test_skips_when_a_run_started_recently(self):
        start, why = tr.decide([run_(3), run_(20)], NOW)
        self.assertEqual((start, why), (False, "skipped: a run started 3 min ago"))

    def test_starts_when_the_last_run_is_old_or_there_is_none(self):
        self.assertEqual(tr.decide([run_(9)], NOW), (True, "the last run started 9 min ago"))
        self.assertTrue(tr.decide([run_(240, event="workflow_dispatch")], NOW)[0])
        self.assertEqual(tr.decide([], NOW), (True, "no earlier run found"))


class TriggerTests(unittest.TestCase):
    def test_starts_the_workflow_on_main(self):
        gh, lines = FakeGitHub([run_(30)]), []
        self.assertTrue(tr.trigger(TOKEN, NOW, gh, lines.append))
        get, post = gh.requests
        self.assertEqual(get.full_url, "https://api.github.com/repos/Asayed36/trading-bot/"
                                       "actions/workflows/screener.yml/runs?per_page=5")
        self.assertEqual((post.get_method(), post.full_url, json.loads(post.data)),
                         ("POST", "https://api.github.com/repos/Asayed36/trading-bot/actions/"
                                  "workflows/screener.yml/dispatches", {"ref": "main"}))
        self.assertEqual(post.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertEqual(post.get_header("Content-type"), "application/json")   # else HTTP 415
        self.assertEqual(lines, ["started Paper trading run on main "
                                 "(the last run started 30 min ago)"])

    def test_does_nothing_after_a_recent_run(self):
        gh, lines = FakeGitHub([run_(2)]), []
        self.assertFalse(tr.trigger(TOKEN, NOW, gh, lines.append))
        self.assertEqual([r.get_method() for r in gh.requests], ["GET"])   # no start request

    def test_expired_token_says_so_without_showing_it(self):
        err = urllib.error.HTTPError("u", 401, "Bad credentials", {}, io.BytesIO(b""))
        with self.assertRaises(tr.TriggerError) as ctx:
            tr.trigger(TOKEN, NOW, FakeGitHub([], fail=err), lambda *_: None)
        self.assertIn("expired or lacks permission", str(ctx.exception))
        self.assertIn("Actions: Read and write", str(ctx.exception))
        self.assertNotIn("SECRETVALUE", str(ctx.exception))

    def test_unreachable_github(self):
        with self.assertRaises(tr.TriggerError) as ctx:
            tr.trigger(TOKEN, NOW, FakeGitHub([], fail=urllib.error.URLError("no network")),
                       lambda *_: None)
        self.assertIn("couldn't reach GitHub", str(ctx.exception))

    def test_token_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dispatch-token")
            with self.assertRaises(tr.TriggerError):
                tr.read_token(path)                       # missing
            with open(path, "w") as fh:
                fh.write(f"{TOKEN}\n")
            self.assertEqual(tr.read_token(path), TOKEN)


class DailyComparisonTests(unittest.TestCase):
    AFTER = datetime(2026, 10, 4, 0, 40, tzinfo=timezone.utc)

    def posts(self, gh):
        return [r for r in gh.requests if r.get_method() == "POST"]

    def test_starts_the_comparison_when_yesterdays_issue_is_missing(self):
        gh, lines = FakeGitHub([], issues=[issue("2026-10-02")]), []
        self.assertTrue(tr.trigger_daily(TOKEN, self.AFTER, gh, lines.append))
        (post,) = self.posts(gh)
        self.assertEqual((post.full_url, json.loads(post.data)),
                         ("https://api.github.com/repos/Asayed36/trading-bot/actions/workflows/"
                          "daily-comparison.yml/dispatches", {"ref": "main"}))
        self.assertEqual(post.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertEqual(lines, ["started Daily strategy comparison on main "
                                 "(the issue for 2026-10-03 wasn't posted)"])
        lookup = gh.requests[0].full_url
        self.assertIn("/issues?labels=daily-comparison&state=all", lookup)

    def test_nothing_when_the_issue_is_posted_or_before_0030(self):
        gh, lines = FakeGitHub([], issues=[issue("2026-10-03"), issue("2026-10-02")]), []
        self.assertFalse(tr.trigger_daily(TOKEN, self.AFTER, gh, lines.append))
        self.assertEqual((self.posts(gh), lines), ([], []))
        gh = FakeGitHub([])
        early = datetime(2026, 10, 4, 0, 29, tzinfo=timezone.utc)
        self.assertFalse(tr.trigger_daily(TOKEN, early, gh, lines.append))
        self.assertEqual(gh.requests, [])                     # doesn't even ask GitHub
        late = datetime(2026, 10, 4, 23, 55, tzinfo=timezone.utc)
        self.assertTrue(tr.trigger_daily(TOKEN, late, FakeGitHub([]), lines.append))

    def test_a_running_or_recent_comparison_run_is_left_alone(self):
        def at(minutes_ago, status="completed"):
            when = (self.AFTER - timedelta(minutes=minutes_ago)).isoformat()
            return {"status": status, "created_at": when, "run_started_at": when}

        for runs, why in (([at(5, "queued")], "a run is already queued"),
                          ([at(30)], "a run started 30 min ago")):
            gh, lines = FakeGitHub([], daily_runs=runs), []
            self.assertFalse(tr.trigger_daily(TOKEN, self.AFTER, gh, lines.append))
            self.assertEqual(self.posts(gh), [])
            self.assertIn(why, lines[0])
        # An hour after a run that didn't post it: try again.
        gh = FakeGitHub([], daily_runs=[at(61)])
        self.assertTrue(tr.trigger_daily(TOKEN, self.AFTER, gh, lambda *_: None))

    def test_issue_lookup_without_the_token_when_github_refuses_it(self):
        gh = FakeGitHub([], issues=[issue("2026-10-03")], issues_need_no_token=True)
        self.assertFalse(tr.trigger_daily(TOKEN, self.AFTER, gh, lambda *_: None))
        first, second = gh.requests
        self.assertEqual(first.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertIsNone(second.get_header("Authorization"))
        self.assertEqual(self.posts(gh), [])

    def test_marker_matches_compare(self):
        sys.path.insert(0, HERE)
        from screener.compare import MARKER
        self.assertEqual(tr.DAILY_MARKER, MARKER)
        self.assertEqual(tr.DAILY_LABEL, __import__("compare").LABEL)

    def test_main_runs_both_and_one_failure_doesnt_stop_the_other(self):
        calls = []
        real = tr.trigger, tr.trigger_daily, tr.read_token

        def broken(token):
            calls.append("paper")
            raise tr.TriggerError("GitHub said 500")
        try:
            tr.trigger, tr.read_token = broken, lambda: TOKEN
            tr.trigger_daily = lambda token: calls.append("daily")
            with unittest.mock.patch("sys.stderr", io.StringIO()) as err:
                self.assertEqual(tr.main(), 1)
            self.assertEqual(calls, ["paper", "daily"])
            self.assertIn("could not start Paper trading run: GitHub said 500", err.getvalue())
        finally:
            tr.trigger, tr.trigger_daily, tr.read_token = real


class UnitFileTests(unittest.TestCase):
    def test_timer_and_service(self):
        with open(os.path.join(HERE, "deploy", "paper-run-trigger.timer")) as fh:
            timer = fh.read()
        with open(os.path.join(HERE, "deploy", "paper-run-trigger.service")) as fh:
            service = fh.read()
        self.assertIn("OnCalendar=*:0/10", timer)
        self.assertIn("User=bot", service)
        self.assertIn("ExecStart=/home/bot/trading-bot/deploy/trigger_paper_run.sh", service)
        self.assertTrue(os.access(os.path.join(HERE, "deploy", "trigger_paper_run.sh"), os.X_OK))


if __name__ == "__main__":
    unittest.main()
