# ROZLF MINI APP

تطبيق Telegram Mini App حقيقي داخل البوت الحالي. لا يوجد موقع منفصل ولا محرك تحليل ثانٍ:
الواجهة تنادي نقاط API محمية داخل خدمة الويب نفسها التي يستخدمها البوت، وكل رقم يأتي من
`SignalGenerator` / `DataSourceRegistry` / `Repository` نفسها.

## 1. ما أُضيف

| الملف | الوظيفة |
|---|---|
| `mini_app/auth.py` | التحقق من Telegram `initData` بـ HMAC-SHA256 ورفض التوقيع/الانتهاء |
| `mini_app/service.py` | طبقة مشتركة: bootstrap، الأسواق، التحليل، التوصيات، السجل، الإحصاء |
| `mini_app/api.py` | مسارات `/api/mini/*` + خدمة `/mini-app/` والملفات الثابتة |
| `mini_app/static/*` | واجهة Premium 3D (أسود/زمردي/ذهبي)، 6 أسواق، شارت حقيقي، نتائج، سجل، إعدادات |
| `tests/test_mini_app.py` | اختبارات Auth + API + تطابق محرك البوت + زر القائمة |

القائمة الرئيسية للبوت تحتفظ بـ ANALYSIS / SETTINGS / RECOMMENDATIONS وتضيف زراً واحداً:
`🚀 ROZLF MINI APP` عبر `WebAppInfo`، ولا يظهر الزر إلا عند وجود رابط HTTPS عام.

## 2. تدفق التحليل (محرك واحد)

1. الواجهة ترسل `market` + `asset` + `duration` (أو `duration=null` للاختيار الذكي).
2. الخادم يتحقق من `initData` ويستخرج هوية Telegram من التوقيع فقط.
3. `service.analyse` يستدعي `ctx.generator.generate` نفسه الذي يستدعيه البوت.
4. النتيجة تُعاد بنفس الاتجاه والثقة والسعر؛ `NO TRADE` يبقى `NO TRADE` ولا يُرفع يدوياً.
5. أي إشارة تُسجَّل في قاعدة البيانات نفسها وتظهر في سجل البوت والتطبيق.

## 3. متغيرات البيئة المطلوبة

لا متغير جديد إلزامي. المتغير الاختياري الوحيد:

| المتغير | الوصف |
|---|---|
| `MINI_APP_URL` | رابط HTTPS العام للخدمة، مثال `https://web-production-b044b.up.railway.app` |
| `PUBLIC_BASE_URL` | بديل مقبول لنفس الرابط |
| `RAILWAY_PUBLIC_DOMAIN` | يُستخدم تلقائياً إن لم يُضبط أي رابط |
| `ROZLF_ROLE` | يجب ضبطه `web-only` على خدمة الويب حتى تبني المحرك بدون Polling |

التطبيق يُبنى دائماً كـ `<base>/mini-app/`. يجب أن يكون الرابط HTTPS حتى يقبله Telegram.

## 4. التشغيل

محلياً (اختبار الواجهة داخل Telegram يحتاج رابط HTTPS عام، أما الفحص المحلي فمباشر):

```bash
source .venv/bin/activate
python main.py
# http://127.0.0.1:8080/mini-app/
```

على Railway لدينا خدمة الويب `web-production-b044b.up.railway.app` وخدمة العامل (worker) التي تشغّل Polling.

1. خدمة الويب تحتاج نفس متغيرات التشغيل كـ worker، وليس التوكن فقط:
   `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `EO_BRIDGE_URL`, `EO_BRIDGE_KEY`,
   `TWELVE_DATA_API_KEY`, `MISTRAL_API_KEY` (استخدم Shared Variable / Reference ولا تنسخ القيم إلى GitHub).
2. أضف إلى خدمة الويب: `ROZLF_ROLE=web-only` — تبني المحرك وتخدم Mini App لكنها لا تشغّل Polling ولا تصطدم بالـ worker.
3. أضف إلى خدمة الـ worker: `MINI_APP_URL=https://web-production-b044b.up.railway.app` (أو اتركه فارغاً إذا كان للعامل نطاق عام).
4. Redeploy للخدمتين. زر `🚀 ROZLF MINI APP` يظهر فقط عندما يكون `MINI_APP_URL` معروفاً،
   ويفتح نفس المسار `/mini-app/` داخل Telegram.

المسارات `/mini-app/` و`/api/mini/*` تُركّب على تطبيق aiohttp الموجود لـ `/health`.

## 5. الأمان

- لا تُقبل هوية المستخدم من العميل؛ تُستخرج من `initData` الموقّع.
- صلاحية `initData` 24 ساعة، وأي تعديل على أي حقل يُرفض.
- كل مسارات `/api/mini/*` تتطلب ترويسة `X-Telegram-Init-Data` أو `Authorization: tma ...`.
- صفحة `index.html` والملفات الثابتة عامة لكنها لا تحتوي بيانات ولا أسراراً.
- لا تُعاد أي مفاتيح API أو توكنات في أي استجابة.

## 6. الاختبارات

```bash
.venv/bin/python -m pytest -q tests/test_mini_app.py
.venv/bin/python -m pytest -q
```

تغطي الاختبارات: توقيع صالح/معدّل/منتهٍ، رفض الطلبات غير الموثقة، الستة أسواق،
التحليل بنفس دالة المحرك، رفض OTC والمدة غير المدعومة، حفظ الحد الأدنى للثقة،
حالة النظام بدون أسرار، وخدمة الملفات الثابتة، ووجود زر Mini App في القائمة.
