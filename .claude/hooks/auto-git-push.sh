#!/usr/bin/env bash
# auto-git-push.sh
# Claude Code Stop hook — commits and pushes all changes after each response.
# Only runs if there are actual uncommitted changes.

set -euo pipefail

REPO_DIR="/Users/dinesh/Documents/My_Product/stream2stack"
cd "$REPO_DIR"

# Bail out silently if there's nothing to commit.
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  exit 0
fi

# Build a commit message from the list of changed files.
CHANGED=$(git status --short | awk '{print $2}' | head -10 | tr '\n' ' ')
FILE_COUNT=$(git status --short | wc -l | tr -d ' ')

if [ "$FILE_COUNT" -eq 1 ]; then
  MSG="chore: update ${CHANGED% }"
else
  MSG="chore: update $FILE_COUNT files — ${CHANGED% }"
fi

# Stage everything (env files are excluded by .gitignore).
git add .

# Commit with a co-author tag.
git commit -m "$(cat <<EOF
$MSG

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"

# Push to origin/main.
git push origin main

echo "auto-git-push: committed and pushed — $MSG"
