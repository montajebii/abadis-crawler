# Setup on Termux

## پیش‌نیازها

- Termux از F-Droid (نسخه‌ی Play Store توصیه نمی‌شود)
- Python 3.10+
- فضای دیسک: حداقل ۵۰۰ مگابایت

## نصب

این دستورات را در Termux اجرا کنید:

    pkg update && pkg upgrade -y
    pkg install -y python nodejs git x11-repo
    pkg install -y chromium termux-api
    termux-wake-lock
    pip install --upgrade pip
    cd ~/abadis-crawler
    pip install -e ".[termux]"
    amv-playwright-install

## پیکربندی

    cp .env.example .env

سپس فایل .env را ویرایش کنید:

- DEVICE_ID را یکتا قرار دهید (مثلاً با uuidgen)
- MAX_WORDS_PER_RUN را بر اساس بودجه‌ی ترافیک تنظیم کنید

## اجرای دوره‌ای با cron

    pkg install -y cronie
    crond
    crontab -e

خط زیر را اضافه کنید (اجرای هر ۶ ساعت، حداکثر ۲۰۰ واژه):

    0 */6 * * * cd ~/abadis-crawler && python -m crawler --max-words 200 >> logs/cron.log 2>&1

## انتشار در GitHub

پس از پایان هر اجرا، فایل CSV در مسیر OUTPUT_CSV (پیش‌فرض ./output.csv) قرار دارد.
آن را با نام یکتا به data/raw/ کپی و push کنید:

    cp output.csv data/raw/$(grep DEVICE_ID .env | cut -d= -f2)_$(date +%Y%m%d_%H%M%S).csv
    git add data/raw/
    git commit -m "data: add batch from $(hostname)"
    git push origin main
