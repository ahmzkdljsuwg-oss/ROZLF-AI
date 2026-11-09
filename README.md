# ROZLF AI — بوت تحليل وإشارات Trading على Telegram

ROZLF AI بوت Telegram مستقل للتحليل الفني وإشارات التداول (ExpertOption-style expiries + Forex/Gold).
لا يوجد موقع ولا لوحة ويب: كل شيء داخل Telegram.

> ⚠️ البوت تعليمي/تحليلي فقط ولا ينفّذ أي صفقة تلقائياً.

---

## 1. ما يعمل فعلياً

| الميزة | الحالة |
|---|---|
| لوحة تحكم Telegram (Inline Keyboard، تعديل رسائل بدون إغراق) | ✅ يعمل |
| تحليل FOREX (EUR/USD, USD/JPY بدون مفتاح عبر Twelve Data demo) | ✅ تم اختباره على بيانات حقيقية |
| باقي أزواج FOREX و GOLD | ✅ مع `TWELVE_DATA_API_KEY` (بدونه `DATA UNAVAILABLE` بصدق) |
| Gold quote لحظي (Swissquote) | ✅ يعمل |
| محرك فني كامل: RSI, MACD, EMA 9/21/50/200, SMA, Bollinger, ATR, Stochastic, S/R, Patterns | ✅ يعمل |
| SMC حسابي: BOS, CHoCH, FVG, Order Blocks, Liquidity Sweeps, Equal Highs/Lows, Market Structure, Premium/Discount | ✅ يعمل |
| إشارات UP / DOWN / NO TRADE مع درجة ثقة محسوبة (ليست عشوائية) | ✅ يعمل |
| تحقق WIN/LOSS/DRAW/UNVERIFIED بعد انتهاء المدة + إحصائيات دقة | ✅ يعمل |
| Auto Scanner (تشغيل/إيقاف، اختيار الأسواق، منع التكرار) | ✅ يعمل |
| تحليل صور الشارت (PNG/JPG/JPEG/WEBP) + فحص الجودة | ✅ يعمل التحقق من الصور؛ التحليل النصي يحتاج `MISTRAL_API_KEY` |
| Mistral للإشارات والصور | ✅ الكود جاهز ومختبر؛ يحتاج مفتاحاً حقيقياً |
| OTC و SMARTY | ⛔ يظهر `DATA UNAVAILABLE` حتى توصيل جسر ExpertOption موثّق (`EO_BRIDGE_URL`/`EO_BRIDGE_KEY`) |
| تنفيذ صفقات تلقائي | ❌ غير موجود بالتصميم |

## 2. هيكل المشروع

```
bot/          واجهة Telegram (handlers, keyboards, middleware)
engines/      forex/gold/otc/smarty providers wrappers + technical + smc + signals
providers/    قاعدة المزودين، الكتالوج، التحقق، الـ registry
ai/           Mistral text + vision، فحص الصور
services/     scanner، signal tracker، statistics
database/     SQLAlchemy models + repository
tests/        pytest suite (58 اختباراً)
docs/         DATA-SOURCES.md، TEST-REPORT.md
main.py       نقطة التشغيل (Polling)
```

## 3. التشغيل محلياً

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # ثم املأ TELEGRAM_BOT_TOKEN على الأقل
python main.py
```

قبل تشغيل البوت يمكنك التحقق من مصادر البيانات:

```bash
PYTHONPATH=. python scripts/live_smoke.py
```

## 4. المتغيرات المطلوبة

| المتغير | مطلوب؟ | الوصف |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | توكن البوت من @BotFather |
| `TELEGRAM_CHAT_ID` | اختياري | لقفل البوت على مستخدم/محادثة واحدة |
| `DATABASE_URL` | اختياري | افتراضياً SQLite؛ على Railway استخدم PostgreSQL |
| `MISTRAL_API_KEY` | اختياري | لتحليل AI وتحليل الصور |
| `MISTRAL_MODEL` | اختياري | افتراضياً `mistral-small-latest` |
| `MISTRAL_VISION_MODEL` | اختياري | افتراضياً `pixtral-12b-2409` |
| `TWELVE_DATA_API_KEY` | اختياري لكنه مهم | بدونه demo mode يدعم EUR/USD و USD/JPY فقط |
| `EO_BRIDGE_URL` / `EO_BRIDGE_KEY` | اختياري | جسر OTC/Smarty موثّق |
| `SCANNER_ENABLED`, `SCAN_MARKETS`, `MAX_SCAN_SIGNALS`, `MIN_CONFIDENCE` | اختياري | إعدادات الماسح |
| `LOG_LEVEL` | اختياري | INFO افتراضياً |

## 5. النشر على Railway

1. ادفع المشروع إلى GitHub (تم ربط المستودع).
2. في Railway: **New Project → Deploy from GitHub repo**.
3. Railway يقرأ `railway.json` + `Dockerfile` ويشغّل `python main.py`.
4. أضف المتغيرات من قسم **Variables** (على الأقل `TELEGRAM_BOT_TOKEN`).
5. للتخزين الدائم: أضف **PostgreSQL** من Railway وانسخ `DATABASE_URL` (سيتحول تلقائياً إلى `postgresql+asyncpg://`).
6. استخدم **نسخة واحدة فقط** (numReplicas=1) — تشغيل نسختين Polling يعطي `TelegramConflictError` (والبوت يوضح ذلك في اللوج ويتوقف).

> البوت يعمل بـ Polling فقط، ولا يشغّل Webhook في نفس الوقت.

## 6. ملاحظات الصدق والبيانات

- لا تُستخدم أسعار Forex بدلاً من OTC أو Smarty مطلقاً.
- كل إشارة تعرض مصدر بياناتها، وكل تحقق يعرض مصدر سعر الإغلاق.
- الأسعار القديمة أو الشموع غير الصالحة تُرفض قبل التحليل.
- بدون مصدر متوافق تظهر رسالة `DATA UNAVAILABLE` ولا تُصدر إشارة.
- التفاصيل الكاملة في `docs/DATA-SOURCES.md` وتقرير الاختبار في `docs/TEST-REPORT.md`.
