#!/usr/bin/env bash
# Pushes the launch strategy's results (data/launch) to GitHub.
# It uses the fine-grained GitHub token saved in ~/.git-credentials, which
# can only read and write this repository's contents. Nothing else.
#
# How: fetch GitHub's main, move this checkout's main onto it (code files
# that changed on GitHub are updated; data/launch is never touched, because
# the bot keeps writing there and its files are always the newest), then
# commit data/launch on top and push. No rebase, so nothing can be left
# half-done; and if an older version of this script left a rebase or
# cherry-pick stuck, it's cleared first.
set -euo pipefail
cd "$(dirname "$0")/.."

# Commits need a name and email. Set them here so a missing git config can
# never block a push.
export GIT_AUTHOR_NAME="launch-bot" GIT_AUTHOR_EMAIL="launch-bot@users.noreply.github.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

if [ ! -d data/launch ]; then
  echo "No launch results yet."
  exit 0
fi

# Clear anything left half-done. "--quit" forgets the operation without
# touching any files, so the newest results in data/launch are kept.
gitdir=$(git rev-parse --git-dir)
if [ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ]; then
  echo "Clearing an unfinished rebase."
  git rebase --quit
fi
for op in cherry-pick revert merge; do
  head="$gitdir/$(echo "$op" | tr 'a-z-' 'A-Z_')_HEAD"
  if [ -f "$head" ]; then
    echo "Clearing an unfinished $op."
    git "$op" --quit
  fi
done
# A stuck rebase can leave the checkout on a detached HEAD: go back to main.
if ! git symbolic-ref -q HEAD >/dev/null; then
  git checkout -q -B main
fi

for attempt in 1 2 3 4; do
  git fetch -q origin main
  before=$(git rev-parse HEAD)
  # main now points at GitHub's main; the files on disk stay as they are...
  git reset -q --mixed origin/main
  # ...except code files that changed on GitHub, which are brought up to
  # date like "git pull" would (restart the bot to use new code).
  git diff -z --name-only --diff-filter=d "$before" origin/main -- . ':(exclude)data/launch' \
    | xargs -0 -r git checkout -q origin/main --
  git diff -z --name-only --diff-filter=D "$before" origin/main -- . ':(exclude)data/launch' \
    | xargs -0 -r rm -f --
  git add data/launch
  if git diff --cached --quiet; then
    echo "No new launch results."
    exit 0
  fi
  git commit -q -m "Launch paper results $(date -u '+%Y-%m-%d %H:%M UTC')"
  if git push -q origin HEAD:main; then
    echo "Pushed launch results."
    exit 0
  fi
  # Someone (the GitHub workflow) pushed in between: start again from theirs.
  sleep $((attempt * 15))
done
echo "Could not push the launch results after 4 attempts." >&2
exit 1
