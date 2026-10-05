#!/usr/bin/env bash
# Pushes the server's paper results to GitHub: the launch strategy
# (data/launch), the main (1 min) strategy and its versions
# (data/main-1min), the trade feed probe's summary (data/trade-feed-probe),
# the momentum strategy (data/momentum) and the news listings bot
# (data/news-listings).
# It uses the fine-grained GitHub token saved in ~/.git-credentials, which
# can only read and write this repository's contents. Nothing else.
#
# How: fetch GitHub's main, move this checkout's main onto it (code files
# that changed on GitHub are updated, .gitignore included; the results
# folders are never touched, because the bots keep writing there and their
# files are always the newest), then commit them on top and push. No rebase,
# so nothing can be left half-done; and if an older version of this script
# left a rebase or cherry-pick stuck, it's cleared first.
# Exit codes: 0 all pushed (or nothing new), 3 pushed but a folder had to be
# skipped (see the WARNING), 1 the push itself failed.
set -euo pipefail
cd "$(dirname "$0")/.."

# Commits need a name and email. Set them here so a missing git config can
# never block a push.
export GIT_AUTHOR_NAME="launch-bot" GIT_AUTHOR_EMAIL="launch-bot@users.noreply.github.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

# Every server results folder. Each one is added on its own: a folder that
# can't be added (say .gitignore doesn't allow it yet) is skipped with a
# warning, and the others are still pushed.
FOLDERS=(data/launch data/main-1min data/trade-feed-probe data/momentum data/news-listings)
RESULTS=()
for dir in "${FOLDERS[@]}"; do
  if [ -d "$dir" ]; then RESULTS+=("$dir"); fi
done
if [ ${#RESULTS[@]} -eq 0 ]; then
  echo "No server results yet."
  exit 0
fi
# Each results folder is left out when bringing code files up to date.
KEEP=()
for dir in "${FOLDERS[@]}"; do KEEP+=(":(exclude)$dir"); done

# Clear anything left half-done. "--quit" forgets the operation without
# touching any files, so the newest results are kept.
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
  git diff -z --name-only --diff-filter=d "$before" origin/main -- . "${KEEP[@]}" \
    | xargs -0 -r git checkout -q origin/main --
  git diff -z --name-only --diff-filter=D "$before" origin/main -- . "${KEEP[@]}" \
    | xargs -0 -r rm -f --
  # Only the finished files: never a half-written *.tmp.
  ADDED=() SKIPPED=()
  for dir in "${RESULTS[@]}"; do
    if err=$(git add -- "$dir" ':(exclude,glob)**/*.tmp' 2>&1); then
      ADDED+=("$dir")
    else
      SKIPPED+=("$dir")
      echo "WARNING: could not add $dir, skipped this time: $(echo "$err" | head -1)" >&2
    fi
  done
  if git diff --cached --quiet; then
    echo "No new server results."
    # Nothing to push, but a folder that couldn't be added still counts.
    [ ${#SKIPPED[@]} -eq 0 ] && exit 0 || exit 3
  fi
  git commit -q -m "Server paper results $(date -u '+%Y-%m-%d %H:%M UTC')"
  if git push -q origin HEAD:main; then
    echo "Pushed server results (${ADDED[*]})."
    if [ ${#SKIPPED[@]} -gt 0 ]; then
      # Pushed, but not everything: exit 3 so the failure shows in
      # "systemctl status launch-push" and the journal (see the WARNING).
      echo "Skipped: ${SKIPPED[*]} (see the WARNING above)." >&2
      exit 3
    fi
    exit 0
  fi
  # Someone (the GitHub workflow) pushed in between: start again from theirs.
  sleep $((attempt * 15))
done
echo "Could not push the server results after 4 attempts." >&2
exit 1
