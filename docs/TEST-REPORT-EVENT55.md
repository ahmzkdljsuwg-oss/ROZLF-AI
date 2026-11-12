# ROZLF AI — تقرير الاختبار (جولة إصلاح مسارات البيانات)

التاريخ: 2026-11-09 · Python 3.13.15 · بيئة الفحص محلية داخل مساحة العمل.

## 1. ما تم تشغيله فعلياً

| الاختبار | الأمر | النتيجة |
|---|---|---|
| حزمة الاختبارات الكاملة | `python -m pytest -q` | **74 passed, 3 skipped** في 3.03s |
| اختبارات الشبكة الحقيقية | `ROZLF_NETWORK_TESTS=1 python -m pytest -q tests/test_yahoo_network.py` | **3 passed** |
| اختبارات الجسر | `cd eo_bridge && python -m pytest -q` | **12 passed** |
| حارس البناء | `python scripts/verify_build.py` | `ROZLF BUILD CHECK OK` (exit 0) |

## 2. أدلة بيانات حقيقية (ليست محاكاة)

- كل أزواج FOREX التسعة رجعت شموعاً حقيقية 5min (300 شمعة) من Twelve Data أو Yahoo Finance:
  EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, NZD/USD, EUR/JPY, GBP/JPY.
- عمر آخر شمعة بين 1 و153 ثانية عند الاختبار.
- تحليل كامل حقيقي لـ EUR/USD أنتج إشارة `UP` بثقة 70.5%، المصدر في الرسالة: **Twelve Data**، وحُفظ السجل في قاعدة SQLite مؤقتة.
- GOLD: لا يوجد `TWELVE_DATA_API_KEY` حقيقي؛ النتيجة `DATA UNAVAILABLE — Twelve Data API key rejected (no TWELVE_DATA_API_KEY set…)` ولم تُصدر إشارة.
- OTC / SMARTY: `EO_BRIDGE_URL` و`EO_BRIDGE_KEY` غير مضبوطين في هذه البيئة؛ النتيجة `OTC UNAVAILABLE` و`SMARTY UNAVAILABLE` مع السبب، ولم تُصدر إشارة.
- لوحة الحالة أصبحت تعتمد على فحص حقيقي (`/candles` أو `/assets`) لكل سوق، وليس على وجود متغير بيئة.

## 3. ما لم يُختبر (ولا يُدّعى)

1. **اتصال ExpertOption حقيقي (OTC/SMARTY)**: يتطلب `EO_TOKEN` صالحاً في الجسر و`EO_BRIDGE_URL` عاماً؛ لم يتوفر أي منهما هنا.
2. **GOLD بأسعار حقيقية**: يتطلب `TWELVE_DATA_API_KEY` حقيقياً.
3. **تشغيل Railway**: لا يوجد `RAILWAY_TOKEN` في مساحة العمل، ولم يُنشر شيء.
4. **Telegram polling بمفتاح حقيقي**: لم يُشغّل البوت بمفتاح صالح (لا يوجد token حقيقي)، لكن مسار البدء وصل إلى `set_my_commands` دون أي `AttributeError`.

## 4. الإصلاحات الجوهرية في هذه الجولة

- `services/scanner.py`: كان فلتر الأسواق يقارن `Market.value` (lowercase) مع اختيار المستخدم (uppercase)، فكان الماسح يتجاهل OTC/SMARTY ويعود دائماً إلى FOREX وGOLD. أُصلح، وأصبحت أسباب التخطي تُسجَّل باسم السوق.
- `providers/yahoo.py` (جديد): مصدر شموع FOREX حقيقي بلا مفتاح، بديل عند فشل Twelve Data، يرفض OTC/SMARTY/GOLD صراحةً.
- `providers/inventory.py`: اكتشاف ديناميكي لأصول OTC من `GET /assets`، وSMARTY من `/assets` ثم `/smarty` (معرّف 240) كبديل؛ رسائل فشل واضحة.
- `providers/twelvedata.py`: سبب صريح عند غياب المفتاح بدل رسالة غامضة.
- لوحة الحالة: فحص حقيقي لكل سوق مع `LIVE / UNAVAILABLE` وسبب الفشل.
- SMARTY: قائمة مدد التداول فقط (1/2/3/5 دقائق)، بلا قائمة عملات، و`SMARTY_UNAVAILABLE` عند غياب البيانات.
