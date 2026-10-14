# کارگاه پاک‌سازی داده

برنامه محلی برای پاک‌کردن CSV و XLSX. فایل اصلی دست نمی‌خورد. قبل از اجرا طرح عملیات نشان داده می‌شود و خروجی فقط بعد از وارسی دوباره فایل تحویل داده می‌شود. بدون کلید مدل هم کار می‌کند.

## اجرا

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=src .venv/bin/python -m cleaning_workspace
```

یا `./run.sh` در لینوکس و `run.ps1` در ویندوز. سپس مرورگر را باز کنید:

`http://127.0.0.1:8000`

فایل نمونه: `web/examples/customers.csv`

آزمون‌ها:

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

## چه چیزهایی واقعاً انجام می‌شود

- CSV (UTF-8، UTF-8 با BOM، و Windows-1256) و XLSX
- حذف فاصله اضافه، حذف ردیف کاملاً خالی، یکسان‌سازی تاریخ قطعی، نشانه‌گذاری تکراری دقیق
- حذف تکراری دقیق فقط با تأیید جدا و با نگه‌داشتن اولین ردیف
- گزارش و دفتر تغییرات از نتیجه اجرا

## چه چیزهایی انجام نمی‌شود

- XLS و XLSB
- اجرای فرمول، ماکرو یا کد داخل درخواست
- حدس تاریخ مبهم، ادغام نام‌های شبیه هم، حذف ردیف نیمه‌خالی، ساخت پیش‌شماره تلفن
- تبدیل تقویم بدون اینکه درخواست یا پاسخ شما هدف را مشخص کند

جزئیات در `docs/data-cleaning/` است.

## تنظیم‌ها

| متغیر | پیش‌فرض |
| --- | --- |
| `CLEANING_HOST` | `127.0.0.1` |
| `CLEANING_PORT` | `8000` |
| `CLEANING_DATA_DIR` | `data/` |
| `CLEANING_MAX_UPLOAD_BYTES` | ۲۰ مگابایت |
| `CLEANING_MAX_ROWS` | ۵۰۰۰۰ |
| `CLEANING_RETENTION_HOURS` | ۲۴ |
| `WORKSPACE_ACCESS_TOKEN` | خالی؛ اگر مقدار داشته باشد باید در سرآیند `X-Workspace-Token` فرستاده شود |
| `CLEANING_AI_BASE_URL` / `CLEANING_AI_API_KEY` / `CLEANING_AI_MODEL` | هر سه با هم لازم‌اند؛ در غیر این صورت مدل صدا زده نمی‌شود |

کلید را در فایل منبع نگذارید.
