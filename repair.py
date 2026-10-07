"""Automatic repair of the problems the daily health check finds (see
screener/repair.py). Run by .github/workflows/repair.yml:

    python repair.py issues [--issue N]   <- open/update issues; pick one to attempt
    python repair.py start N              <- mark #N attempted; write the task
    python repair.py finish N --execution-file F   <- pull request or comment; cost

Needs GITHUB_TOKEN and GITHUB_REPOSITORY (GitHub Actions provides them).
It never merges anything, never trades, never touches a wallet.
"""

import argparse
import os
import sys

from run import HERE, load_config
from screener import repair
from screener.github_issues import GitHubError, GitHubIssues
from screener.health import health_lines
from screener.paper_trader import now_utc


def output(name, value):
    """A step output for the workflow (GITHUB_OUTPUT), when there is one."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(f"{name}={value}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)
    p = sub.add_parser("issues")
    p.add_argument("--issue", help="attempt this issue (it must be waiting for its attempt)")
    p = sub.add_parser("start")
    p.add_argument("number", type=int)
    p = sub.add_parser("finish")
    p.add_argument("number", type=int)
    p.add_argument("--execution-file")
    args = parser.parse_args(argv)

    cfg = load_config()
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        print("Needs GITHUB_TOKEN and GITHUB_REPOSITORY (GitHub Actions provides them).")
        return 1
    gh = GitHubIssues(token, repo, repair.LABEL)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id else None
    now = now_utc()
    try:
        if args.step == "issues":
            folder = os.path.join(HERE, cfg["files"]["data_folder"])
            found = []
            health_lines(folder, cfg, now, gh, found=found)
            print(f"{len(found)} problem(s) in today's health check.")
            known = repair.open_issues(gh, found, folder, now, repair.failed_runs(gh, cfg, now))
            number = repair.pick(gh, cfg, now, wanted=args.issue, known=known,
                                 current={p["check"] for p in repair.group(found)})
            output("issue", number or "")
            output("model", cfg["repair"]["model"])
            output("max_turns", cfg["repair"]["max_turns"])
        elif args.step == "start":
            repair.start(gh, args.number, now, run_url, folder=HERE)
        else:
            repair.finish(gh, cfg, args.number, now, args.execution_file, run_url, folder=HERE)
    except GitHubError as exc:
        print(f"GitHub: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
