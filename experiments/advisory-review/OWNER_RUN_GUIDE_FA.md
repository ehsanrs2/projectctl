# مرحلهٔ دوم — اجرای پایلوت مقایسه‌ای بازبینی (راهنمای مالک)

**وضعیت:** Runner، داده‌ها و آزمون مسیر آماده‌اند. **هیچ اجرای پولی واقعی انجام نشده است.**

## هدف و محدوده

سه مورد مصنوعی (`case-01`, `case-04`, `case-05`) با سه Rubric یکسان‌مدل ولی متفاوت‌روش بررسی می‌شوند؛ جمعاً ۹ Review. این‌ها اجرای **خود gstack یا Superpowers نیستند**، بلکه Rubricهای **inspired** هستند. `oracle/gold.json` هرگز در متن ورودی Reviewer یا پوشهٔ اجرای او قرار نمی‌گیرد. هر مرورگر/ابزار مدل می‌تواند رفتار ناخواسته داشته باشد؛ بدون مهار OS، جداسازی داده‌های میزبان تضمین نمی‌شود.

## گام اول: آزمون‌های رایگان و ساخت بستهٔ کور

بعد از استخراج ZIP، از ریشهٔ پوشه اجرا کنید:

```bash
python -m pip install jsonschema
python -m unittest discover -s tests -p 'test_*.py' -v
python source_bundle/scripts/validate_bundle.py --run-fixture-tests
python scripts/codex_pilot_runner.py \
  --bundle source_bundle \
  --out /tmp/pctl-review-prepared \
  --model YOUR_AVAILABLE_MODEL
```

آخرین دستور **هیچ مدلی اجرا نمی‌کند**. دقیقاً ۹ Prompt در `prompts/` و `plan.json` ایجاد می‌شود؛ پوشهٔ خروجی باید وجود نداشته باشد. Model ID واقعی باید با دسترسی حساب بررسی شود. `--out` باید خارج از پوشهٔ Bundle باشد.

## گام دوم: پیش‌نیاز امنیت و بررسی هزینه

- نصب و احراز هویت `codex` در محیط اپراتور ضروری است؛ `codex exec --help` باید Flagهای لازم را بشناسد. در این محیط پژوهش Codex موجود نبود و هیچ مدل آزمایش نشد.
- توصیه می‌شود در VM/Container اختصاصی که فقط فایل‌های مصنوعی و Credential موردنیاز خود را دارد اجرا شود. گزینهٔ `--sandbox read-only` مجوز **نوشتن** را محدود می‌کند؛ اثبات عدم **خواندن** سایر فایل‌های میزبان نیست.
- محتواهای Fixture مصنوعی‌اند؛ بااین‌حال Codex CLI برای استنتاج با Provider انتخابی ارتباط بیرونی برقرار می‌کند. این ترافیک API/سهمیه ممکن است هزینه داشته باشد.
- مدل و Reasoning در هر ۹ Run یکسان باشند؛ نتیجهٔ موردی بدون مدل و میزان Reasoning قابل مقایسه نیست.
- فایل `run_metadata.json` و JSONL برای هر اجرا ذخیره می‌شوند. لاگ‌ها نباید عمومی منتشر شوند مگر بازبینی حریم خصوصی انجام شود.
- این Runner فقط مدت اجرای هر Turn را محدود می‌کند؛ **سقف قطعی دلار/توکن در سمت Provider برقرار نمی‌کند**. پیش از اجرا ظرفیت مصرف حساب را بررسی کنید.

## گام سوم: اجرای واقعی مرحله‌ای، با رضایت صریح

پیش‌فرض اجرای پولی **حداکثر سه فراخوانی** در هر Batch است تا پس از دریافت نتایج و هزینه بتوان دربارهٔ ادامه تصمیم گرفت. Batch اول یک مقایسهٔ منطبق برای case-01 است.

```bash
python scripts/codex_pilot_runner.py \
  --bundle source_bundle \
  --out /tmp/pctl-review-real-batch1 \
  --model YOUR_AVAILABLE_MODEL \
  --reasoning medium \
  --execute --ack-paid --ack-host-read-risk
```

اگر Batch اول از نظر اجرا، ثبت هزینه و Policy قابل قبول بود، Batch دوم و سوم را با مدل و Reasoning **بدون تغییر** اجرا کنید:

```bash
python scripts/codex_pilot_runner.py --bundle source_bundle \
  --out /tmp/pctl-review-real-batch2 --model YOUR_AVAILABLE_MODEL \
  --reasoning medium --start-index 4 \
  --execute --ack-paid --ack-host-read-risk

python scripts/codex_pilot_runner.py --bundle source_bundle \
  --out /tmp/pctl-review-real-batch3 --model YOUR_AVAILABLE_MODEL \
  --reasoning medium --start-index 7 \
  --execute --ack-paid --ack-host-read-risk
```

در صورت Fail، Timeout، خروجی ناقص یا Tool call غیرمنتظره، همان Batch متوقف می‌شود. **یک Run مردود را بدون ثبت و داوری مستقل به‌عنوان موفق محاسبه نکنید.**

## گام چهارم: تولید صف داوری انسانی

```bash
python scripts/make_adjudication_queue.py \
  /tmp/pctl-review-real-batch1 \
  /tmp/pctl-review-real-batch2 \
  /tmp/pctl-review-real-batch3 \
  --out /tmp/pctl-review-adjudication.md
```

این ابزار هیچ کلید پاسخ را نمی‌خواند و نتیجهٔ TP/FP تولید نمی‌کند. داور باید پس از تکمیل ۹ خروجی، هر ادعا را با بازتولید و فایل Gold سنجیده و خروجی‌ `adjudicated_runs.json` بسازد. سپس با ابزار قدیمی `source_bundle/scripts/score_reports.py` امتیازها حساب می‌شوند. **واحد آزمایش case×arm است؛ اجرای صرف Bundle یا خود Runner نباید به‌عنوان کشف باگ گزارش شود.**

## معیار پذیرش این فاز

- گزارش JSON برای ۹ کار با Schema معتبر و شناسهٔ صحیح؛ Token/زمان فقط از شواهد ابزار.
- صفر نقض پروتکل؛ Timeout/ابزار غیرمجاز می‌تواند آزمایش را نامعتبر کند.
- داوری مستقل تک‌تک یافته‌ها و بررسی پروندهٔ سالم (`case-05`).
- ثبت اختلاف Recall/Precision و هزینه در بازوهای مشابه؛ عدم ادعای اهمیت آماری از نمونهٔ سه‌تایی.
- عدم پذیرش ADR یا پیاده‌سازی Skill Registry صرفاً براساس این آزمایش.

## مسئولیت‌ها و محدودیت‌ها

- این بسته خارج از ریپازیتوری ProjectCTL است؛ هیچ ADR، Milestone یا قرارداد رسمی را تغییر نمی‌دهد.
- `--ignore-user-config` برای مهار برخی منابع Configuration استفاده می‌شود، اما تضمین پاکی همهٔ Contextها یا نداشتن Hook/Plugin نیست. گزارش مستقل نسخهٔ CLI و تنظیمات اثرگذار ضروری است.
- اجرای واقعی گاهی نیازمند تطبیق Flag با نسخهٔ Codex CLI مالک است؛ در صورت عدم پشتیبانی، Runner **متوقف می‌شود** و نباید گزینه‌های محدودکننده را بی‌بررسی حذف کرد.
- نتایج این پایلوت حداکثر تأیید ادامهٔ تحقیق هستند، نه پذیرش محصول یا اثبات رفتار Production.
