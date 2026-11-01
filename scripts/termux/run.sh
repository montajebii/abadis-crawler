#!/data/data/com.termux/files/usr/bin/bash
# Run one crawl batch and drop the resulting CSV into data/raw/.
# Usage: ./scripts/termux/run.sh [max_words]
set -euo pipefail

cd "$(dirname "$0")/../.."
PROJECT_ROOT="$(pwd)"

# shellcheck disable=SC1091
source .venv/bin/activate

# Load device id from .env (or env var)
if [ -z "${DEVICE_ID:-}" ] && [ -f .env ]; then
  DEVICE_ID=$(grep '^DEVICE_ID=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")
fi
if [ -z "${DEVICE_ID:-}" ]; then
  echo "ERROR: DEVICE_ID is not set (run install.sh first)" >&2
  exit 1
fi

MAX_WORDS="${1:-${MAX_WORDS_PER_RUN:-100}}"

echo "==> Crawling (device=${DEVICE_ID:0:8}, max_words=${MAX_WORDS})"
python -m crawler --max-words "$MAX_WORDS"
EXIT_CODE=$?

if [ -f output.csv ] && [ "$(wc -c < output.csv)" -gt 200 ]; then
  ts="$(date -u +%Y%m%d_%H%M%S)"
  dest="data/raw/${DEVICE_ID:0:8}_${ts}.csv"
  cp output.csv "$dest"
  echo ""
  echo "✅ CSV saved: $dest ($(wc -l < output.csv) lines)"
  echo ""
  echo "Submit with: ./scripts/termux/submit.sh"
else
  echo "WARN: output.csv is empty or missing; nothing to submit" >&2
fi

exit $EXIT_CODE
