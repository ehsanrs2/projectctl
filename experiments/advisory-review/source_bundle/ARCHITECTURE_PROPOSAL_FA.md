# P0-01 — طرح معماری Skill Inventory و Advisory Review

**Status:** DRAFT FOR RESEARCH (NOT ADR / NOT ACCEPTED).

## مرجع واقعی

ProjectCTL امروز ContextAssembler، Codex WorkerAdapter، Capability Probe، Verification مستقل و Evidence دارد. سه مرجع قدرت دارند: `docs/PROJECT_STATE.yaml` (هدف)، منابع انسانی سیاست و Scope، و سیستم اجرای معتبر. هیچ ابزار دیگر نباید مرجع موازی شود.

## معماری فرضیِ آینده

```text
Human-approved Project State / Scope / Task Authority
                     |
        ProjectCTL Scheduler + Execution Planner
                     |
           (approved task/workspace scope)
                     v
           [Advisory Capability Resolver] -- metadata + digest
                     |
             [Offline/isolated reviewer]
                     |
          AdvisoryReport v0 (non-authoritative)
                     |
       [separate evaluator + human adjudication]
                     |
          Proposed decision for future ADR

Production Verification / RunStore / Integration = unchanged
```

## تفکیک دو لایهٔ پیشنهادی

**۱. Skill Inventory (صرفاً داده):** خواندن metadata، شناسهٔ repo، commit pin، digest، وابستگی‌ها و Requested Effects. هیچ Skill از طریق Registry حق نصب/اجرای خودکار پیدا نمی‌کند. `schemas/skill_inventory.v0.schema.json` صرفاً نمونهٔ پیشنهادی تحقیقاتی است.

**۲. Advisory Runner (فاز آینده و مشروط):** فقط پس از اثبات جداگانهٔ Compatibility و محدودیت OS و پالیسی معتبر بتواند Review اجرایی را اجرا کند. یک خروجی `advisory_report` تولید می‌کند که Verification، Evidence و تصمیم کنترل‌پلین را override نمی‌کند.

## محل احتمالاً مناسب در کد (فقط نقشه، نه تصمیم قطعی)

| نیاز | بخش موجود | تصمیمِ پیشنهادی |
|---|---|---|
| کشف Metadata مهارت | `projectctl/context/` | ابتدا Reader آفلاین مستقل، خارج از ContextAssembler |
| مذاکرهٔ Capability | `projectctl/workers/codex/` | Probe جدید مستقل؛ SDK را معادل CLI فرض نکنید |
| ساخت گزارش | `projectctl/telemetry/` و `schemas` | در فاز Pilot خارج از Repo؛ در آینده قرارداد تحقیقاتی/غیرمرجع |
| سنجش عملی | خارجی/Harbor-inspired | از Evidence مستقل واقعی کپی اعتبار نگیرد؛ fixture تنها |
| تصمیم معماری | `docs/decisions/` | ADR بعد از مشاهدهٔ خروجی پایلوت، نه پیش از آن |

## مسیر تصمیم

- **Gate 0:** Host compatibility و تمام Permissionها صریحاً شناسایی شوند؛ در ابهام Block.
- **Gate 1:** Pilot آفلاین با Fixtureهای مصنوعی و Rubricها، خروجی معتبر و قابل امتیازدهی بدهد.
- **Gate 2:** در صورت مشاهدهٔ سود عملی، Pilot واقعی Native Skill در محیط جدا با OS-enforced controls و Budget جدا انجام شود؛ روش Rubric-only جایگزین این Gate نیست.
- **Gate 3:** طراحی ADR با سنجش هزینه/فایده، Threat Model، نسخه‌گذاری و قرارداد Fail-Closed؛ صرفاً پس از پذیرش مالک در Milestone مناسب.

## عدم‌تداخل با M6

این پیشنهاد به RunStore SQLite، WAL، Seal Writer، Trace Collector، Schemas M6، Migration و Verification Manifest دست نمی‌زند. ادغام پیش از تأیید یک Milestone جدید ممنوع است.
