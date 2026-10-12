"""Checks for the two test groups of the "Paper trading run" workflow (tests/run_groups.py and
.github/workflows/screener.yml): which files are TRADING and which SETUP, the rerun of failed
tests, the log lines, and the order of the workflow steps. Run with:  python -m unittest -v
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import run_groups  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FLAKY = textwrap.dedent('''
    import os, unittest
    class T(unittest.TestCase):
        def test_flaky(self):
            marker = os.environ["MARKER"]
            if not os.path.exists(marker):
                open(marker, "w").close()
                self.fail("first time fails")
        def test_fine(self):
            pass
''')
BROKEN = textwrap.dedent('''
    import unittest
    class T(unittest.TestCase):
        def test_broken(self):
            self.fail("always fails")
        def test_fine(self):
            pass
''')


class GroupSplitTests(unittest.TestCase):
    def test_every_test_file_is_in_exactly_one_group(self):
        trading, setup = run_groups.group_files("trading"), run_groups.group_files("setup")
        self.assertEqual(set(trading) | set(setup), set(run_groups.test_files()))
        self.assertEqual(set(trading) & set(setup), set())

    def test_setup_list_names_real_files_only(self):
        self.assertEqual(set(run_groups.SETUP_FILES) - set(run_groups.test_files()), set())

    def test_trading_code_tests_stay_in_the_strict_group(self):
        trading = run_groups.group_files("trading")
        for f in ("test_screener.py", "test_main_1min.py", "test_convergence.py", "test_news.py",
                  "test_robinhood.py", "test_trend.py", "test_token_record.py", "test_early.py",
                  "test_compare_issue.py", "test_entries.py", "test_run_groups.py"):
            self.assertIn(f, trading)

    def test_git_and_ops_tests_are_setup(self):
        setup = run_groups.group_files("setup")
        for f in ("test_launch_ops.py", "test_repair.py", "test_gitutil.py"):
            self.assertIn(f, setup)


class RerunTests(unittest.TestCase):
    def run_module(self, source, group="setup"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        name = "tmp_group_%d" % id(source)
        with open(os.path.join(tmp.name, name + ".py"), "w") as fh:
            fh.write(source)
        sys.path.insert(0, tmp.name)
        self.addCleanup(sys.path.remove, tmp.name)
        self.addCleanup(sys.modules.pop, name, None)
        marker = os.path.join(tmp.name, "marker")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"MARKER": marker}), \
                mock.patch.object(run_groups, "module_names", return_value=[name]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = run_groups.run_group(group)
        return code, out.getvalue()

    def test_passes_first_time(self):
        code, out = self.run_module("import unittest\nclass T(unittest.TestCase):\n"
                                    "    def test_a(self): pass\n")
        self.assertEqual(code, 0)
        self.assertIn("Setup tests: passed\n", out)
        self.assertNotIn("rerun", out)

    def test_flaky_test_passes_on_rerun_and_only_it_is_rerun(self):
        code, out = self.run_module(FLAKY)
        self.assertEqual(code, 0)
        self.assertIn("Setup tests: passed on rerun", out)
        self.assertEqual(out.count("test_fine"), 0)      # the verbose lines go to stderr
        self.assertIn("test_flaky", out)

    def test_persistent_failure_in_setup_group_says_trading_continued(self):
        code, out = self.run_module(BROKEN)
        self.assertEqual(code, 1)
        self.assertIn("Setup tests: FAILED (trading continued)", out)

    def test_persistent_failure_in_trading_group_is_plain_failed(self):
        code, out = self.run_module(BROKEN, group="trading")
        self.assertEqual(code, 1)
        self.assertIn("Trading tests: FAILED\n", out)
        self.assertNotIn("trading continued", out)

    def test_a_file_that_cannot_be_imported_counts_as_failed(self):
        code, out = self.run_module("import module_that_does_not_exist\n")
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)


class WorkflowOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, ".github", "workflows", "screener.yml")) as fh:
            cls.text = fh.read()
        cls.names = re.findall(r"^      - name: (.+)$", cls.text, re.M)

    def step(self, name):
        m = re.search(r"^      - name: %s\n(.*?)(?=^      - |\Z)" % re.escape(name), self.text,
                      re.M | re.S)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def test_steps_come_in_this_order(self):
        order = ["Trading tests", "Setup tests", "Screen and paper trade",
                 "Save results to the repository", "Final check - setup tests"]
        for name in order:
            self.assertIn(name, self.names)
        self.assertEqual([n for n in self.names if n in order], order)
        self.assertEqual(self.names[-1], "Final check - setup tests")   # the very last step

    def test_only_the_setup_step_may_fail_without_stopping_the_job(self):
        self.assertNotIn("continue-on-error", self.step("Trading tests"))
        self.assertIn("python -m tests.run_groups trading", self.step("Trading tests"))
        setup = self.step("Setup tests")
        self.assertIn("continue-on-error: true", setup)
        self.assertIn("id: setup_tests", setup)
        self.assertIn("python -m tests.run_groups setup", setup)
        self.assertEqual(self.text.count("continue-on-error"), 1)

    def test_final_check_runs_even_after_a_skipped_save_and_fails_the_run(self):
        final = self.step("Final check - setup tests")
        self.assertIn("always()", final)
        self.assertIn("steps.setup_tests.outcome == 'failure'", final)
        self.assertIn("exit 1", final)


if __name__ == "__main__":
    unittest.main()
