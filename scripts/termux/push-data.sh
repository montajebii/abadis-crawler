#!/usr/bin/env bash
# Push data/raw/ CSVs safely: rebase first, then push.
set -euo pipefail
cd "$(dirname "$0")/../.."

git pull --rebase origin main
git push origin main
echo "✅ pushed"
