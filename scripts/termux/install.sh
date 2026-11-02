#!/usr/bin/env bash
# One-shot installer for Termux.
# Usage: bash scripts/termux/install.sh
set -euo pipefail

cd "$(dirname "$0")/../.."
PROJECT_ROOT="$(pwd)"

echo "==> Installing system packages"
pkg update -y
pkg install -y python nodejs git x11-repo termux-api cronie termux-exec
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

echo "==> Installing termux-playwright (Termux Playwright port)"
pip install termux-playwright
python -m termux_playwright install

# Make sure node is visible to the Playwright driver
NODE_BIN="$PREFIX/bin/node"
PW_NODE=".venv/lib/python$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages/playwright/driver/node"
if [ -e "$NODE_BIN" ] && [ ! -e "$PW_NODE" ]; then
  ln -sf "$NODE_BIN" "$PW_NODE"
  echo "Linked node into Playwright driver dir"
fi

echo "==> Installing crawler + dev dependencies (without official playwright)"
pip install -e "." --no-deps
pip install beautifulsoup4 lxml python-dotenv fake-useragent tenacity pytest pytest-asyncio

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
