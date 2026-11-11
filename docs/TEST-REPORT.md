# TEST REPORT — ROZLF AI

تاريخ التشغيل: 2026-11-09

## 1. الاختبارات الآلية

الأمر:

```bash
.venv/bin/python -m pytest -q
```

النتيجة الفعلية: **58 passed** (0 failed) في ~2.2 ثانية.

| الملف | ما يغطيه |
|---|---|
| `tests/test_config.py` | القيم الافتراضية، قراءة البيئة، الحدود، تحويل DATABASE_URL، allowed ids |
| `tests/test_validation.py` | شموع صالحة، تكرار/ترتيب، OHLC غير منطقي، بيانات قديمة، شموع قليلة |
| `tests/test_technical.py` | حدود المؤشرات، اتجاه صاعد/هابط، NO TRADE، مفاهيم SMC، سقف الثقة 92 |
| `tests/test_providers.py` | مصدر FOREX، رفض OTC بدون مصدر، رفض البيانات القديمة، fallback مزود، غياب quote |
| `tests/test_signals.py` | إنشاء إشارة وحفظها، NO TRADE لا يُحفظ، حد أدنى للثقة، احترام المدد، WIN/LOSS/DRAW/UNVERIFIED، استبعاد المفتوحة من الدقة، منع تكرار الماسح، رفض OTC |
| `tests/test_strategies.py` | استقلال عائلات الأدلة، تعارض/توافق الفريمات، إلغاء الإشارة، حصر الجلسات على Forex |
| `tests/test_backtest.py` | منع تسريب المستقبل، احتساب WIN/LOSS/DRAW، الصفقات والانتهاء |
| `tests/test_ai.py` | Mistral غير مهيأ لا يدّعي النجاح، health model، تحويل فشل الشبكة |
| `tests/test_bot_ui.py` | أزرار اللوحة كلها callbacks حقيقية، قوائم الأسواق، نص الإشارة، تنسيق السعر، المدد، الإحصائيات الفارغة |
| `tests/test_handlers.py` | mkt callback (حالة علوية/سفلية، سوق مجهول)، img:help، ast callback |

## 2. اختبار بيانات حقيقي (Live)

الأمر:

```bash
PYTHONPATH=. python scripts/live_smoke.py
```

النتيجة الفعلية:

```
== EUR/USD (FOREX) [FOREX]
source=Twelve Data bars=300 valid=True price=1.12036 direction=UP confidence=92
== XAU/USD (GOLD) [GOLD]
DATA UNAVAILABLE: no verified source for XAU/USD (GOLD) M5
== EUR/USD (OTC) [OTC]
DATA UNAVAILABLE: no verified source
== EUR/USD (SMARTY) [SMARTY]
DATA UNAVAILABLE: no verified source
```

تفسير:
- FOREX EUR/USD يعمل على بيانات حقيقية (Twelve Data demo) وشموعها اجتازت التحقق.
- GOLD و OTC و SMARTY تعيد `DATA UNAVAILABLE` بصدق (لا مفتاح Twelve Data كامل، ولا جسر ExpertOption).
- Swissquote أعاد quote حقيقي `1.1203 / 1.12033` في نفس التشغيل.

اختبار end-to-end إضافي مع قاعدة بيانات مؤقتة أنشأ إشارة حقيقية:
`LIVE UP 92 Twelve Data signal=True` ثم حُفظت `status=ACTIVE` وأظهرت الإحصائيات `total=1, active=1, accuracy=None`.

## 3. أخطاء اكتُشفت أثناء الاختبار وأُصلحت

1. **أصوات هبوطية موجبة**: كانت عوامل DOWN تُسجّل نقاطاً موجبة فيُختلط الاتجاه (سوق هابط أعطى UP). صُحّحت الإشارات في `engines/technical/analyzer.py`.
2. **`market_label`** أعاد `FOREXX`. صُحّح.
3. **`format_price(None)`** كان يعيد `—`؛ أصبح `N/A`.
4. **ميزة تحليل الصور** أُزيلت بالكامل في تحديث الاستراتيجيات؛ لم يبق منها كود أو زر.
5. **`PreparedImage`** أسماء حقول غير مطابقة؛ عُدّلت الاختبارات لتطابق `data/quality_score`.
6. **`MistralClient`** يعمل الآن للنصوص فقط مع نموذج افتراضي.
7. **Twelve Data** كان يرفض العمل بدون مفتاح رغم وجود demo؛ أصبح يستخدم `apikey=demo` تلقائياً (تغطية EUR/USD و USD/JPY فقط).
8. **greenlet** كانت ناقصة لتشغيل SQLAlchemy async على SQLite؛ أضيفت إلى `requirements.txt`.

## 4. ما لم يُختبر (بصدق)

- **تشغيل البوت فعلياً على Telegram** لم يُنفّذ لعدم وجود `TELEGRAM_BOT_TOKEN` حقيقي في بيئة البناء. تم التحقق من `import main` وبناء الـ Dispatcher والـ handlers، لكن Polling الحي يحتاج توكن.
- **Mistral API حقيقي** لم يُستدعَ بدون `MISTRAL_API_KEY`؛ تم اختبار منطق العميل والأخطاء فقط.
- **OTC / SMARTY** غير قابلين للاختبار لعدم وجود جسر موثّق.
- **PostgreSQL على Railway** لم يُختبر محلياً؛ الكود يستخدم `asyncpg` ويحوّل الرابط تلقائياً.
