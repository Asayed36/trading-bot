#!/usr/bin/env bash
# Pushes the launch strategy's results (data/launch) to GitHub.
# It uses the fine-grained GitHub token saved in ~/.git-credentials, which
# can only read and write this repository's contents. Nothing else.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d data/launch ]; then
  echo "No launch results yet."
  exit 0
fi
git add data/launch
if git diff --cached --quiet; then
  echo "No new launch results."
  exit 0
fi
git -c user.name="launch-bot" -c user.email="launch-bot@users.noreply.github.com" \
  commit -q -m "Launch paper results $(date -u '+%Y-%m-%d %H:%M UTC')"

# The GitHub workflow also commits to main every few minutes (other files),
# so replay this commit on top of the latest main and retry if needed.
for attempt in 1 2 3 4; do
  if git pull -q --rebase --autostash origin main && git push -q origin HEAD:main; then
    echo "Pushed launch results."
    exit 0
  fi
  sleep $((attempt * 15))
done
echo "Could not push the launch results after 4 attempts." >&2
exit 1
