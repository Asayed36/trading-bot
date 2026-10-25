"""Files that a workflow saves with `git add` must not be ignored by .gitignore: git add
refuses an ignored path, and the whole workflow step fails (the Timing report failed every
night for this reason)."""

import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ignored(path):
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=HERE).returncode == 0


class SavedFilesAreNotIgnored(unittest.TestCase):
    def test_timing_report_is_not_ignored(self):
        self.assertFalse(ignored("data/main-1min/timing_report.md"))

    def test_the_timing_report_workflow_adds_that_file(self):
        with open(os.path.join(HERE, ".github", "workflows", "timing-report.yml")) as fh:
            text = fh.read()
        paths = re.findall(r"^\s*git add (\S+)", text, re.M)
        self.assertIn("data/main-1min/timing_report.md", paths)
        for path in paths:
            self.assertFalse(ignored(path), path)


if __name__ == "__main__":
    unittest.main()
