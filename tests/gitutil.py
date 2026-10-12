"""Helpers for the tests that build throwaway git repositories (a bare "origin"
and checkouts of it): test_launch_ops.py and test_repair.py.

Two weaknesses of the plain `git clone` + `subprocess.run(check=True, capture_output=True)`
that these replace:

* when git failed, the test only said "returned non-zero exit status 128": git's own
  message (stderr) was captured and thrown away. run_git() raises GitError with it;
* the second checkout was made with `git clone origin.git server`, which starts a second
  git process (git-upload-pack) and sometimes failed on GitHub's runners (4 of 159
  scheduled runs in a day). copy_checkout() makes the same checkout by copying the first
  one's folder (it already holds the pushed commit and the origin's remote-tracking
  branch), with no git transport at all, and run_git() tries a failing command once more.
"""

import os
import shutil
import subprocess
import time


class GitError(RuntimeError):
    pass


def diagnostics(cwd, env):
    """What may explain a failure on someone else's machine: git's version, the disk, the
    owners, and what is in the folder."""
    bits = []
    try:
        bits.append("git " + subprocess.run(["git", "--version"], capture_output=True, text=True,
                                           env=env).stdout.strip())
    except OSError as exc:
        bits.append(f"git --version failed: {exc}")
    try:
        free = shutil.disk_usage(cwd).free // 1_000_000
        bits.append(f"free disk {free} MB, uid {os.getuid()}, folder owner uid {os.stat(cwd).st_uid}")
        bits.append("folder holds: " + ", ".join(sorted(os.listdir(cwd))[:20]))
    except OSError as exc:
        bits.append(f"could not look at {cwd}: {exc}")
    return "; ".join(bits)


def run_git(args, cwd, env, check=True, retries=0, pause=0.5):
    """Run `git <args>` in `cwd`. On a non-zero exit (and check=True) it is run again up to
    `retries` more times, then GitError is raised with git's own stderr and stdout."""
    attempts = retries + 1
    for attempt in range(attempts):
        result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
        if result.returncode == 0 or not check:
            return result
        if attempt + 1 < attempts:
            time.sleep(pause)
    raise GitError(f"git {' '.join(args)} (in {cwd}) exited {result.returncode} after "
                   f"{attempts} attempt(s)\n--- git's stderr ---\n{result.stderr.rstrip()}\n"
                   f"--- git's stdout ---\n{result.stdout.rstrip()}\n--- {diagnostics(cwd, env)}")


def init_checkout(origin, dest, env, branch="main"):
    """The same repository `git clone <origin> <dest>` makes of an EMPTY bare repository
    (a remote "origin" and the branch's upstream set), without cloning."""
    run_git(["init", "-q", "-b", branch, dest], os.path.dirname(dest), env)
    run_git(["remote", "add", "origin", os.path.abspath(origin)], dest, env)
    run_git(["config", f"branch.{branch}.remote", "origin"], dest, env)
    run_git(["config", f"branch.{branch}.merge", f"refs/heads/{branch}"], dest, env)


def copy_checkout(source, dest, env):
    """A second checkout of the same repository: a copy of `source` (a checkout whose
    commits are pushed to origin) with the same remote, no network or git transport."""
    shutil.copytree(source, dest, symlinks=True)
    run_git(["status", "--porcelain"], dest, env)           # a broken copy fails here, loudly
