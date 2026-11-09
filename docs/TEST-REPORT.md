# تقرير الاختبار — ROZLF AI

تاريخ التشغيل: 2026-11-07 · Python 3.13.15 · aiogram 3.31.0 · SQLAlchemy 2.1.8

## 1. الوحدات والاختبارات التكاملية

```
$ python -m pytest -q
43 passed
```

| ملف | ما يغطيه |
| --- | --- |
| `tests/test_validation.py` | رفض الشموع الفارغة، التوقيت السيئ، OHLC غير المنطقي، الفجوات، الشموع القديمة |
| `tests/test_indicators.py` | EMA/SMA/RSI/MACD/Bollinger/ATR و SMC (BOS, CHoCH, FVG, Order Blocks, Sweeps, Premium/Discount) |
| `tests/test_analyzer.py` | اتجاه صاعد ⇒ UP، هابط ⇒ DOWN، عتبة عالية ⇒ NO TRADE، وجود أسباب ودرجة |
| `tests/test_signals.py` | اختيار المدة، حدود السياسة (cooldown/الحد اليومي)، رفض الإشارة المكررة |
| `tests/test_tracker.py` | حسم WIN/LOSS/DRAW من سعر فعلي، وتأجيل الحسم عند سعر أقدم من وقت الانتهاء |
| `tests/test_mistral.py` | لا مفتاح ⇒ NO_KEY، تحليل JSON داخل code fence، ترويسة Bearer، Vision بـ base64، رد سيئ ⇒ BAD_RESPONSE، إعادة المحاولة عند Rate Limit |
| `tests/test_handlers.py` | `/start`، `stats:show`، `hist:1`، `set:sources`، `/health`، زر تشغيل الماسح، وحجب محادثة غير مصرّح بها |
| `tests/test_services.py` | رسم صورة شارت PNG من شموع حقيقية، تجاهل عدد الشموع القليل، إشعار Telegram مع صورة، تعطيل الإشعار بلا chat id، تعامل الماسح مع فشل مصدر |

الاختبارات تستخدم بيانات وهمية داخل `tests/` فقط، ولا تُعرض أبداً كأسعار حقيقية.

## 2. اختبار حقيقي على شبكة الإنترنت (بيانات فعلية)

تشغيل `scripts/scan_once.py` مع `TWELVE_DATA_API_KEY=demo`:

```json
{
  "readiness": {"forex_ready": true, "otc_ready": false, "smarty_ready": false, "ai_ready": false},
  "scans": [
    {"market": "FOREX", "signals": ["USDJPY", "EURUSD"], "skipped": 16, "available": true, "duration_ms": 2000},
    {"market": "OTC", "signals": [], "available": false,
     "detail": "غير مضبوط: أضف EO_BRIDGE_URL وEO_BRIDGE_KEY."},
    {"market": "SMARTY", "signals": [], "available": false,
     "detail": "غير مضبوط: أضف EO_BRIDGE_URL وEO_BRIDGE_KEY."}
  ]
}
```

Interpretation:
- شموع فوركس حقيقية وصلت من Twelve Data، ومرّت فحص الجودة، وأنتجت إشارتين فقط من بين 18 فرصة مفحوصة (16 مرفوضة) — أي أن الفلترة تعمل ولا تُصدر إشارات عشوائية.
- OTC وSMARTY أعادا DATA UNAVAILABLE كما هو مطلوب عند غياب مصدر حقيقي، ولم يُستخدم فوركس بديلاً عنهما.

## 3. ما لم يُختبر (بصراحة)

| الاختبار | السبب |
| --- | --- |
| نداء Mistral حقيقي (نص وصورة) | لا يوجد `MISTRAL_API_KEY` في بيئة البناء؛ الكود والمسارات والأخطاء مُختبرة بمحاكاة HTTP |
| إرسال فعلي إلى Telegram | لا يوجد `TELEGRAM_BOT_TOKEN` حقيقي؛ التكامل مُختبر بـ session وهمي يحاكي Bot API |
| بيانات OTC / SMARTY حقيقية | يتطلب `EO_BRIDGE_URL` من مشغّل يملك حساب ExpertOption؛ لا يوجد في هذه البيئة |
| تشغيل 24/7 على Render | يحتاج نشراً فعلياً وخطة مدفوعة أو keep-alive؛ غير مُنفذ |
| حسم إشارة على سعر حقيقي بعد دقيقة | يحتاج انتظاراً زمنياً على مصدر حقيقي؛ المنطق مُختبر وحداتياً وفي مسار التسوية الكامل |

## 4. أخطاء وُجدت وأُصلحت أثناء الاختبار

1. `charts.py` كان يستخدم `matplotlib.dates.MaxNLocator` (غير موجود) ⇒ فشل رسم صور الشارت؛ صُحح إلى `matplotlib.ticker` وتحقّقت الصور بإخراج PNG فعلي.
2. `settings.py` كان يستدعي `registry.statuses()` دون `await` (ثم تعامل مع الناتج ككائنات) ⇒ خطأ في شاشة المصادر؛ صُحح.
3. تعارض `ai_retries` في اختبار Mistral ⇒ صُحح ببناء معاملات القاموس.
4. `CannedSession` لم ينفّذ `close`/`stream_content` ⇒ أُضيفا.

## 5. طريقة إعادة التشغيل

```bash
pip install -r requirements-dev.txt
python -m pytest -q
TWELVE_DATA_API_KEY=demo PYTHONPATH=. python scripts/scan_once.py
```
