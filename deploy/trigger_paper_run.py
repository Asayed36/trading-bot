"""Starts the "Paper trading run" workflow on GitHub, unless one ran recently.

GitHub's own schedule (every 5 minutes) is best-effort and sometimes drops
runs for hours. paper-run-trigger.timer runs this every 10 minutes on your
server; GitHub's schedule stays on as a backup.

    python3 deploy/trigger_paper_run.py

What it does:
  1. Asks GitHub for the latest runs of .github/workflows/screener.yml.
  2. If one is queued or running, or one started in the last MIN_GAP_MINUTES
     minutes (GitHub's schedule did work), it does nothing.
  3. Otherwise it starts the workflow on main (a workflow_dispatch, the same
     as "Run workflow" in the Actions tab).

It only uses a fine-grained token limited to this repository with
"Actions: Read and write" (see deploy/LAUNCH_SERVER_SETUP.md), read from
~/.config/trading-bot/dispatch-token. It never prints the token, and it
changes nothing in the repository or the trading rules: the run itself is
the normal Paper trading run.

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
        if run.get("status") in ("queued", "in_progress", "waiting", "pending", "requested"):
            return False, f"skipped: a run is already {run['status']} ({run.get('event')})"
    started = [_utc(r.get("run_started_at") or r["created_at"]) for r in runs
               if r.get("run_started_at") or r.get("created_at")]
    if started:
        ago = (now - max(started)).total_seconds() / 60
        if ago < min_gap:
            return False, f"skipped: a run started {ago:.0f} min ago"
        return True, f"the last run started {ago:.0f} min ago"
    return True, "no earlier run found"


def request(method, path, token, body=None, opener=urllib.request.urlopen):
    """(HTTP status, parsed JSON or None). Raises TriggerError with a plain
    message, never including the token."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "paper-run-trigger"}
    if data is not None:
        headers["Content-Type"] = "application/json"   # GitHub refuses others (HTTP 415)
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with opener(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
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
        trigger(read_token())
    except TriggerError as exc:
        print(f"could not start Paper trading run: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
