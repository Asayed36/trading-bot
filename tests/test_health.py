"""Checks for the health section at the top of the daily comparison.
Run with:  python -m unittest -v
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import load_config, run  # noqa: E402
from screener.compare import report  # noqa: E402
from screener.demo import DemoApi, DemoNewsHttp, demo_rpc_factory  # noqa: E402
from screener.github_issues import GitHubIssues  # noqa: E402
from screener.health import OK, WARN, health_lines, record_health  # noqa: E402

CFG = load_config()
NOW = datetime(2026, 10, 2, 0, 7, tzinfo=timezone.utc)


def ago(**kw):
    return (NOW - timedelta(**kw)).isoformat()


class FakeGitHub:
    def __init__(self, runs=(), pushed=None, broken=False):
        self.runs, self.pushed, self.broken = list(runs), pushed, broken

    def workflow_runs(self, workflow, since):
        if self.broken:
            raise RuntimeError("GitHub answered with error 502")
        assert workflow == "screener.yml" and since == NOW - timedelta(hours=24)
        return self.runs

    def last_commit_time(self, path):
        assert path == "data/launch"
        return self.pushed


def run_(conclusion, minutes_ago):
    return {"conclusion": conclusion, "updated_at": ago(minutes=minutes_ago)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, data):
        path = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh)

    def healthy(self):
        for name in ("main", "early", "convergence", "news"):
            record_health(self.d, NOW - timedelta(minutes=4), {name: None})
        self.write("convergence/positions.json", {
            "helius": {"used": 1}, "tracked": [{"wallet": f"w{i}"} for i in range(5)],
            "list_updated": ago(days=1)})
        self.write("news/positions.json", {"sources": {
            "PR Newswire crypto": {"ok": True, "items": 20}}})
        return FakeGitHub([run_("success", 4), run_("success", 9)], pushed=NOW - timedelta(minutes=50))

    def lines(self, gh):
        text = "\n".join(health_lines(self.d, CFG, NOW, gh))
        rows = {line.split(" | ")[0][2:]: line for line in text.splitlines()
                if line.startswith("| ") and not line.startswith("| Check")}
        return text, rows


class HealthTests(Base):
    def test_all_ok(self):
        text, rows = self.lines(self.healthy())
        self.assertIn("**All checks OK.**", text)
        self.assertNotIn(WARN, text)
        self.assertIn("0 failed of 2; last successful run 2026-10-02 00:03 UTC (4 min ago)",
                      rows["Scheduled runs (last 24h)"])
        self.assertIn("5 tracked (list from 2026-10-01)", rows["convergence: wallets"])
        self.assertIn(f"{OK} 20 item(s)", rows["news: PR Newswire crypto"])
        self.assertIn("last push 2026-10-01 23:17 UTC (50 min ago)", rows["launch: server push"])

    def test_failed_runs_and_no_success(self):
        gh = self.healthy()
        gh.runs = [run_("failure", 5), run_("success", 10), run_("cancelled", 12)]
        text, rows = self.lines(gh)
        self.assertIn(f"{WARN} 1 failed of 3", rows["Scheduled runs (last 24h)"])
        self.assertIn("1 problem(s) need a look", text)
        gh.runs = [run_("failure", 5), run_("timed_out", 30)]
        _, rows = self.lines(gh)
        self.assertIn("2 failed of 2; no successful run in 24h", rows["Scheduled runs (last 24h)"])

    def test_stale_and_skipped_strategies(self):
        gh = self.healthy()
        record_health(self.d, NOW - timedelta(minutes=2), {"early": "GeckoTerminal down"})
        with open(os.path.join(self.d, "health.json")) as fh:
            data = json.load(fh)
        data["strategies"]["news"]["last_ok"] = ago(hours=3)
        self.write("health.json", data)
        text, rows = self.lines(gh)
        self.assertIn(WARN, rows["early: last successful run"])
        self.assertIn("skipped since 00:05 UTC: GeckoTerminal down",
                      rows["early: last successful run"])
        self.assertIn("(older than 60 min)", rows["news: last successful run"])
        self.assertIn(OK, rows["main: last successful run"])
        self.assertIn("2 problem(s)", text)
        # a later good run clears the error
        record_health(self.d, NOW - timedelta(minutes=1), {"early": None})
        _, rows = self.lines(gh)
        self.assertIn(OK, rows["early: last successful run"])

    def test_convergence_problems(self):
        gh = self.healthy()
        self.write("convergence/positions.json", {
            "helius": {"used": 1}, "tracked": [{"wallet": "w"}], "paused_until": ago(days=-3),
            "refresh": {"scored": {"a": {}}, "queue": ["b", "c"]}})
        _, rows = self.lines(gh)
        self.assertIn("1 tracked; rebuilding: 1 scored, 2 to go - fewer than 3",
                      rows["convergence: wallets"])
        self.assertIn(WARN, rows["convergence: Helius"])
        self.write("convergence/positions.json", {})
        _, rows = self.lines(gh)
        self.assertIn("HELIUS_API_KEY", rows["convergence: wallets"])

    def test_failing_news_source(self):
        gh = self.healthy()
        self.write("news/positions.json", {"sources": {
            "Chainlink blog": {"ok": False, "error": "not a valid feed | bad"}}})
        text, rows = self.lines(gh)
        self.assertIn(f"{WARN} failing: not a valid feed / bad", rows["news: Chainlink blog"])
        self.assertIn("> - news: Chainlink blog: failing", text)

    def test_launch_never_or_late(self):
        gh = self.healthy()
        gh.pushed = None
        _, rows = self.lines(gh)
        self.assertIn("no results pushed yet", rows["launch: server push"])
        gh.pushed = NOW - timedelta(hours=5)
        _, rows = self.lines(gh)
        self.assertIn("(older than 3 h)", rows["launch: server push"])
        self.assertIn(WARN, rows["launch: server push"])

    def test_launch_from_stats_without_github(self):
        self.healthy()
        self.write("launch/stats.json", {"2026-10-01 23:00": {"launches_seen": 9}})
        text, rows = self.lines(None)
        self.assertIn("latest hour in stats.json 2026-10-01 23:00 UTC", rows["launch: server push"])
        self.assertIn("not checked: no GitHub token", rows["Scheduled runs (last 24h)"])

    def test_github_down_doesnt_break_the_report(self):
        gh = self.healthy()
        gh.broken = True
        _, rows = self.lines(gh)
        self.assertIn("couldn't ask GitHub: GitHub answered with error 502",
                      rows["Scheduled runs (last 24h)"])

    def test_health_is_at_the_top_of_the_report(self):
        body = report([("main", self.d, 3)], "2026-10-01", health=["### Health (x)", ""])
        lines = body.splitlines()
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3], "### Health (x)")
        self.assertTrue(lines[5].startswith("| | main"))


class GitHubApiTests(unittest.TestCase):
    def test_workflow_runs_and_last_commit(self):
        def answer(json_body, next_url=None):
            links = {"next": {"url": next_url}} if next_url else {}
            return mock.Mock(status_code=200, json=lambda: json_body, links=links)

        gh = GitHubIssues("tok", "me/repo")
        with mock.patch("screener.github_issues.requests.request", side_effect=[
                answer({"workflow_runs": [{"id": 1}]}, "https://api.github.com/next"),
                answer({"workflow_runs": [{"id": 2}]}),
                answer([{"commit": {"committer": {"date": "2026-10-01T23:17:00Z"}}}])]) as req:
            runs = gh.workflow_runs("screener.yml", NOW - timedelta(hours=24))
            pushed = gh.last_commit_time("data/launch")
        self.assertEqual([r["id"] for r in runs], [1, 2])
        first = req.call_args_list[0].args[1]
        self.assertIn("/repos/me/repo/actions/workflows/screener.yml/runs?created=%3E%3D"
                      "2026-10-01T00:07:00Z", first)
        self.assertIn("/commits?path=data/launch&per_page=1", req.call_args_list[2].args[1])
        self.assertEqual(pushed, datetime(2026, 10, 1, 23, 17, tzinfo=timezone.utc))


class RecordTests(Base):
    def test_every_run_records_each_strategy(self):
        run(DemoApi(), CFG, self.d, out=lambda *a: None, rpc_factory=demo_rpc_factory(),
            news_http=DemoNewsHttp())
        with open(os.path.join(self.d, "health.json")) as fh:
            data = json.load(fh)
        self.assertEqual(sorted(data["strategies"]), ["convergence", "early", "main", "news"])
        self.assertTrue(all("last_ok" in s for s in data["strategies"].values()))

    def test_skipped_strategy_is_recorded(self):
        record_health(self.d, NOW, {"main": None, "news": "CoinGecko said 'too many requests'"})
        with open(os.path.join(self.d, "health.json")) as fh:
            data = json.load(fh)
        self.assertEqual(data["updated"], NOW.isoformat())
        self.assertNotIn("last_ok", data["strategies"]["news"])
        self.assertEqual(data["strategies"]["news"]["last_error"],
                         "CoinGecko said 'too many requests'")


if __name__ == "__main__":
    unittest.main()
