"""Starts the "Paper trading run" workflow on GitHub, unless one ran recently,
and the "Daily strategy comparison" when yesterday's issue is missing.

GitHub's own schedules are best-effort and sometimes drop runs for hours (or
a whole day's comparison). paper-run-trigger.timer runs this every 10
minutes on your server; GitHub's schedules stay on as a backup.

    python3 deploy/trigger_paper_run.py

What it does:
  1. Asks GitHub for the latest runs of .github/workflows/screener.yml.
  2. If one is queued or running, or one started in the last MIN_GAP_MINUTES
     minutes (GitHub's schedule did work), it does nothing.
  3. Otherwise it starts the workflow on main (a workflow_dispatch, the same
     as "Run workflow" in the Actions tab).
  4. After 00:30 UTC: if yesterday's "Daily comparison: YYYY-MM-DD" issue
     isn't on GitHub yet, and no comparison run is queued, running or
     started in the last DAILY_GAP_MINUTES minutes, it starts
     .github/workflows/daily-comparison.yml on main the same way. It posts
     the issue for yesterday, so it's the same issue GitHub's 00:07 run
     would have posted.

It only uses a fine-grained token limited to this repository with
"Actions: Read and write" (see deploy/LAUNCH_SERVER_SETUP.md), read from
~/.config/trading-bot/dispatch-token. That token has no Issues permission,
so if GitHub refuses the issue lookup with it, the lookup is tried again
without any token (the repository's issues are public). It never
prints the token, and it changes nothing in the repository or the trading
rules: the runs themselves are the normal workflows.

Exit code 0 = started or skipped on purpose; 1 = couldn't (see the message).
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"
REPO = os.environ.get("PAPER_RUN_REPO", "Asayed36/trading-bot")
WORKFLOW = "screener.yml"
REF = "main"
MIN_GAP_MINUTES = 8
DAILY_WORKFLOW = "daily-comparison.yml"
DAILY_LABEL = "daily-comparison"
DAILY_MARKER = "<!-- daily-comparison: {} -->"     # as in screener/compare.py
DAILY_AFTER = (0, 30)                               # UTC hour, minute
DAILY_GAP_MINUTES = 60
ACTIVE = ("queued", "in_progress", "waiting", "pending", "requested")
TOKEN_FILE = os.environ.get("PAPER_RUN_TOKEN_FILE",
                            os.path.expanduser("~/.config/trading-bot/dispatch-token"))


class TriggerError(Exception):
    pass


def _utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def decide(runs, now, min_gap=MIN_GAP_MINUTES):
    """(start?, why) from the workflow's latest runs (GitHub's list, newest
    first)."""
    for run in runs:
        if run.get("status") in ACTIVE:
            return False, f"skipped: a run is already {run['status']} ({run.get('event')})"
    started = [_utc(r.get("run_started_at") or r["created_at"]) for r in runs
               if r.get("run_started_at") or r.get("created_at")]
    if started:
        ago = (now - max(started)).total_seconds() / 60
        if ago < min_gap:
            return False, f"skipped: a run started {ago:.0f} min ago"
        return True, f"the last run started {ago:.0f} min ago"
    return True, "no earlier run found"


def daily_posted(issues, day):
    """Is the comparison issue for `day` (YYYY-MM-DD) among these issues?"""
    marker = DAILY_MARKER.format(day)
    return any(marker in (i.get("body") or "") or i.get("title") == f"Daily comparison: {day}"
               for i in issues)


def daily_due(now):
    """(the day to post, or None before 00:30 UTC)."""
    if (now.hour, now.minute) < DAILY_AFTER:
        return None
    return (now - timedelta(days=1)).date().isoformat()


def request(method, path, token, body=None, opener=urllib.request.urlopen):
    """(HTTP status, parsed JSON or None). Raises TriggerError with a plain
    message, never including the token. token=None asks without one (only
    works for reading a public repository)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "paper-run-trigger"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"   # GitHub refuses others (HTTP 415)
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with opener(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and not token:
            raise TriggerError(f"GitHub said {exc.code} to {method} {path} without a "
                               "token") from None
        if exc.code in (401, 403):
            raise TriggerError(f"GitHub said {exc.code}: the token has expired or lacks "
                               "permission (it needs Actions: Read and write on "
                               f"{REPO})") from None
        raise TriggerError(f"GitHub said {exc.code} for {method} {path}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise TriggerError(f"couldn't reach GitHub: {exc}") from None


def trigger(token, now=None, opener=urllib.request.urlopen, out=print):
    now = now or datetime.now(timezone.utc)
    base = f"/repos/{REPO}/actions/workflows/{WORKFLOW}"
    _, body = request("GET", f"{base}/runs?per_page=5", token, opener=opener)
    start, why = decide((body or {}).get("workflow_runs") or [], now)
    if not start:
        out(why)
        return False
    status, _ = request("POST", f"{base}/dispatches", token, {"ref": REF}, opener=opener)
    if status != 204:
        raise TriggerError(f"GitHub answered {status} instead of 204 to the start request")
    out(f"started Paper trading run on {REF} ({why})")
    return True


def trigger_daily(token, now=None, opener=urllib.request.urlopen, out=print):
    """Start the Daily strategy comparison if yesterday's issue is missing
    (after 00:30 UTC). Returns True if it started one."""
    now = now or datetime.now(timezone.utc)
    day = daily_due(now)
    if day is None:
        return False
    path = f"/repos/{REPO}/issues?labels={DAILY_LABEL}&state=all&per_page=10"
    try:
        _, issues = request("GET", path, token, opener=opener)
    except TriggerError:
        # The token only has Actions permission; the repository's issues
        # are public, so ask again without it.
        _, issues = request("GET", path, None, opener=opener)
    if daily_posted(issues or [], day):
        return False                     # the normal case: nothing to say
    base = f"/repos/{REPO}/actions/workflows/{DAILY_WORKFLOW}"
    _, body = request("GET", f"{base}/runs?per_page=5", token, opener=opener)
    runs = (body or {}).get("workflow_runs") or []
    for run in runs:
        if run.get("status") in ACTIVE:
            out(f"daily comparison for {day}: not posted yet, a run is already {run['status']}")
            return False
    started = [_utc(r.get("run_started_at") or r["created_at"]) for r in runs
               if r.get("run_started_at") or r.get("created_at")]
    if started and (now - max(started)).total_seconds() / 60 < DAILY_GAP_MINUTES:
        ago = (now - max(started)).total_seconds() / 60
        out(f"daily comparison for {day}: not posted yet, but a run started {ago:.0f} min ago")
        return False
    status, _ = request("POST", f"{base}/dispatches", token, {"ref": REF}, opener=opener)
    if status != 204:
        raise TriggerError(f"GitHub answered {status} instead of 204 to the start request")
    out(f"started Daily strategy comparison on {REF} (the issue for {day} wasn't posted)")
    return True


def read_token(path=TOKEN_FILE):
    try:
        with open(path) as fh:
            token = fh.read().strip()
    except OSError:
        raise TriggerError(f"no token at {path} (see deploy/LAUNCH_SERVER_SETUP.md)") from None
    if not token:
        raise TriggerError(f"the token file {path} is empty")
    return token


def main():
    try:
        token = read_token()
    except TriggerError as exc:
        print(f"could not start Paper trading run: {exc}", file=sys.stderr)
        return 1
    failed = 0
    # Each on its own: one failing mustn't stop the other.
    for name, step in (("Paper trading run", trigger),
                       ("Daily strategy comparison", trigger_daily)):
        try:
            step(token)
        except TriggerError as exc:
            print(f"could not start {name}: {exc}", file=sys.stderr)
            failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
