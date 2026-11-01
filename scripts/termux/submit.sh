#!/data/data/com.termux/files/usr/bin/bash
# Commit new CSVs under data/raw/ and submit via a Pull Request.
#
# Prerequisites (one-time):
#   pkg install -y gh
#   gh auth login        # device flow
#   gh repo fork <upstream> --clone=false
#
# Usage: ./scripts/termux/submit.sh
set -euo pipefail

cd "$(dirname "$0")/../.."

# Detect upstream + user
UPSTREAM_URL="$(git remote get-url origin)"
UPSTREAM_REPO="$(echo "$UPSTREAM_URL" | sed -E 's#.*[:/]([^/]+/[^/]+?)(\.git)?$#\1#')"

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI not installed. Run: pkg install -y gh && gh auth login" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

GH_USER="$(gh api user --jq .login)"

# Stage new CSVs
git add data/raw/*.csv

if git diff --cached --quiet; then
  echo "Nothing to submit (no new CSVs under data/raw/)"
  exit 0
fi

# Branch name from device + timestamp
if [ -z "${DEVICE_ID:-}" ] && [ -f .env ]; then
  DEVICE_ID=$(grep '^DEVICE_ID=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")
fi
BRANCH="data/$(date -u +%Y%m%d-%H%M%S)-${DEVICE_ID:0:8}"

git checkout -b "$BRANCH"
git commit -m "data: batch from ${DEVICE_ID:0:8} at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Push to user's fork (create it if needed)
FORK_REMOTE="fork-$GH_USER"
if ! git remote get-url "$FORK_REMOTE" >/dev/null 2>&1; then
  echo "==> Creating fork of $UPSTREAM_REPO (one-time)"
  gh repo fork "$UPSTREAM_REPO" --clone=false
  git remote add "$FORK_REMOTE" "git@github.com:${GH_USER}/$(basename "$UPSTREAM_REPO").git"
fi

git push -u "$FORK_REMOTE" "$BRANCH"

# Open PR
gh pr create \
  --repo "$UPSTREAM_REPO" \
  --head "${GH_USER}:${BRANCH}" \
  --base main \
  --title "data: batch from ${DEVICE_ID:0:8}" \
  --body "Automated data submission from device \`${DEVICE_ID:0:8}\`.

CSV files under \`data/raw/\` were produced by \`scripts/termux/run.sh\`.
See logs in the device for details."

echo ""
echo "✅ PR opened. CI will validate and merge."
