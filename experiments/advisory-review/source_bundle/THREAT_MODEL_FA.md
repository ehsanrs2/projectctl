# P0-01 — مدل تهدید و مرز اختیارات ابزارهای بیرونی

**وضعیت:** پیشنهاد تحقیقاتی؛ پیش‌نویس غیرمصوب، فاقد تأثیر بر ProjectCTL Runtime.

## هدف امنیتی

Skill یا Reviewer خارجی حتی در صورت Prompt Injection، خطای Tool، یا پیکربندی ناخواسته نباید بتواند اختیار Scheduler، Task Authority، RunStore، Scope، Verification، Evidence، Git Integration یا Publication را تصاحب کند.

## مرزهای اعتماد

| بخش | منبع اختیار | اجازه برای Plugin خارجی |
|---|---|---|
| هدف/معماری/ADR | فایل‌های انسانی و مسیر تصمیم مصوب | فقط خواندن متنِ مجاز، نه تغییر |
| انتخاب Task و امتیاز Scheduler | ProjectCTL | هیچ |
| Execution Input و Scope | `projectctl.scope.yaml` و Manifestها | فقط خواندن Snapshot پالایش‌شده |
| Codex Worker Runtime | Adapter و Sandbox مصوب | فقط زیرمجموعهٔ Capability اثبات‌شده |
| Verification و Evidence | سیاست مستقل ProjectCTL | فقط مشاهدهٔ خروجی پالایش‌شده، نه تأیید یا تضعیف |
| Git، Commit، PR و انتشار | Integration/Delivery معتبر ProjectCTL | هیچ در پایلوت |
| Review خارجی | گزارش تحقیقاتی غیرمرجع | Write فقط در artifact scratch مجاز، در صورت نیاز |
| هزینه و ارتباطات خارجی | حساب و سیاست کنترل‌شدهٔ مالک | غیرفعال در فاز آفلاین |

## تهدیدها و سیاست‌ها

| تهدید | مسیر سوءاستفاده | کنترل لازم پیش از Integration |
|---|---|---|
| Privilege escalation در متن Skill | دستورالعمل خارجی درخواست `git push` یا تغییر Policy می‌کند | Skill به‌عنوان Untrusted Data؛ enforce سطح Tool/OS؛ نه صرف Prompt |
| Prompt injection در Fixture/Repo | SPEC یا README می‌گوید Secretها را ارسال کن | سلسله‌مراتب دستورالعمل و allowlist مسیر/ابزار؛ آزمون تزریق |
| شبکه/telemetry و cross-model review | Skill به سرویس بیرونی یا مدل دوم می‌فرستد | افشای داده با رضایت مشخص، egress کنترل‌شده، ثبت هزینه و مقصد |
| نوشتن در مسیرهای نامجاز | `/review` خودکار کد را اصلاح می‌کند؛ QA گزارش را در Repo ذخیره می‌کند | sandbox read-only یا Scratch مستقل؛ Diff/FS witness |
| bypass verification | Reviewer می‌گوید «قبول است» | هیچ ارتباط authoritative با Verification/Integration؛ تمام نتایج Advisory |
| Skill collision/precedence | `AGENTS.md` یا Rule جدید قراردادهای ProjectCTL را خنثی می‌کند | ثبت ترتیب اجرای قطعی و محدودیت بالادستی غیرقابل‌override |
| Supply chain/upgrade | Skill در upstream تغییر می‌کند، اجرای CLI به checkout شناور متصل است | pin Commit + SHA-256 فایل‌ها و scripts + نصب کنترل‌شده + rollback |
| Capability mismatch | CLI مهارت را پیدا می‌کند، SDK نه | قابلیت واقعی و آزمایش زندهٔ Adapter جداگانه؛ fail-closed |
| Non-deterministic review | نتایج ظاهراً قطعی اما وابسته به Prompt/Model | ثبت مدل، نسخه، تلاش، دمای قابل‌تنظیم، زمان و منابع؛ عدم تغییر رسمی تصمیم |
| Data exfiltration via report | خواندن Secrets از سورس یا Trajectory و چاپ در گزارش | Redaction، allowlist فیلد و عدم چاپ Prompt/Env/Token خام |

## اصل کلیدی

`SKILL.md` دادهٔ نامطمئن است، نه Capability Grant. فیلد `allowed-tools` استاندارد Agent Skills را تنها به‌عنوان «اظهار نیازمندی» ثبت می‌کنیم؛ کنترل دسترسی باید بیرون از Skill اعمال شود.

## مرز شروع پایلوت

- فقط fixture مصنوعی، بدون Credentials و پروژهٔ واقعی.
- کاربر فقط **یک پوشهٔ Fixture** را به Reviewer می‌دهد؛ `oracle/` اصلاً mount نمی‌شود.
- اجرای آفلاین: شبکه/telemetry/telemetry hooks/secondary reviewer غیرمجاز. اگر راه معتبر برای جلوگیری نداریم، Native Skill اجرا نمی‌شود و از Rubric الهام‌گرفته استفاده می‌کنیم.
- Write فقط برای ثبت نتایج در مسیر خروجی بیرون از Fixture، توسط runner مورد اعتماد.
- هیچ Commit/Push/Publish، تغییر Repo اصلی یا فراخوانی زندهٔ ProjectCTL.
- هر تلاش برای نوشتن خارج از مجوز، استفادهٔ پنهان از شبکه، تغییر Scope یا افزایش Permission ⇒ **Protocol Violation** و رد آن اجرای Pilot.

## تصمیم‌های باز (برای ADR آتی، نه اکنون)

1. Skillها فقط به صورت متنی عرضه شوند یا اسکریپت اجرایی هم داشته باشند؟
2. آیا Reviewer در RunStore دارای Run جداگانه خواهد بود یا تنها یک Artifact پژوهشی مستقل؟
3. آیا نتیجهٔ Advisory روزی می‌تواند Policy Gate شود؟ به‌طور پیش‌فرض پاسخ منفی است.
4. چه روشی برای محدودیت شبکه/اجرای Process با واقعیت پشتیبانی‌شدهٔ میزبان سازگار است؟
5. کدام بخش از Context مجاز است خارج از دستگاه یا به Model دیگر ارسال شود؟

تا پاسخ قطعی و شواهد اجرایی نیامده، هیچ اتصال Runtime پیشنهاد نمی‌شود.
