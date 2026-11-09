# ROZLF AI — Advanced Trading Intelligence (Telegram)

بوت تحليل تداول احترافي يعمل بالكامل داخل Telegram: تحليل فوركس و OTC وSmarty، تحليل صور الشارت، ماسح آلي، إشارات حقيقية مع تحقق WIN/LOSS من السعر الفعلي، وسجل وإحصاءات دقة.

> **تنبيه:** التحليل أداة مساعدة لاتخاذ القرار فقط. لا يوجد ضمان ربح، ولا ينفّذ البوت أي صفقة، ولا يتصل بحساب تداول. كل الأرقام المعروضة مأخوذة من مصدر بيانات حقيقي وموسوم بمصدره.

---

## 1. ما تم بناؤه فعلياً

| المحرك | الحالة | المصدر |
| --- | --- | --- |
| فوركس + الذهب (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, NZDUSD, USDCHF, XAUUSD) | يعمل ببيانات حقيقية | Twelve Data (شموع) |
| تحقق السبريد والحداثة | يعمل | Swissquote public quotes (bid/ask فقط، لا شموع) |
| OTC | يعمل **فقط** عند وجود جسر ExpertOption للقراءة فقط | `EO_BRIDGE_URL` |
| SMARTY | يعمل **فقط** عند وجود نفس الجسر | `EO_BRIDGE_URL` |
| التحليل الفني (RSI, MACD, EMA 9/21/50/200, SMA, Bollinger, ATR, Stochastic, S/R, Volume) | يعمل | حساب محلي على الشموع الحقيقية |
| SMC (BOS, CHoCH, FVG, Order Blocks, Liquidity Sweeps, Market Structure, Premium/Discount) | يعمل | حساب محلي |
| تحليل النص بالذكاء الاصطناعي | Mistral (نصي) | `MISTRAL_API_KEY` |
| تحليل صور الشارت | Mistral Vision | `MISTRAL_VISION_MODEL` |
| إشارات بمدة 30s → 1h | يعمل، والمدة تُختار حسب الفريم | محلي |
| تحقق WIN/LOSS/DRAW بعد انتهاء المدة | يعمل من سعر فعلي (quote) | مصدر البيانات |
| صور الشارت | تُرسم من الشموع الحقيقية (matplotlib) | محلي |

**لا يُخترع سعر ولا نتيجة.** إذا لم يوجد مصدر بيانات لسوق معيّن، يعرض البوت `DATA UNAVAILABLE` بدلاً من استخدام بيانات سوق آخر.

---

## 2. التثبيت المحلي

```bash
git clone <this-repo> rozlf-ai
cd rozlf-ai
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # ثم املأ القيم
python -m rozlf
```

يعمل البوت بـ **Polling** (لا يحتاج Webhook URL). للتأكد من الإعدادات:

```bash
python -m pytest -q                            # 43 اختباراً
curl -s localhost:8080/health | python -m json.tool
```

---

## 3. متغيرات البيئة

| المتغير | إلزامي | الوصف |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | نعم | توكن البوت من @BotFather |
| `TELEGRAM_CHAT_ID` | نعم عملياً | المحادثة المسموح لها باستخدام البوت (أرسل `/id` لمعرفتها). بدونه لا تُرسل إشارات تلقائية. |
| `MISTRAL_API_KEY` | لا | بدونها يستمر التحليل الفني المحلي ويُوسم بوضوح أنه ليس تحليل Mistral |
| `MISTRAL_MODEL` | لا | الافتراضي `mistral-small-latest` |
| `MISTRAL_VISION_MODEL` | لا | يجب أن يكون موديلاً يدعم الصور (مثل `pixtral-12b-2409`) |
| `TWELVE_DATA_API_KEY` | نعم للفوركس | شموع حقيقية. خطة `demo` المجانية تغطي EUR/USD فقط |
| `EO_BRIDGE_URL` / `EO_BRIDGE_KEY` | لا | جسر قراءة فقط لبيانات OTC/Smarty؛ بدونهما يظهر DATA UNAVAILABLE |
| `DATABASE_URL` | لا | الافتراضي SQLite. للإنتاج: PostgreSQL (`postgresql+asyncpg://...`) |
| `LOG_LEVEL`, `PORT` | لا | `INFO`, `8080` |
| `SCANNER_INTERVAL_SECONDS` | لا | 90 |
| `MIN_SIGNAL_SCORE` | لا | 62 |
| `MAX_SIGNALS_PER_SCAN` | لا | 3 |
| `SIGNAL_COOLDOWN_MINUTES` | لا | 45 (منع تكرار نفس الأصل/الاتجاه/الفريم) |
| `DEFAULT_EXPIRY_SECONDS` | لا | 300 |

لا تُطبع أي أسرار في السجلات: `logging_setup.RedactingFilter` يحجب التوكن والمفاتيح.

---

## 4. واجهة البوت

`/start` يعرض:

1. تحليل سمارتي (SMARTY)
2. تحليل OTC
3. تحليل فوركس
4. الماسح الآلي — تشغيل/إيقاف + مسح فوري
5. تحليل صورة — أرسل PNG/JPG/WEBP حتى 10MB
6. الإشارات الحية
7. سجل الإشارات (صفحات)
8. إحصاءات الدقة (محسوبة من النتائج المحسومة فقط)
9. الإعدادات — المصادر، Mistral، مدة الإشارة

أوامر مساندة: `/menu`, `/scan`, `/stop`, `/live`, `/stats`, `/status`, `/health`, `/id`, `/ping`, `/version`, `/help`.

كل زر مرتبط بدالة حقيقية؛ لا أزرار شكلية.

---

## 5. دورة حياة الإشارة

1. جلب شموع حقيقية من المصدر (Twelve Data للفوركس، الجسر لـ OTC/Smarty).
2. فحص الجودة: عدد كافٍ، OHLC منطقي، فجوات، حداثة، سبريد عند توفره.
3. تحليل فني + SMC → درجة ثقة وأسباب مكتوبة.
4. رفض تلقائي عند `NO TRADE` أو الدرجة < الحد أو تكرار حديث أو تجاوز الحد اليومي.
5. حفظ في قاعدة البيانات ثم إرسال صورة الشارت + بطاقة الإشارة إلى Telegram.
6. بعد انتهاء المدة: جلب سعر فعلي جديد؛ إذا كان السعر أقدم من وقت الانتهاء يُؤجل الحسم (لا تخمين).
7. `WIN` / `LOSS` / `DRAW` من السعر الفعلي، ثم إشعار إغلاق.

---

## 6. النشر على Render

1. ارفع المشروع إلى GitHub.
2. Render → New → Blueprint → اختر المستودع (يقرأ `render.yaml`).
3. أدخل المتغيرات السرية عند الطلب (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `MISTRAL_API_KEY`, `TWELVE_DATA_API_KEY`, وربما `EO_BRIDGE_*`).
4. Health check: `/health` (يُعيد 503 قبل جاهزية المصادر الأساسية).
5. راقب السجلات حتى ترى `bot started as @...`.

### قيود تشغيلية يجب معرفتها

- **Render لا يضمن التشغيل 24/7 على الخطة المجانية**: الخدمة تنام عند عدم استخدام HTTP، وبوتات Telegram على Polling لا تُبقي الخدمة مستيقظة. للإنتاج المستمر استخدم خطة مدفوعة أو Keep-alive خارجي مسموح.
- القرص **مؤقت**: SQLite يُفقد عند إعادة النشر. استخدم PostgreSQL (`DATABASE_URL`) للإنتاج.
- البوت يحتاج **اتصالاً صادراً** إلى `api.telegram.org` و`api.twelvedata.com` و`api.mistral.ai`.
- `ExpertOption` ليس له API عام موثق للتداول الآلي. لذلك الجسر هنا **قراءة فقط** (شموع) ولا ينفذ صفقات، ولا يخزن Session Token.

---

## 7. الاختبارات

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

التفاصيل الكاملة والنتائج الفعلية في [`docs/TEST-REPORT.md`](docs/TEST-REPORT.md)، ومصادر البيانات وتحققها في [`docs/DATA-SOURCES.md`](docs/DATA-SOURCES.md).

---

## 8. البنية

```
rozlf/
  config.py            إعدادات pydantic-settings
  providers/           Twelve Data, Swissquote, ExpertOption Bridge + registry + catalog
  engines/
    validation.py      جودة الشموع
    technical/         مؤشرات + SMC + محرك القرار
    signals/           المولّد، الماسح، المتتبّع، الإحصاءات
    image/             (تحليل الصور يتم عبر Mistral Vision)
  ai/mistral.py        نص + صور، أخطاء وRate Limit آمنة
  database/            SQLAlchemy async + SQLite/PostgreSQL
  services/            charts, notifier, signal_service, container, health
  bot/                 aiogram 3 routers, keyboards, texts, middlewares
tests/                 43 اختباراً (بيانات وهمية للاختبار فقط)
```

---

## 9. ما لا يفعله المشروع

- لا ينفذ صفقات ولا يتصل بحساب تداول.
- لا يستخدم واجهات ExpertOption غير موثقة ولا محاكاة نقرات.
- لا يخزن كلمات مرور أو Cookies أو Session Tokens.
- لا يضمن أي نتيجة ربح.
