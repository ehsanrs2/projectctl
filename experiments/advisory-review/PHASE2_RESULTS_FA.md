# نتیجهٔ فاز P0-03 — Pilot Runner Qualification

**تاریخ:** ۲۰۲۶-۱۰-۱۸  
**وضعیت:** PREPARED / RUNNER-TESTED / **NO MODEL EVALUATION YET**  
**دامنه:** خارج از ProjectCTL و بدون تغییر در Milestone فعلی M6.0  
**مسیر ورودی:** بستهٔ پژوهشی P0 قبلی، کپی‌شده در `source_bundle/`

## اجرای واقعی در این نوبت

| آزمون | نتیجهٔ مشاهده‌شده | چه چیزی را ثابت نمی‌کند |
|---|---|---|
| ۷ unittest جدید Runner | PASS — ۷/۷ | عملکرد مدل، امنیت محیط میزبان |
| آزمون سرتاسری Mock Codex | PASS — هر ۹ گزارش ساختگی از مسیر اجرا، Schema و رویدادها گذشتند | توانایی کشف ۴ نقص عمدی؛ این‌ها خروجی یک مدل نیستند |
| اعتبارسنجی قدیمی ۶ Fixture | PASS — ۶/۶ تست سطحی | سالم‌بودن Fixtureهایی که عمداً ایراد دارند |
| آماده‌سازی ۹ Prompt کور | PASS — ۹ فایل، بدون مسیر/فایل Gold در ورودی | محرمانگی فایل‌های دیگرِ میزبان هنگام اجرای Codex واقعی |
| بررسی Schema با `jsonschema` | PASS در unit testهای جدید | سازگاری قطعی خروجی هر نسخهٔ Codex |
| هزینهٔ اجرای مدل | **۰ فراخوانی واقعی** | مقایسهٔ عملی کیفیت یا هزینه |

## محدودیت‌های صریح

- این محیط `codex`, `claude`, `ollama` نصب‌شده نداشت و `OPENAI_API_KEY` / `CODEX_API_KEY` هم تنظیم نشده بود؛ بنابراین هیچ مدل خارجی اجرا نشد.
- همهٔ خروجی‌های Mock فقط برای بررسی Runner هستند و **نباید به score_reports.py داده شوند**.
- Runner دستور `codex exec` را از طریق stdin و با یک خروجی Schema محدود اجرا می‌کند؛ Tool call غیرمنتظره را در لاگ تشخیص می‌دهد و Batch را متوقف می‌کند. اما این روال تضمین مهار در سطح OS نیست.
- Default اجرا صفر هزینه است؛ برای اجرای پولی، `--execute`, `--ack-paid`, `--ack-host-read-risk` و شناسهٔ مدل در دسترس لازم است. پیش‌فرض هر Batch حداکثر ۳ اجرای پولی است.
- جهت استناد آماری یا تصمیم محصول، نمونهٔ ۳ Case بسیار کوچک است. هدف این فاز اعتبار روش مقایسه و تولید یافته‌های قابل داوری است.
- عدم تغییر رسمی در `projectctl/`, `docs/PROJECT_STATE.yaml`, `docs/PROJECTCTL_BLUEPRINT.md`, `projectctl.verification.yaml` و ADRها.

## معیار پایان فاز بعدی

سه Batch واقعی با مدل/Reasoning یکسان و گزارش JSON معتبر، صفر نقض ابزار غیرمجاز، داوری مستقل و محاسبهٔ TP/FP، Recall/Precision و هزینهٔ قابل استناد. اگر CLI واقعی گزینه‌های محدودکننده را ندارد یا اجرا به امنیت میزبان متکی است، **STOP**؛ نباید گزینه‌ها را حذف و با اعتماد کاذب ادامه داد.

## مراجع فنی

- [ProjectCTL](https://github.com/ehsanrs2/projectctl/commit/c24eecd7bf3c94e80d444399a85394c57bbf4b67)
- [Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference)
- [gstack](https://github.com/garrytan/gstack)
- [Superpowers](https://github.com/obra/superpowers)
