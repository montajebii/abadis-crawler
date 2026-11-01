# Abadis Distributed Crawler

خزندهٔ توزیع‌شدهٔ مردم‌محور برای استخراج ساختاریافتهٔ داده از `abadis.ir`.

هر کاربر اسکریپت را روی دستگاه خودش (Termux روی اندروید، لینوکس، ...) اجرا می‌کند،
خروجی به‌صورت CSV در `data/raw/` کامیت می‌شود، و GitHub Actions همهٔ CSVها را
در یک دیتابیس SQLite یکپارچه ادغام می‌کند.

## معماری سه‌لایه

| لایه | مسئولیت | خروجی |
|---|---|---|
| **Crawler** (Termux) | استخراج صفحات و ذخیرهٔ وضعیت محلی | `*.csv` |
| **Transport** (GitHub) | انتقال CSVها از طریق Pull Request | `data/raw/*.csv` |
| **ETL** (GitHub Actions) | ادغام، حذف تکراری، ساخت SQLite | `abadis.db` |

## شروع سریع

```bash
pip install -e ".[termux]"   # روی Termux
cp .env.example .env
# DEVICE_ID را در .env تنظیم کنید
python -m crawler --max-words 200
