# Abadis Distributed Crawler

خزندهٔ توزیع‌شدهٔ مردم‌محور برای استخراج ساختاریافتهٔ داده از `abadis.ir`.

هر کاربر اسکریپت را روی دستگاه خودش (Termux روی اندروید، لینوکس، ...) اجرا می‌کند،
خروجی به‌صورت CSV در `data/raw/` قرار می‌گیرد و از طریق Pull Request به مخزن
می‌رسد، و GitHub Actions همهٔ CSVها را در یک دیتابیس SQLite یکپارچه ادغام
می‌کند و به‌عنوان Release منتشر می‌کند.

## معماری سه‌لایه

| لایه | مسئولیت | خروجی |
|---|---|---|
| **Crawler** (Termux) | استخراج صفحات و ذخیرهٔ وضعیت محلی | `*.csv` |
| **Transport** (GitHub) | انتقال CSVها از طریق Pull Request | `data/raw/*.csv` |
| **ETL** (GitHub Actions) | ادغام، حذف تکراری، ساخت SQLite | `abadis.db` |

## شروع سریع (روی دسکتاپ)

    pip install -e ".[dev]"
    playwright install chromium        # اگر region شما محدود است، PLAYWRIGHT_DOWNLOAD_HOST را ست کنید
    cp .env.example .env
    # DEVICE_ID را در .env تنظیم کنید
    python -m crawler --max-words 20

سپس فایل CSV تولیدشده (`output.csv`) را به `data/raw/` کپی و یک Pull Request باز کنید.
GitHub Actions به‌طور خودکار دیتابیس را می‌سازد و Release می‌کند.

## مشارکت سریع (روی گوشی اندروید با Termux)

    pkg install -y git
    git clone https://github.com/montajebii/abadis-crawler.git
    cd abadis-crawler
    bash scripts/termux/install.sh
    ./scripts/termux/run.sh 100
    ./scripts/termux/submit.sh

راهنمای کامل: `docs/SETUP_TERMUX.md`

## مستندات

- `docs/ARCHITECTURE.md` — شرح لایه‌ها و جریان داده
- `docs/DATA_SCHEMA.md` — قرارداد داده (CSV و SQLite)
- `docs/SETUP_TERMUX.md` — راه‌اندازی روی Termux + عیب‌یابی
- `docs/CONTRIBUTING.md` — راهنمای مشارکت کد و داده

## مجوز

MIT — استفاده از نوشتارهای آبادیس با ذکر منبع آزاد است.
