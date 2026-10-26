"""Runs a test group with the clock moved to several moments, to catch a test that only passes
on certain dates or times of day (a test that used the real clock failed for the last ~1.8
days of every Helius billing cycle, 2026-10-26).

  python -m tests.clock_matrix              run the trading group at every moment below
  python -m tests.clock_matrix --at 2026-10-27T12:00:00   run it once at that UTC moment
  python -m tests.clock_matrix --group setup ...          the setup group instead

The clock is moved by an offset, so time still passes while the tests run. Only
datetime.now() / utcnow() / today(), date.today() and time.time() / gmtime() / localtime()
are moved; nothing on disk changes. A test that fails at only some moments depends on the
date. It takes about one group run per moment, so it is not part of the normal suite.
"""

import argparse
import datetime as _dt
import os
import subprocess
import sys
import time as _time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (label, UTC moment). The Helius cycle starts on the 28th at 00:00 UTC ([convergence]
# helius_cycle_day); a clock started at 23:58:30 stays before midnight for about 90 seconds.
MOMENTS = (
    ("middle of a Helius cycle", "2026-10-10T12:00:00"),
    ("3 days before the cycle ends", "2026-10-25T00:00:30"),
    ("2.5 days before the cycle ends", "2026-10-25T12:00:00"),
    ("1.5 days before the cycle ends", "2026-10-26T12:00:00"),
    ("last day of the cycle", "2026-10-27T12:00:00"),
    ("last hour of the cycle", "2026-10-27T23:00:00"),
    ("last minutes of the cycle", "2026-10-27T23:58:30"),
    ("first minute of a cycle", "2026-10-28T00:00:30"),
    ("month end", "2026-10-31T12:00:00"),
    ("month and year end, 23:59", "2026-12-31T23:58:30"),
    ("midnight, new month", "2026-11-01T00:00:30"),
    ("a Saturday", "2026-10-24T12:00:00"),
    ("a Monday", "2026-10-26T00:00:30"),
)


def parse(text):
    return _dt.datetime.fromisoformat(text).replace(tzinfo=_dt.timezone.utc)


def install(at):
    """Move the clock so that `now` is `at` (UTC) at this call, and keep it running."""
    real_datetime, real_date = _dt.datetime, _dt.date
    offset = at - real_datetime.now(_dt.timezone.utc)
    real_time, real_gmtime, real_localtime = _time.time, _time.gmtime, _time.localtime

    def moved():
        return real_datetime.now(_dt.timezone.utc) + offset

    class _Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, real_datetime)

    class FakeDatetime(real_datetime, metaclass=_Meta):
        @classmethod
        def now(cls, tz=None):
            return moved().astimezone(tz) if tz else moved().replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return moved().replace(tzinfo=None)

        @classmethod
        def today(cls):
            return moved().replace(tzinfo=None)

    class _DateMeta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, real_date)

    class FakeDate(real_date, metaclass=_DateMeta):
        @classmethod
        def today(cls):
            return moved().date()

    _dt.datetime, _dt.date = FakeDatetime, FakeDate
    _time.time = lambda: real_time() + offset.total_seconds()
    _time.gmtime = lambda secs=None: real_gmtime(_time.time() if secs is None else secs)
    _time.localtime = lambda secs=None: real_localtime(_time.time() if secs is None else secs)


def run_here(at, group):
    """Run one test group once (no rerun) with the clock at `at`; return the failed tests."""
    sys.path.insert(0, HERE)
    install(parse(at))
    from tests import run_groups
    return run_groups.run_names(run_groups.module_names(group), verbosity=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--at", help="run once with the clock at this UTC moment (ISO, no zone)")
    parser.add_argument("--group", default="trading", choices=("trading", "setup"))
    args = parser.parse_args(argv)
    if args.at:
        failed = run_here(args.at, args.group)
        for name in failed:
            print("FAILED AT", args.at, name)
        return 1 if failed else 0
    bad = 0
    for label, at in MOMENTS:
        proc = subprocess.run([sys.executable, "-W", "ignore", "-m", "tests.clock_matrix",
                               "--at", at, "--group", args.group],
                              cwd=HERE, capture_output=True, text=True)
        failed = [line for line in proc.stdout.splitlines() if line.startswith("FAILED AT")]
        if proc.returncode and not failed:
            tail = proc.stderr.strip().splitlines()[-1:] or ["no message"]
            failed = ["(the run itself broke) " + tail[0]]
        print(f"{'FAIL' if failed else 'ok  '}  {parse(at):%a} {at}Z  {label}", flush=True)
        for line in failed:
            print("      ", line)
        bad += bool(failed)
    print(f"\nClock matrix ({args.group}): "
          + (f"{bad} of {len(MOMENTS)} moments FAILED" if bad else "all moments passed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
