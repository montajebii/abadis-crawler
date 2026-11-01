#!/data/data/com.termux/files/usr/bin/bash
# One-shot installer for Termux.
# Usage: bash scripts/termux/install.sh
set -euo pipefail

cd "$(dirname "$0")/../.."
PROJECT_ROOT="$(pwd)"

echo "==> Installing system packages"
pkg update -y
pkg install -y python nodejs git x11-repo termux-api cronie
pkg install -y chromium
termux-wake-lock || true

echo "==> Enabling storage access"
if [ ! -d "$HOME/storage" ]; then
  termux-setup-storage || true
fi

echo "==> Creating Python venv"
if [ ! -d .venv ]; then
  python -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip

echo "==> Installing amv-playwright (Termux Playwright port)"
# The official Playwright CDN returns 403 in some regions; use the mirror.
export PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://registry.npmmirror.com/-/binary/playwright}"
pip install --upgrade amv-playwright

echo "==> Installing crawler + dev dependencies"
pip install -e ".[dev]"

echo "==> Running unit tests"
python -m pytest tests/ -q

echo "==> Writing .env if missing"
if [ ! -f .env ]; then
  cp .env.example .env
  DEVICE_ID_VAL="$(uuidgen 2>/dev/null || python -c 'import uuid; print(uuid.uuid4())')"
  sed -i "s/^DEVICE_ID=.*/DEVICE_ID=$DEVICE_ID_VAL/" .env
  echo "Generated DEVICE_ID=$DEVICE_ID_VAL"
fi

echo ""
echo "✅ Install complete."
echo ""
echo "Next steps:"
echo "  1. Review .env (MAX_WORDS_PER_RUN, SHARD_COUNT)"
echo "  2. Run a test crawl: ./scripts/termux/run.sh"
echo "  3. Optional: add the cron entry from docs/SETUP_TERMUX.md"
