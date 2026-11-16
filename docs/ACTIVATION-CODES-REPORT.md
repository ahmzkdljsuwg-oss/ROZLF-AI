# تقرير نظام أكواد التفعيل — ROZLF AI + NEXUS-ADMIN

التاريخ: 2026-11-16  
الفرع: `lemon/subscriptions`  
حالة النشر: **لم يُنشر إلى Railway** (بانتظار موافقة المالك)

## 1. ما تم تنفيذه

| المطلوب | التنفيذ |
|---|---|
| إصدار كود من بوت الإدارة فقط | زر «➕ إصدار كود تفعيل» داخل NEXUS-ADMIN |
| المالك الوحيد | ثابت في الكود `PRIMARY_OWNER_ID = 8368948762`؛ قيمة `OWNER_TELEGRAM_IDS` لا تمنح صلاحية لأي حساب آخر |
| كود عشوائي قوي | `secrets.choice` بصيغة `NX-XXXX-XXXX-XXXX-XXXX` (16 حرفاً من أبجدية 32 حرفاً) |
| استخدام واحد | `UPDATE ... WHERE status='AVAILABLE' AND used_by IS NULL` داخل معاملة ذرية |
| مدة يختارها المالك | يوم / 7 / 30 / 90 / 365 |
| حفظ في PostgreSQL | جدول `subscription_codes` |
| حفظ الهاش فقط | `code_hash` = SHA-256، والكود الصريح يُعرض مرة واحدة للمالك |
| منع التكرار والتخمين | فهرس فريد + محاولات إنشاء محدودة + رفض الأكواد غير الموجودة |
| إلغاء كود | زر «🗑 إلغاء الكود» يحوّل الحالة إلى `DISABLED` |
| ربط الاشتراك بـ Telegram ID | `subscriptions.telegram_id` هو المفتاح |
| منع استخدامه من حساب آخر | الكود يصبح `USED` بعد أول تفعيل |
| إيقاف الميزات عند الانتهاء | `SubscriptionMiddleware` يفحص القاعدة عند كل طلب |
| لوحة المالك | إصدار، قائمة النشطة، قائمة المستخدمة، الاشتراكات، بداية/نهاية، تمديد، إلغاء، حظر، بحث بـ Telegram ID |

## 2. الملفات المعدّلة

- `config.py` — تثبيت المالك الوحيد وتفعيل الاشتراكات عند وجود `ADMIN_BOT_TOKEN`.
- `database/models.py` — عمود `code_hash` فريد.
- `database/repository.py` — `hash_activation_code`, هجرة الأكواد القديمة، `disable_code`, `find_code_by_hash`, `extend_subscription`, `ban_subscription`, `SUB_BANNED`, تخزين الهاش.
- `admin_bot/keyboards.py` — أزرار الإصدار/الإلغاء/البحث/التمديد/الحظر.
- `admin_bot/handlers.py` — معالجات البحث (FSM)، الملف الشخصي، التمديد، الحظر، إلغاء الكود.
- `admin_bot/states.py` — حالة انتظار Telegram ID.
- `admin_bot/main.py` — `MemoryStorage` لدعم FSM.
- `bot/handlers/menus.py` — شاشة طلب الكود عند `/start` للحساب غير المفعّل.
- `bot/formatting.py`, `bot/middleware/subscription.py` — صيغة الكود الجديدة.
- `.env.example`, `README.md` — توثيق المالك الوحيد والهاش.
- `tests/test_activation_codes.py` — 11 اختباراً جديداً.
- `tests/test_subscriptions.py`, `tests/test_admin_startup.py` — تحديث التوقعات.

## 3. نتائج الاختبارات (مُنفَّذة فعلياً)

```
.venv/bin/python -m pytest tests/test_activation_codes.py -q
11 passed in 2.93s
```

```
.venv/bin/python -m pytest -q
414 passed, 3 skipped
```

## 4. تغطية السيناريوهات الثمانية

| # | السيناريو | الاختبار | النتيجة |
|---|---|---|---|
| 1 | إصدار كود من حساب المالك | `test_owner_issues_a_unique_hashed_code` | PASS |
| 2 | رفض الإصدار من حساب غير مالك | `test_non_owner_cannot_issue_or_use_the_admin_panel` | PASS |
| 3 | تفعيل الكود من حساب عميل | `test_customer_activates_code_once` | PASS |
| 4 | رفض إعادة استخدام الكود | `test_reuse_and_second_account_are_rejected` | PASS |
| 5 | رفض الكود/الاشتراك المنتهي | `test_expired_subscription_stops_protected_features` | PASS |
| 6 | منع حساب آخر من استخدام كود مفعّل | `test_reuse_and_second_account_are_rejected` | PASS |
| 7 | توقف الميزات المحمية بعد الانتهاء | `test_expired_subscription_stops_protected_features` | PASS |
| 8 | بوت التداول يعمل دون تأثر | `test_customer_bot_stays_functional_alongside_activation` + كامل الحزمة | PASS |

اختبارات إضافية: لوحة المالك (عرض/تمديد/حظر) — `test_admin_panel_lists_extends_and_bans_customers`، والبحث بـ Telegram ID — `test_owner_can_search_a_customer_by_telegram_id`، وهجرة الأكواد القديمة مرة واحدة فقط — `test_legacy_plaintext_codes_are_migrated_idempotently`.

## 5. قيود معروفة

- اختبارات قاعدة البيانات نُفّذت على SQLite داخل بيئة الاختبار؛ هجرة PostgreSQL مكتوبة بـ SQL قياسي (`ALTER TABLE ... ADD COLUMN`, `CREATE UNIQUE INDEX IF NOT EXISTS`) لكنها لم تُشغّل على PostgreSQL إنتاجي في هذا التشغيل.
- لم يُجرَ اختبار Telegram حقيقي بالتوكنات الإنتاجية (التوكنات غير متاحة ولم تُطلب).
- لا توجد أكواد اختبار أو ثابتة داخل الكود؛ كل كود يُولّد وقت التشغيل.

## 6. خطوات التشغيل

1. شغّل بوت الإدارة: `python start_admin.py`.
2. من حساب Telegram `8368948762` أرسل `/start`.
3. اضغط «➕ إصدار كود تفعيل» واختر المدة، ثم أرسل الكود للعميل.
4. في بوت العملاء أرسل `/activate NX-XXXX-XXXX-XXXX-XXXX`.
5. لمتابعة الاشتراك: `/status`، وللإدارة البحث بالـ Telegram ID من لوحة المالك.
