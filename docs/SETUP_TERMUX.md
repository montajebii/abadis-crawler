# Setup on Termux

## Requirements

- Termux installed from **F-Droid** (Play Store version is outdated)
- Android 8+
- ~600 MB free storage (Chromium is heavy)
- An internet connection (mobile data is fine)

## One-time install

Open Termux and run:

    pkg install -y git
    git clone https://github.com/montajebii/abadis-crawler.git
    cd abadis-crawler
    bash scripts/termux/install.sh

The installer:

- Installs system packages (Python, Node, Chromium, cron)
- Creates a Python venv
- Installs `amv-playwright` (Termux port of Playwright)
- Runs the unit test suite (35 tests)
- Generates `DEVICE_ID` in `.env`

If `termux-setup-storage` asks for permission, allow it.

## First test run

    ./scripts/termux/run.sh 5

This fetches 5 word pages. Expect output like:

    ==> Crawling (device=xxxxxxxx, max_words=5)
    ...
    ✅ CSV saved: data/raw/xxxxxxxx_20261102_XXXXXX.csv

Inspect:

    head -3 data/raw/xxxxxxxx_*.csv
    sqlite3 local_state.db "SELECT COUNT(*) FROM words;"

## Submitting data

One-time GitHub setup:

    pkg install -y gh
    gh auth login            # follow the device flow
    gh repo fork montajebii/abadis-crawler --clone=false

Then for each batch:

    ./scripts/termux/run.sh 100
    ./scripts/termux/submit.sh

`submit.sh` will:

1. Stage new CSV files under `data/raw/`
2. Create a branch `data/<timestamp>-<device_id>`
3. Push to your fork
4. Open a Pull Request against `main`

GitHub Actions will validate the CSV and, once merged, rebuild the SQLite
database and publish a new Release automatically.

## Automating with cron

    pkg install -y cronie
    crond
    crontab -e

Add one line (runs every 6 hours, 100 words per run):

    0 */6 * * * cd ~/abadis-crawler && ./scripts/termux/run.sh 100 >> logs/cron.log 2>&1

Note that `submit.sh` is **not** in the cron entry — review the CSV once,
then submit manually to keep the PR history clean.

## Battery and network

- `termux-wake-lock` is enabled by `install.sh` to prevent Android
  from killing Termux mid-run.
- On Wi-Fi, crawling is unlimited; on mobile data, keep `MAX_WORDS_PER_RUN`
  low (50–100) to save bandwidth. A typical word page is 30–80 KB
  after blocking images and CSS.
- AIMD throttling keeps the request rate between 1 and 30 requests per
  minute depending on server responses. No manual tuning is needed.

## Troubleshooting

**`ImportError: No module named 'amv_playwright'`**

    source .venv/bin/activate
    pip install --upgrade amv-playwright

**`Playwright browser not found`**

    export PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright
    amv-playwright-install

**`gh: command not found`**

    pkg install -y gh

**`HTTP 429` in logs**
The AIMD controller will automatically back off. If it exhausts 3 retries,
the run stops and the next cron invocation resumes. No manual action needed.

**CSV file is empty**

The first list page might have returned 0 words if the network was flaky.
Delete `local_state.db` and try again:

    rm -f local_state.db local_state.db-wal local_state.db-shm
    ./scripts/termux/run.sh 5
