#!/usr/bin/env bash
# Starts the "Paper trading run" workflow on GitHub unless one ran in the last
# 8 minutes (see trigger_paper_run.py). Run every 10 minutes by
# paper-run-trigger.timer; you can also run it by hand to test.
exec python3 "$(dirname "$(readlink -f "$0")")/trigger_paper_run.py" "$@"
