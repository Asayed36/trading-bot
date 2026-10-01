"""Checks for running the launch bot on a server: the --test mode saves
nothing, and deploy/push_results.sh pushes the newest results even after an
older version left a rebase stuck (no git identity). Run with:
python -m unittest -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launch_bot  # noqa: E402
from run import HERE  # noqa: E402

SCRIPT = os.path.join(HERE, "deploy", "push_results.sh")


class TestModeTests(unittest.TestCase):
    def test_test_mode_uses_a_temporary_folder(self):
        seen = {}

        class FakeRunner:
            def __init__(self, cfg, folder):
                seen["folder"] = folder
                self.engine = mock.Mock(stats={"2026-10-01 22:00": {"launches_seen": 5}},
                                        traders={"90s": mock.Mock(state={"ever_bought": ["a"]})})

            async def main(self, stop_after=None):
                seen["stop_after"] = stop_after

        with mock.patch.object(launch_bot, "Runner", FakeRunner), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(launch_bot.main(["--test"]), 0)
        self.assertEqual(seen["stop_after"], 120)               # long enough for 90s
        self.assertFalse(seen["folder"].startswith(os.path.join(HERE, "data")))
        self.assertFalse(os.path.exists(seen["folder"]))         # removed afterwards
        summary = printed.call_args.args[0]
        self.assertIn("nothing was saved to data/launch", summary)
        self.assertIn("launches_seen: 5", summary)
        self.assertIn("paper buys at 90s: 1", summary)


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "needs git and bash")
class PushScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        # No global or system git config: like a fresh server without an identity.
        self.env = dict(os.environ, HOME=self.d, GIT_CONFIG_NOSYSTEM="1",
                        GIT_TERMINAL_PROMPT="0")
        for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                  "GIT_COMMITTER_EMAIL"):
            self.env.pop(k, None)
        self.git("init", "-q", "--bare", "-b", "main", "origin.git")
        self.git("clone", "-q", "origin.git", "dev")
        dev = self.path("dev")
        os.makedirs(os.path.join(dev, "deploy"))
        os.makedirs(os.path.join(dev, "data", "launch"))
        shutil.copy(SCRIPT, os.path.join(dev, "deploy", "push_results.sh"))
        self.write("dev/code.py", "v1\n")
        self.write("dev/old.py", "old\n")
        self.write("dev/data/launch/journal.csv", "row1\n")
        self.dev("add", "-A")
        self.dev("commit", "-qm", "init")
        self.dev("push", "-q", "origin", "main")
        self.git("clone", "-q", "origin.git", "server")

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, rel):
        return os.path.join(self.d, rel)

    def write(self, rel, text, mode="w"):
        with open(self.path(rel), mode) as fh:
            fh.write(text)

    def read(self, rel):
        with open(self.path(rel)) as fh:
            return fh.read()

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", *args], cwd=cwd or self.d, env=self.env, check=check,
                              capture_output=True, text=True)

    def dev(self, *args):
        return self.git("-c", "user.name=dev", "-c", "user.email=dev@x", *args,
                        cwd=self.path("dev"))

    def server(self, *args, check=True):
        return self.git(*args, cwd=self.path("server"), check=check)

    def push(self):
        return subprocess.run(["bash", "deploy/push_results.sh"], cwd=self.path("server"),
                              env=self.env, capture_output=True, text=True)

    def test_recovers_from_a_stuck_rebase_and_keeps_the_newest_results(self):
        # The old script: commit the results, then "git pull --rebase", which
        # stops half-way when git has no user.name/user.email.
        self.write("server/data/launch/journal.csv", "row2\n", "a")
        self.server("-c", "user.name=l", "-c", "user.email=l@x", "commit", "-qam", "results")
        self.write("dev/code.py", "v2\n")
        self.dev("rm", "-q", "old.py")
        self.dev("commit", "-qam", "code update")
        self.dev("push", "-q", "origin", "main")
        stuck = self.server("pull", "-q", "--rebase", "origin", "main", check=False)
        self.assertNotEqual(stuck.returncode, 0)
        self.assertTrue(os.path.isdir(self.path("server/.git/rebase-merge")))
        # The bot keeps writing; a local setting on the server is kept.
        self.write("server/data/launch/journal.csv", "row3\n", "a")
        self.write("server/local.txt", "mine\n")

        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Clearing an unfinished rebase.", result.stdout)
        self.assertIn("Pushed launch results.", result.stdout)
        self.dev("pull", "-q", "origin", "main")
        self.assertEqual(self.read("dev/data/launch/journal.csv"), "row1\nrow2\nrow3\n")
        self.assertEqual(self.read("server/code.py"), "v2\n")       # code updated like a pull
        self.assertFalse(os.path.exists(self.path("server/old.py")))
        self.assertEqual(self.read("server/local.txt"), "mine\n")
        self.assertFalse(os.path.isdir(self.path("server/.git/rebase-merge")))
        log = self.server("log", "--format=%an %s", "-3", "origin/main").stdout.splitlines()
        self.assertTrue(log[0].startswith("launch-bot Launch paper results"))
        self.assertEqual(log[1], "dev code update")

        # Nothing new: nothing pushed.
        self.assertIn("No new launch results.", self.push().stdout)

    def test_clears_a_stuck_cherry_pick(self):
        self.write("server/data/launch/journal.csv", "row2\n", "a")
        self.server("-c", "user.name=l", "-c", "user.email=l@x", "commit", "-qam", "results")
        sha = self.server("rev-parse", "HEAD").stdout.strip()
        self.server("reset", "-q", "--hard", "origin/main")
        self.assertNotEqual(self.server("cherry-pick", sha, check=False).returncode, 0)
        self.assertTrue(os.path.exists(self.path("server/.git/CHERRY_PICK_HEAD")))
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Clearing an unfinished cherry-pick.", result.stdout)
        self.dev("pull", "-q", "origin", "main")
        self.assertEqual(self.read("dev/data/launch/journal.csv"), "row1\nrow2\n")


if __name__ == "__main__":
    unittest.main()
