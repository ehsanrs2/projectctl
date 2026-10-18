# بستهٔ پژوهشی موازی ProjectCTL — P0-01 و P0-02

**وضعیت:** Research-only / Off-repository / Non-authoritative  
**تاریخ:** ۲۰۲۶-۱۰-۱۸  
**وابستگی عملیاتی به M6.0:** ندارد  
**نتایج عملکرد مدل‌ها:** هنوز اجرا نشده  
**تغییر در ریپازیتوری ProjectCTL:** هیچ

## هدف

۱. روشن‌کردن مرز امنیتی و سازگاری Skillها/Reviewهای خارجی بدون نقض اختیار ProjectCTL.  
۲. آماده‌کردن آزمایش مقایسه‌ای تکرارپذیر برای Review، قبل از تصمیم دربارهٔ هرگونه ادغام.

## یافته‌های مبتنی بر سورس

- در ProjectCTL، `projectctl/workers/codex/adapter.py` از Codex Python SDK با `deny_all`، `workspace_write`/`read_only` و شبکهٔ غیرفعال استفاده می‌کند؛ پشتیبانی Skillهای Codex CLI معادل قابلیت اثبات‌شدهٔ همین Adapter نیست.
- `projectctl/context/assembler.py` از `AGENTS.md`ها، knowledge bindingها و Scope مصوب ContextManifest می‌سازد. افزودن Skill خارجی نباید منبع دستورالعمل دیگری با اختیار بالاتر معرفی کند.
- `projectctl.verification.yaml` و شواهد مستقل Verification تحت اختیار ProjectCTL هستند؛ Review خارجی فقط Advisory است.
- `gstack /review` «Fix-first» دارد و ممکن است فایل تغییر دهد؛ `gstack /qa-only` گزارش‌دهنده است ولی Write و Bash هم درخواست می‌کند. استفاده از نام «read-only» در Prompt به‌تنهایی محدودیت OS محسوب نمی‌شود.
- Superpowers در بعضی Workflowها Subagent و Commit دارد، بنابراین اجرای کامل Skillها به جای Rubric بی‌تغییر مجاز فرض نمی‌شود.
- استاندارد Agent Skills فقط قالب `SKILL.md`/metadata و بارگذاری تدریجی را تعیین می‌کند؛ `allowed-tools` در Specification تجربی است، نه تضمین Enforcement.
- Harbor API فیلد `skills` را در Capability مدل عامل نشان می‌دهد، اما خود این فیلد مجوز امنیتی نیست. ATIF دادهٔ غنی و بالقوه حساس دارد؛ برای M6 Trace خروجی مجاز یا هم‌تراز Evidence نیست.

## ساختار بسته

- `THREAT_MODEL_FA.md`: ماتریس اعتماد، عملیات ممنوع و معیارهای عدم‌قبول.
- `ARCHITECTURE_PROPOSAL_FA.md`: طرح اختیاری Capability/Skill + Advisory. هیچ قرارداد رسمی ProjectCTL را تغییر نمی‌دهد.
- `EVALUATION_PROTOCOL_FA.md`: پروتکل ثبت‌شدهٔ آزمایش، کنترل‌های مقایسه، سنجه‌ها و تصمیم.
- `prompts/`: سه Rubric موازی؛ توجه: B/C **inspired** هستند، نه اجرای Pluginهای اصلی.
- `fixtures/case-01...case-06/`: شش پروژهٔ مصنوعی مستقل شامل SPEC، module و unittest.
- `oracle/gold.json`: کلید پاسخ محرمانه برای داور؛ **نباید به Reviewer داده شود**.
- `schemas/`: قراردادهای تحقیقاتی JSON؛ فاقد اختیار و خارج از رجیستری Schema پروژه.
- `scripts/`: بررسی بسته، کپی کور مورد، و امتیازدهی از adjudication دستی.
- `examples/adjudicated_runs.template.json`: نمونهٔ قالب نمره‌دهی.
- `CODEX_GOAL.md`: یک Goal مهندسی برای بررسی بعدی در محیط مالک، بدون اجرای زندهٔ خودکار.

## بررسی‌های انجام‌شده در ساخت بسته

- ۶/۶ Fixture با آزمون‌های سطحی موجود (عمدی) سبز هستند. **این سبزبودن به معنی سالم‌بودن پیاده‌سازی نیست.**
- ۴ ایراد عمدی در Oracle ثبت شده و ۲ Fixture بدون ایراد عمدی هستند.
- ۳ تست ابزار امتیازدهی/کنترل ورودی و ۶ تست Adjudicator برای بازتولید نقص‌های عمدی و دو مورد سالم موفق شدند (مجموع ۹ تست داخلی).
- بررسی صحت ساختار بسته انجام شده است.
- هیچ اجرای واقعی Codex/gstack/Superpowers، سنجش کیفیت Agent یا ارزیابی امنیتی سیستم‌عامل انجام نشده است.

## استفادهٔ دستی (با Python 3.10+، بدون نصب وابستگی)

```bash
python scripts/validate_bundle.py --run-fixture-tests
python -m unittest discover -s scripts -p 'test_offline_tools.py' -v
python scripts/prepare_blind_case.py case-01 /tmp/pctl-review-case01
```

`prepare_blind_case.py` مسیر مقصد را **ایجاد** می‌کند و اگر از قبل موجود باشد، بدون دست‌کاری آن رد می‌کند. بعد فقط پوشهٔ مقصد جداگانه را در محیط Agent قرار دهید، نه ریشهٔ بسته و نه پوشهٔ `oracle/`.

گزارش‌ها را پس از بازبینی داور انسانی به `adjudicated_runs.json` تبدیل کرده و سپس:

```bash
python scripts/score_reports.py /path/to/adjudicated_runs.json
```

این ابزار فقط آیتم‌های انطباق‌داده‌شده توسط داور را جمع می‌زند؛ خودکار از روی متن گزارش، درست‌بودن باگ را تشخیص نمی‌دهد.

## کنترل تغییرات

این بسته نباید مستقیم در `docs/PROJECTCTL_BLUEPRINT.md`، `docs/PROJECT_STATE.yaml`، `projectctl/` یا `projectctl.verification.yaml` کپی یا Merge شود. اگر تصمیم معماری بعداً مثبت شد، آن زمان ADR مستقل، تحلیل Threat Model جدید، Evidence و Milestone مصوب لازم است.

## منابع و پین مطالعه

- [ProjectCTL / main@c24eecd](https://github.com/ehsanrs2/projectctl/commit/c24eecd7bf3c94e80d444399a85394c57bbf4b67)
- [gstack / main@d258bcf](https://github.com/garrytan/gstack/commit/d258bcffb0cb7bda5f133f3e957f932d816d282f)
- [Superpowers / main@bb92a77](https://github.com/obra/superpowers/commit/bb92a77741419a4ab5f06e711a283343f1ada0c3)
- [Agent Skills Specification](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx)
- [Harbor capabilities](https://github.com/harbor-framework/harbor/blob/main/src/harbor/agents/capabilities.py)
- [OpenHands SDK](https://github.com/OpenHands/software-agent-sdk)
