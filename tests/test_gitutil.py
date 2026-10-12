"""Checks for tests/gitutil.py, the helpers the git-based tests use to build throwaway
repositories: git's own message is shown when a step fails, a failing command is tried
once more, and a second checkout is made without `git clone`. Run with:  python -m unittest -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import gitutil  # noqa: E402


@unittest.skipUnless(shutil.which("git"), "needs git")
class GitUtilTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name
        self.env = dict(os.environ, HOME=self.d, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
        for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            self.env.pop(k, None)

    def git(self, *args, cwd=None):
        return gitutil.run_git(args, cwd or self.d, self.env)

    def test_a_failure_shows_gits_own_message_and_where_it_happened(self):
        with self.assertRaises(gitutil.GitError) as ctx:
            gitutil.run_git(["clone", "-q", "no-such-origin.git", "server"], self.d, self.env)
        text = str(ctx.exception)
        self.assertIn("git clone -q no-such-origin.git server", text)
        self.assertIn("exited 128", text)
        self.assertIn("--- git's stderr ---", text)
        self.assertIn("no-such-origin.git", text.split("--- git's stderr ---")[1])   # git's words
        self.assertIn("git version", text)
        self.assertIn("free disk", text)
        self.assertIn(self.d, text)

    def test_a_failing_command_is_tried_once_more_then_reported(self):
        real = subprocess.run
        calls = []

        def flaky(args, **kw):
            calls.append(args)
            if len(calls) == 1:
                return subprocess.CompletedProcess(args, 128, "", "fatal: transient\n")
            return real(args, **kw)

        with mock.patch.object(gitutil.subprocess, "run", flaky), mock.patch.object(gitutil.time, "sleep"):
            result = gitutil.run_git(["--version"], self.d, self.env, retries=1)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        calls.clear()
        always = lambda args, **kw: subprocess.CompletedProcess(args, 128, "", "fatal: still broken\n")  # noqa: E731
        with mock.patch.object(gitutil.subprocess, "run", always), mock.patch.object(gitutil.time, "sleep"):
            with self.assertRaises(gitutil.GitError) as ctx:
                gitutil.run_git(["status"], self.d, self.env, retries=1)
        self.assertIn("after 2 attempt(s)", str(ctx.exception))
        self.assertIn("fatal: still broken", str(ctx.exception))
        # check=False never raises
        with mock.patch.object(gitutil.subprocess, "run", always):
            self.assertEqual(gitutil.run_git(["status"], self.d, self.env, check=False).returncode, 128)

    def test_the_first_checkout_is_what_clone_makes_of_an_empty_repository(self):
        self.git("init", "-q", "--bare", "-b", "main", "origin.git")
        self.git("clone", "-q", "origin.git", "cloned")
        gitutil.init_checkout(os.path.join(self.d, "origin.git"), os.path.join(self.d, "made"), self.env)
        wanted = {}
        for name in ("cloned", "made"):
            out = self.git("config", "--local", "--list", cwd=os.path.join(self.d, name)).stdout
            wanted[name] = sorted(out.splitlines())
        self.assertEqual(wanted["made"], wanted["cloned"])

    def test_the_second_checkout_is_a_working_copy_of_the_pushed_one(self):
        self.git("init", "-q", "--bare", "-b", "main", "origin.git")
        origin = os.path.join(self.d, "origin.git")
        dev = os.path.join(self.d, "dev")
        gitutil.init_checkout(origin, dev, self.env)
        with open(os.path.join(dev, "code.py"), "w") as fh:
            fh.write("v1\n")
        self.git("add", "-A", cwd=dev)
        self.git("-c", "user.name=d", "-c", "user.email=d@x", "commit", "-qm", "init", cwd=dev)
        self.git("push", "-q", "origin", "main", cwd=dev)
        gitutil.copy_checkout(dev, os.path.join(self.d, "server"), self.env)
        server = os.path.join(self.d, "server")
        head = lambda cwd: self.git("rev-parse", "HEAD", cwd=cwd).stdout.strip()  # noqa: E731
        self.assertEqual(head(server), head(dev))
        self.assertEqual(self.git("status", "--porcelain", cwd=server).stdout, "")
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "main@{upstream}", cwd=server).stdout.strip(),
                         "origin/main")
        self.assertEqual(self.git("remote", "get-url", "origin", cwd=server).stdout.strip(), origin)
        # it is independent of the first one, and talks to the same origin
        with open(os.path.join(server, "code.py"), "w") as fh:
            fh.write("v2\n")
        self.git("-c", "user.name=s", "-c", "user.email=s@x", "commit", "-qam", "server change", cwd=server)
        self.git("push", "-q", "origin", "main", cwd=server)
        self.git("pull", "-q", "origin", "main", cwd=dev)
        with open(os.path.join(dev, "code.py")) as fh:
            self.assertEqual(fh.read(), "v2\n")

    def test_building_the_repositories_many_times_never_fails(self):
        origin = os.path.join(self.d, "o.git")
        self.git("init", "-q", "--bare", "-b", "main", "o.git")
        for i in range(15):
            dev = os.path.join(self.d, f"dev{i}")
            gitutil.init_checkout(origin, dev, self.env)
            with open(os.path.join(dev, "f"), "w") as fh:
                fh.write(f"{i}\n")
            self.git("add", "-A", cwd=dev)
            self.git("-c", "user.name=d", "-c", "user.email=d@x", "commit", "-qm", str(i), cwd=dev)
            self.git("push", "-q", "-f", "origin", "main", cwd=dev)
            gitutil.copy_checkout(dev, os.path.join(self.d, f"server{i}"), self.env)


if __name__ == "__main__":
    unittest.main()
