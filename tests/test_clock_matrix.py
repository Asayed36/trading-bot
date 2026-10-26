"""The clock mover used by tests/clock_matrix.py really moves the clock (in a separate process,
so the real clock of this test run is never touched)."""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CODE = """
import sys
sys.path.insert(0, %r)
from tests import clock_matrix
clock_matrix.install(clock_matrix.parse("2026-12-31T23:58:30"))
import datetime, time
from datetime import datetime as dt, date, timezone
a = dt.now(timezone.utc)
print(a.isoformat()[:16], dt.utcnow().isoformat()[:16], date.today(), time.gmtime().tm_year)
print(isinstance(a, dt), isinstance(a + datetime.timedelta(hours=1), dt))
"""


class ClockMoverTests(unittest.TestCase):
    def test_clock_is_moved_and_still_runs(self):
        out = subprocess.run([sys.executable, "-I", "-c", CODE % HERE], cwd=HERE,
                             capture_output=True, text=True, check=True).stdout.split("\n")
        self.assertEqual(out[0], "2026-12-31T23:58 2026-12-31T23:58 2026-12-31 2026")
        self.assertEqual(out[1], "True True")

    def test_every_moment_parses(self):
        sys.path.insert(0, HERE)
        from tests import clock_matrix
        for label, at in clock_matrix.MOMENTS:
            self.assertEqual(clock_matrix.parse(at).tzinfo is not None, True, label)


if __name__ == "__main__":
    unittest.main()
