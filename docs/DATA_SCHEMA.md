# Data Schema

## قرارداد CSV (`data/raw/*.csv`)

هر فایل CSV با کدگذاری UTF-8 و جداکننده‌ی کاما، با هدر ذخیره می‌شود.
هر ردیف نماینده‌ی یک بخش معنایی از یک واژه است.

ستون‌ها:

- `word_canonical` — فرم نرمال‌شده و یکتای واژه (کلید تطبیق)
- `word_display` — فرم نمایشی همان‌طور که در سایت دیده می‌شود
- `word_pronunciation` — تلفظ (اختیاری)
- `word_english_mean` — معنی انگلیسی (اختیاری)
- `source_key` — کلید منبع: dehkhoda, moeen, amid, parsi, farhang, ...
- `source_title` — عنوان نمایشی بخش
- `definition_text` — متن ساده‌ی بخش (بدون تگ)

## قواعد نرمال‌سازی `word_canonical`

1. تبدیل `ي` عربی و `ك` عربی به `ی` و `ک` فارسی.
2. حذف فاصله‌های ابتدا و انتها.
3. تبدیل فاصله‌های چندتایی به یک فاصله.
4. حفظ نیم‌فاصله (U+200C) به‌عنوان بخشی از واژه.

## حذف تکراری در ETL

- `definitions` با کلید `(word_canonical, source_key)` یکتا می‌شود.
- `words` با کلید `word_canonical` یکتا می‌شود؛ اولین ردیفی که واژه را دید
  مقادیر `display_form`, `pronunciation`, `english_mean` را تعیین می‌کند.

## جداول SQLite

- `dictionaries` — لیست دیکشنری‌ها، یکتا با `slug`
- `words` — واژه‌ها، یکتا با `canonical`
- `definitions` — بخش‌های معنایی، یکتا با `(word_id, source_key)`
- `crawl_pages` — وضعیت صفحات فهرست (فقط محلی)
- `word_queue` — صف واژه‌ها (فقط محلی)
- `crawl_metrics` — متریک‌ها

اسکیمای کامل در `db/schema.sql` است و منبع حقیقت محسوب می‌شود.
