"""Checks for the automatic repair (screener/repair.py, repair.py), with a
made-up GitHub and a made-up Claude Code: nothing is sent anywhere.
Run with:  python -m unittest -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import HERE, load_config  # noqa: E402
from screener import repair  # noqa: E402

CFG = load_config()
NOW = datetime(2026, 10, 6, 0, 37, tzinfo=timezone.utc)
DAY = "2026-10-06"
CODE = {"check": "robinhood: geckoterminal", "detail": "failing: 3 call(s), 3 failed: boom",
        "summary": "robinhood: geckoterminal: failing"}
SERVER = {"check": "momentum: server", "detail": "feed last up 5 h ago (older than 3 h)",
          "summary": "momentum: server: late"}
SECRET = {"check": "convergence: wallets", "detail": "not active: is the HELIUS_API_KEY "
          "secret set?", "summary": "convergence: wallets: not active"}


class FakeGitHub:
    def __init__(self):
        self.issues, self.comments, self.pulls, self.labels = [], [], [], set()
        self.fail_pull = None

    def ensure_label(self, name, *a):
        self.labels.add(name)

    def issues_with_label(self):
        return [dict(i) for i in self.issues]

    def create(self, title, body, labels=None):
        n = len(self.issues) + 1
        self.issues.append({"number": n, "title": title, "body": body, "state": "open",
                            "labels": [{"name": x} for x in labels or []]})
        return n

    def _get(self, n):
        return next(i for i in self.issues if i["number"] == n)

    def issue(self, n):
        return dict(self._get(n))

    def set_body(self, n, body):
        self._get(n)["body"] = body

    def add_labels(self, n, labels):
        self._get(n)["labels"] += [{"name": x} for x in labels]

    def comment(self, n, body):
        self.comments.append((n, body))

    def create_pull(self, title, head, base, body, draft=True):
        if self.fail_pull:
            raise self.fail_pull
        self.pulls.append({"title": title, "head": head, "base": base, "body": body,
                           "draft": draft})
        return "https://github.com/o/r/pull/9"


class IssueTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(os.path.join(self.tmp.name, "health.json"), "w") as fh:
            json.dump({"strategies": {"robinhood": {
                "last_ok": "2026-10-05T20:00:00+00:00", "error_at": "2026-10-05T23:00:00",
                "last_error": "GeckoTerminal said 'too many requests'"}}}, fh)

    def open(self, problems, now=NOW):
        lines = []
        repair.open_issues(self.gh, problems, self.tmp.name, now,
                           [{"run_number": 7, "html_url": "https://x/runs/7",
                             "conclusion": "failure"}], out=lines.append)
        return lines

    def test_kinds(self):
        self.assertEqual(repair.kind(CODE)[0], "code")
        self.assertEqual(repair.kind(SERVER)[0], "server")
        self.assertEqual(repair.kind(SECRET)[0], "settings")
        for check in ("launch: server push", "main (1 min): server",
                      "news (listings): Binance listings"):
            self.assertEqual(repair.kind({"check": check, "detail": "x"})[0], "server", check)

    def test_one_issue_per_problem_with_its_details(self):
        lines = self.open([CODE, SERVER, SECRET])
        self.assertEqual(len(self.gh.issues), 3)
        code, server, secret = self.gh.issues
        self.assertEqual(code["title"], "Repair: robinhood: geckoterminal")
        self.assertEqual([x["name"] for x in code["labels"]], ["repair", "repair-ready"])
        for text in ("<!-- repair-problem: robinhood: geckoterminal -->", "failing: 3 call(s)",
                     "GeckoTerminal said 'too many requests'", "[7](https://x/runs/7)",
                     "`screener/robinhood.py`", "`[robinhood]` in `config.toml`",
                     "draft pull request", f"**Last seen:** {DAY}"):
            self.assertIn(text, code["body"])
        # server and settings problems: left to you, and the issue says why
        self.assertEqual([x["name"] for x in server["labels"]], ["repair", "needs-you"])
        self.assertIn("Not attempted automatically:** this runs on your own server",
                      server["body"])
        self.assertIn("a secret, a setting or a limit", secret["body"])
        self.assertIn("#2 opened (needs you): momentum: server", lines)

    def test_late_strategies_go_into_the_scheduled_runs_issue(self):
        runs = {"check": "Scheduled runs (last 24h)", "detail": "5 failed of 9"}
        late = {"check": "news: last successful run", "detail": "2026-10-05 20:00 (older "
                "than 60 min)"}
        broken = {"check": "robinhood: last successful run", "detail": "20:00; skipped since "
                  "21:00 UTC: boom"}
        self.open([runs, late, broken])
        self.assertEqual([i["title"] for i in self.gh.issues],
                         ["Repair: Scheduled runs (last 24h)",
                          "Repair: robinhood: last successful run"])
        self.assertIn("Probably because of this (late, with no error of their own): news: "
                      "last successful run: 2026-10-05 20:00", self.gh.issues[0]["body"])
        # without failing runs, a late strategy is its own problem
        self.assertEqual(repair.group([late]), [late])

    def test_a_problem_still_there_updates_its_issue(self):
        self.open([CODE])
        self.open([CODE], now=NOW.replace(day=7))
        self.assertEqual(len(self.gh.issues), 1)
        self.assertIn("**Last seen:** 2026-10-07 (seen on 2 days): failing",
                      self.gh.issues[0]["body"])
        self.open([CODE], now=NOW.replace(day=7))              # same day again: unchanged
        self.assertIn("seen on 2 days", self.gh.issues[0]["body"])
        # closed by you, then back: a new issue (and a new attempt)
        self.gh.issues[0]["state"] = "closed"
        self.open([CODE], now=NOW.replace(day=9))
        self.assertEqual(len(self.gh.issues), 2)


class PickTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        for p in (CODE, dict(CODE, check="news: PR Newswire"), SERVER):
            k, why = repair.kind(p)
            self.gh.create(repair.issue_title(p), repair.issue_body(p, k, why, [], DAY),
                           labels=["repair", "repair-ready" if k == "code" else "needs-you"])

    def pick(self, cfg=CFG, wanted=None):
        lines = []
        return repair.pick(self.gh, cfg, NOW, wanted, out=lines.append), lines

    def test_oldest_ready_issue_once_per_issue_and_per_day(self):
        self.assertEqual(self.pick()[0], 1)
        with tempfile.TemporaryDirectory() as d:
            repair.start(self.gh, 1, NOW, "https://x/run", folder=d)
            with open(os.path.join(d, ".repair", "task.md")) as fh:
                task = fh.read()
        self.assertIn("Paper trading only", task)
        self.assertIn("# Repair: robinhood: geckoterminal (issue #1)", task)
        self.assertNotIn("repair-problem", task)
        self.assertIn("repair-attempted", [x["name"] for x in self.gh.issues[0]["labels"]])
        # one a day: #2 waits for tomorrow
        number, lines = self.pick()
        self.assertIsNone(number)
        self.assertIn("already 1 attempt(s)", lines[0])
        tomorrow = repair.pick(self.gh, CFG, NOW.replace(day=7), out=lambda *a: None)
        self.assertEqual(tomorrow, 2)                       # never #1 again

    def test_daily_dollar_cap(self):
        cfg = dict(CFG, repair=dict(CFG["repair"], max_attempts_per_day=5))
        self.gh.issues[0]["body"] += f"<!-- repair-cost: {DAY} 3.1000 -->"
        number, lines = self.pick(cfg)
        self.assertIsNone(number)
        self.assertIn("$3.10 spent", lines[0])

    def test_by_hand_only_if_waiting(self):
        self.assertEqual(self.pick(wanted="2")[0], 2)
        number, lines = self.pick(wanted="3")                # needs-you: never
        self.assertIsNone(number)
        self.assertIn("#3 can't be attempted", lines[0])

    def test_turned_off(self):
        cfg = dict(CFG, repair=dict(CFG["repair"], enabled=False))
        self.assertIsNone(self.pick(cfg)[0])

    def test_config(self):
        c = CFG["repair"]
        self.assertEqual((c["model"], c["max_attempts_per_day"], c["max_turns"]),
                         ("claude-sonnet-5-5", 1, 30))
        self.assertLessEqual(c["max_daily_usd"], 5)


@unittest.skipUnless(shutil.which("git"), "needs git")
class FinishTests(unittest.TestCase):
    """finish() in a throwaway git repository with a bare "origin"."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.repo = os.path.join(d, "repo")
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", HOME=d)
        self.env = env
        run = lambda *a, cwd=d: subprocess.run(a, cwd=cwd, env=env, check=True,  # noqa: E731
                                               capture_output=True)
        run("git", "init", "-q", "--bare", "-b", "main", "origin.git")
        run("git", "clone", "-q", "origin.git", "repo")
        os.makedirs(os.path.join(self.repo, "data"))
        self.write("code.py", "x = 1\n")
        self.write("data/state.json", "{}\n")
        run("git", "add", "-A", cwd=self.repo)
        run("git", "-c", "user.name=a", "-c", "user.email=a@x", "commit", "-qm", "init",
            cwd=self.repo)
        run("git", "push", "-q", "origin", "main", cwd=self.repo)
        self.gh = FakeGitHub()
        self.gh.create("Repair: robinhood: geckoterminal", "body", labels=["repair"])
        self.exec_file = os.path.join(d, "out.json")
        with open(self.exec_file, "w") as fh:
            json.dump([{"type": "system"}, {"type": "result", "total_cost_usd": 0.8312,
                                            "num_turns": 17}], fh)

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def finish(self, tests=lambda folder: (True, "Ran 9 tests\nOK")):
        return repair.finish(self.gh, CFG, 1, NOW, self.exec_file, "https://x/run",
                             folder=self.repo, tests=tests, out=lambda *a: None)

    def test_a_fix_becomes_a_draft_pull_request(self):
        self.write("code.py", "x = 2\n")
        self.write("data/state.json", '{"changed": true}\n')      # never part of a fix
        self.write(".github/workflows/x.yml", "evil\n")          # nor this
        self.write(".repair/result.md", "FIX: Retry GeckoTerminal once\n\nThe cause was ...")
        url = self.finish()
        self.assertEqual(url, "https://github.com/o/r/pull/9")
        (pr,) = self.gh.pulls
        self.assertEqual((pr["title"], pr["head"], pr["base"], pr["draft"]),
                         ("Retry GeckoTerminal once", f"repair/issue-1-{DAY}", "main", True))
        for text in ("Fixes #1", "review it before merging", "The cause was ...",
                     "All tests pass.", "`code.py`", "about **$0.83** (claude-sonnet-5-5, 17 "
                     "turns)"):
            self.assertIn(text, pr["body"])
        self.assertNotIn("data/state.json", pr["body"])
        files = subprocess.run(["git", "show", "--name-only", "--format=", f"repair/issue-1-{DAY}"],
                               cwd=self.repo, capture_output=True, text=True).stdout.split()
        self.assertEqual(files, ["code.py"])
        pushed = subprocess.run(["git", "ls-remote", "origin"], cwd=self.repo,
                                capture_output=True, text=True).stdout
        self.assertIn(f"refs/heads/repair/issue-1-{DAY}", pushed)
        self.assertIn("<!-- repair-cost: 2026-10-06 0.8312 -->", self.gh.issues[0]["body"])
        self.assertIn("Proposed fix: https://github.com/o/r/pull/9", self.gh.comments[-1][1])

    def test_failing_tests_are_said_in_the_title(self):
        self.write("code.py", "x = 2\n")
        self.write(".repair/result.md", "FIX: Something\n\nwhy")
        self.finish(tests=lambda folder: (False, "FAILED (failures=1)"))
        self.assertTrue(self.gh.pulls[0]["title"].startswith("[tests failing] "))
        self.assertIn("Some tests FAIL", self.gh.pulls[0]["body"])

    def test_no_fix_is_explained_on_the_issue(self):
        self.write(".repair/result.md", "NO-FIX: GeckoTerminal was down for an hour\n\nNothing "
                                        "in the code; it recovered by itself.")
        self.assertIsNone(self.finish())
        self.assertEqual(self.gh.pulls, [])
        text = self.gh.comments[-1][1]
        self.assertIn("proposes **no code change**", text)
        self.assertIn("GeckoTerminal was down for an hour", text)
        self.assertIn("$0.83", text)

    def test_no_result_and_unknown_cost(self):
        os.remove(self.exec_file)
        self.assertIsNone(self.finish())
        self.assertIn("didn't finish its attempt", self.gh.comments[-1][1])
        # an unknown cost counts as the assumed worst case
        self.assertIn(f"<!-- repair-cost: {DAY} 2.0000 -->", self.gh.issues[0]["body"])

    def test_pull_request_refused_leaves_the_branch(self):
        self.gh.fail_pull = RuntimeError("422 GitHub Actions is not permitted to create")
        self.write("code.py", "x = 3\n")
        self.write(".repair/result.md", "FIX: x\n\ny")
        self.assertIsNone(self.finish())
        self.assertIn("Allow GitHub Actions to create and approve pull requests",
                      self.gh.comments[-1][1])


class WorkflowTests(unittest.TestCase):
    def test_limits_and_secrets(self):
        with open(os.path.join(HERE, ".github", "workflows", "repair.yml")) as fh:
            text = fh.read()
        for needle in ("anthropics/claude-code-action@v1", "secrets.CLAUDE_API_KEY",
                       "--max-turns", "timeout-minutes: 20", "--disallowedTools \"WebFetch,"
                       "WebSearch\"", "if: always()", "cron: \"37 0 * * *\""):
            self.assertIn(needle, text)
        # Claude Code can't push, merge or reach the internet
        allowed = text.split("--allowedTools")[1].splitlines()[0]
        for tool in ("git push", "git commit", "gh ", "curl", "WebFetch"):
            self.assertNotIn(tool, allowed)
        # nothing can merge: no merge command, no merge API call
        with open(os.path.join(HERE, "screener", "repair.py")) as fh:
            code = fh.read()
        for source in (text, code):
            self.assertNotIn("pr merge", source)
            self.assertNotIn("/merge", source)
            self.assertNotIn("auto_merge", source)

    def test_health_reports_its_problems(self):
        from screener.health import health_lines
        found = []
        with tempfile.TemporaryDirectory() as d:
            health_lines(d, CFG, NOW, None, found=found)
        self.assertTrue(found)
        self.assertEqual(found[0]["check"], "Scheduled runs (last 24h)")
        self.assertIn("no GitHub token", found[0]["detail"])


if __name__ == "__main__":
    unittest.main()
