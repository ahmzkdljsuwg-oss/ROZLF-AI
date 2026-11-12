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
| محرك استراتيجيات (SMC/ICT/Price Action/Trend/Momentum) | ✅ يعمل مع درجات توافق أدلة وشروط إبطال |
| تحليل صور الشارت | ❌ أُزيل بالكامل (زر + handlers + اعتماديات) |
| Mistral لتحليل الإشارات | ✅ يعمل؛ يحتاج مفتاحاً حقيقياً |
| SMARTY و FOOTBALL/LUXURY/AI/CRICKET | ✅ محرك مستقل لكل سوق؛ تتطلب جسر ExpertOption موثّقاً (`EO_BRIDGE_URL`/`EO_BRIDGE_KEY`)، وبدونه تظهر `DATA UNAVAILABLE` |
| OTC | ❌ خارج المشروع بالكامل (لا أزرار، لا ماسح، لا إشارات) |
| قائمة رئيسية: كل سوق بزر مستقل + SMART/MANUAL DURATION | ✅ يعمل |
| 🚀 Open Mini App داخل Telegram (6 أسواق، نفس المحرك) | ✅ زر WebApp + زر القائمة الدائم عبر setChatMenuButton |
| تنفيذ صفقات تلقائي | ❌ غير موجود بالتصميم |

## 2. هيكل المشروع

```
bot/          واجهة Telegram (handlers, keyboards, middleware)
engines/      markets (ملف مستقل لكل سوق) + technical + smc + strategies + signals
providers/    قاعدة المزودين، الكتالوج، التحقق، الـ registry
ai/           Mistral لتحليل الإشارات النصية
engines/strategies/  محرك الاستراتيجيات الموحّد
engines/backtest/    اختبار تاريخي سببي (walk-forward)
services/     scanner، signal tracker، statistics
database/     SQLAlchemy models + repository
tests/        pytest suite (188+ اختباراً)
mini_app/     Telegram Mini App (API + static UI)
docs/         DATA-SOURCES.md، TEST-REPORT.md، BACKTEST-RESULTS.md
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
| `MISTRAL_API_KEY` | اختياري | لتحليل AI النصي |
| `MISTRAL_MODEL` | اختياري | افتراضياً `mistral-small-latest` |
| `MISTRAL_VISION_MODEL` | اختياري | افتراضياً `pixtral-12b-2409` |
| `TWELVE_DATA_API_KEY` | اختياري لكنه مهم | بدونه demo mode يدعم EUR/USD و USD/JPY فقط |
| `EO_BRIDGE_URL` / `EO_BRIDGE_KEY` | اختياري | جسر SMARTY ومؤشرات ExpertOption |
| `SCANNER_ENABLED`, `SCAN_MARKETS`, `MAX_SCAN_SIGNALS`, `MIN_CONFIDENCE` | اختياري | إعدادات الماسح |
| `ENGINE_API_URL` | مطلوب لخدمة الويب فقط | رابط خدمة البوت التي تملك المحرك الحقيقي؛ توجّه خدمة الويب طلبات Mini App الموثقة إليه (initData يُتحقق منه في خدمة البوت) |
| `LOG_LEVEL` | اختياري | INFO افتراضياً |

## 5. النشر على Railway

1. ادفع المشروع إلى GitHub (تم ربط المستودع).
2. في Railway: **New Project → Deploy from GitHub repo**.
3. Railway يقرأ `railway.json` + `Dockerfile`، ويشغّل الأمر:
   `sh -c "python scripts/verify_build.py && exec python main.py"`.
   أي أن كل بناء وتشغيل يطبع `ROZLF BUILD SHA` ويتأكد أن `main.py` لا يحتوي
   `set_my_bot_commands`؛ عند وجوده يفشل البناء/التشغيل برسالة `ROZLF BUILD CHECK FAILED`.
   إن ظهر SHA قديم في السجل فهذا يعني أن Railway لم يسحب آخر `main` وتجب إعادة الربط/Redeploy.
4. أضف المتغيرات من قسم **Variables** (على الأقل `TELEGRAM_BOT_TOKEN`).
5. للتخزين الدائم: أضف **PostgreSQL** من Railway وانسخ `DATABASE_URL` (سيتحول تلقائياً إلى `postgresql+asyncpg://`).
6. استخدم **نسخة واحدة فقط** (numReplicas=1) — تشغيل نسختين Polling يعطي `TelegramConflictError` (والبوت يوضح ذلك في اللوج ويتوقف).

> البوت يعمل بـ Polling فقط، ولا يشغّل Webhook في نفس الوقت.

## 6. ROZLF MINI APP

يُخدم التطبيق من نفس خدمة الويب على `/mini-app/`، ويضيف زراً واحداً في القائمة الرئيسية.
الرابط العام يُؤخذ من `MINI_APP_URL` أو `PUBLIC_BASE_URL` أو `RAILWAY_PUBLIC_DOMAIN`.
التفاصيل الكاملة: `docs/MINI-APP.md`.

## 7. ملاحظات الصدق والبيانات

- لا تُستخدم أسعار Forex بدلاً من SMARTY أو أي سوق مؤشرات مطلقاً. OTC غير مدعوم في هذه المرحلة.
- كل إشارة تعرض مصدر بياناتها، وكل تحقق يعرض مصدر سعر الإغلاق.
- الأسعار القديمة أو الشموع غير الصالحة تُرفض قبل التحليل.
- بدون مصدر متوافق تظهر رسالة `DATA UNAVAILABLE` ولا تُصدر إشارة.
- التفاصيل الكاملة في `docs/DATA-SOURCES.md`، ونتائج Task M في `docs/TASK-M-REPORT.md`، وتقرير الاختبار في `docs/TEST-REPORT.md`.
