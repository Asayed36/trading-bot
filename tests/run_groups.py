"""Runs the tests in two groups for the "Paper trading run" workflow:

  python -m tests.run_groups trading   the code that decides, buys, sells or records trades
  python -m tests.run_groups setup     git, server, repair, probe and alert scripts

Every test file is TRADING unless it is named in SETUP_FILES below, so a new test file
is held to the strict group until someone deliberately moves it. Each group runs once;
if anything fails, only the failed tests are run once more. Exit code 0 = passed (first
time or on the rerun), 1 = still failing. The log gets one clear line:

  Trading tests: passed / passed on rerun / FAILED
  Setup tests: passed / passed on rerun / FAILED (trading continued)
"""

import glob
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tests that only check scripts around the bot (git pushing, server restarts, the
# repair and alert workflows, data probes). A flaky one of these must not skip a round.
SETUP_FILES = (
    "test_autorestart.py",
    "test_gitutil.py",
    "test_launch_ops.py",
    "test_paper_run_trigger.py",
    "test_precheck.py",
    "test_repair.py",
    "test_robinhood_probe.py",
    "test_scanner_alert.py",
    "test_trade_feed_probe.py",
)

LABELS = {
    "trading": ("Trading tests", ""),
    "setup": ("Setup tests", " (trading continued)"),
}


def test_files():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "tests", "test_*.py")))


def group_files(group):
    if group == "setup":
        return [f for f in test_files() if f in SETUP_FILES]
    return [f for f in test_files() if f not in SETUP_FILES]


def module_names(group):
    return ["tests." + f[:-3] for f in group_files(group)]


def _name_of(test):
    """The name to load a failed test again by (a test, a class set-up or a bad import)."""
    ident = test.id()
    if ident.startswith("unittest.loader._FailedTest."):
        return ident.split("_FailedTest.", 1)[1]
    m = re.match(r"^\w+ \((.+)\)$", ident)   # "setUpClass (tests.test_x.Class)"
    return m.group(1) if m else ident


def run_names(names, verbosity=2):
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    failed = sorted({_name_of(t) for t, _ in result.failures + result.errors})
    return failed


def run_group(group):
    label, suffix = LABELS[group]
    names = module_names(group)
    print(f"{label}: running {len(names)} test files", flush=True)
    failed = run_names(names)
    if not failed:
        print(f"{label}: passed")
        return 0
    print(f"\n{label}: {len(failed)} failed, running only those once more:")
    for name in failed:
        print(f"  {name}")
    sys.stdout.flush()
    failed_again = run_names(failed)
    if not failed_again:
        print(f"{label}: passed on rerun")
        return 0
    print(f"{label}: FAILED{suffix}")
    for name in failed_again:
        print(f"  {name}")
    return 1


def main(argv):
    if len(argv) != 2 or argv[1] not in LABELS:
        print(__doc__)
        return 2
    sys.path.insert(0, HERE)
    return run_group(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
