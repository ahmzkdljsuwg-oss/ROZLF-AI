# ROZLF-EO-BRIDGE

خدمة مستقلة (Read-Only) تقرأ بيانات **ExpertOption** الحقيقية وتقدمها للبوت ROZLF AI فوق HTTPS.
لا تنفذ صفقات، ولا تسجل الدخول بكلمة مرور، ولا تولد أسعاراً وهمية: تعتمد على **جلسة ExpertOption حقيقية** يمررها المشغل عبر `EO_TOKEN`.

- السوق المدعوم من البوت عبر هذا الجسر: **OTC** و **SMARTY** (ويمكن أيضاً قراءة **GOLD / FOREX** إن كان الحساب يوفرهما).
- إن غاب `EO_TOKEN` أو كان منتهياً أو كان الأصل غير متاح: تُرجع الخدمة خطأ صريحاً (`EO_TOKEN_MISSING` / `AUTH_FAILED` / `UNSUPPORTED_SYMBOL` / `INACTIVE_ASSET`) وليس بيانات مزيفة.

---

## 1) المتغيرات

| المتغير | إلزامي | الوصف |
|---|---|---|
| `EO_BRIDGE_KEY` | نعم | مفتاح سري يتحقق منه كل طلب بيانات عبر ترويسة `X-API-Key` |
| `EO_TOKEN` | نعم للبيانات | توكن جلسة ExpertOption الحقيقية (من حسابك) |
| `EO_REGION` | لا | `EUROPE` (افتراضي) أو `INDIA` / `HONG_KONG` / `SINGAPORE` / `UNITED_STATES` أو رابط `wss://` كامل |
| `EO_DEMO` | لا | `true` سياق تجريبي، `false` سياق حقيقي (قراءة فقط في الحالتين) |
| `EO_HISTORY_SECONDS` | لا | طول نافذة التاريخ المطلوبة (افتراضي 7200) |
| `PORT` | لا | منفذ HTTP (Railway يمرره تلقائياً) |
| `LOG_LEVEL` | لا | `INFO` افتراضياً |

### كيف تحصل على `EO_TOKEN` من حسابك؟
1. افتح `https://app.expertoption.com` وسجّل الدخول في متصفحك.
2. اضغط F12 ← تبويب **Network** ← فلتر **WS** ← أعد تحميل الصفحة.
3. افتح رسالة WebSocket وأرسل أي رسالة (`ping` مثلاً)، ثم ابحث في الرسائل الصادرة عن الحقل `"token"`.
4. انسخ قيمة التوكن (سلسلة طويلة). هذا توكن جلسة، وليس كلمة مرور، وينتهي عند تسجيل الخروج.

---

## 2) التشغيل محلياً

```bash
cd eo_bridge
cp .env.example .env      # ثم املأ EO_BRIDGE_KEY و EO_TOKEN
set -a && . ./.env && set +a
python -m eo_bridge.main
```

ثم:

```bash
curl -s localhost:8080/health
curl -s -H "X-API-Key: $EO_BRIDGE_KEY" "localhost:8080/assets?market=otc"
curl -s -H "X-API-Key: $EO_BRIDGE_KEY" "localhost:8080/discover"
curl -s -H "X-API-Key: $EO_BRIDGE_KEY" "localhost:8080/smarty?timeframe=1min&limit=60"
curl -s -H "X-API-Key: $EO_BRIDGE_KEY" "localhost:8080/quote?market=otc&symbol=EURUSD"
curl -s -H "X-API-Key: $EO_BRIDGE_KEY" "localhost:8080/candles?market=otc&symbol=EURUSD&timeframe=5min&limit=120"
```

فحص حقيقي متكامل (سوكيت ExpertOption مباشرة أو الخدمة المنشورة):

```bash
python -m eo_bridge.scripts.probe_real                  # فحص اتصال السوكيت الحقيقي
EO_TOKEN=... python -m eo_bridge.scripts.probe_real     # يجب أن يطبع أعداد الأصول الحقيقية
BRIDGE_URL=https://<service>.up.railway.app EO_BRIDGE_KEY=... python -m eo_bridge.scripts.probe_real --http
```

---

## 3) واجهة الـ API

| المسار | الوصف |
|---|---|
| `GET /health` | الحالة: `configured`, `connected`, `assets`, `last_error` (بدون مفتاح) |
| `GET /assets?market=otc` | الأصول الحقيقية المتاحة مع `id` و`market` |
| `GET /discover` | اكتشاف تلقائي: عدد أصول كل سوق + قائمة OTC الحقيقية + حالة Smarty + Gold |
| `GET /smarty?timeframe=1min&limit=120` | Endpoint مخصص لـ Smarty (`SMRTY`, id 240): بيانات الأصل + السعر + الشموع |
| `GET /quote?market=otc&symbol=EURUSD` | `bid`, `ask`, `time`, `price_type=last_candle_close`, `stale_seconds` |
| `GET /candles?market=otc&symbol=EURUSD&timeframe=5min&limit=120` | شموع OHLC بالوقت الحقيقي |

- `/discover` هو مصدر الحقيقة لقائمة OTC: لا تُفترض الأصول، بل تُقرأ من حسابك في كل مرة.
- `/smarty` يبحث عن الأصل id=240 أولاً، ثم باسم `SMRTY`؛ وإن لم يكن معروضاً على حسابك يعيد `SMARTY_UNAVAILABLE` بدل تلفيق أصل.

- الترويسة المطلوبة: `X-API-Key: $EO_BRIDGE_KEY` (عدا `/` و`/health`).
- الفريمات: `1min, 5min, 15min, 30min, 1h` (وأي عدد ثوانٍ صحيح).
- السعر الحالي يساوي إغلاق آخر شمعة 5 ثوانٍ من ExpertOption، وليس من منصة أخرى. الحقل `price_type` يوضح ذلك، و`stale_seconds` يفضح أي تأخر.
- `symbol` في الرد هو الرمز الذي طلبته (مثل `EURUSD`)، و`eo_symbol` هو اسم الأصل الحقيقي (مثل `EURUSD_OTC`).

---

## 4) النشر على Railway (خدمة مستقلة)

> الخدمة مستقلة تماماً عن بوت Telegram. يمكن تشغيلها وحذفها دون التأثير على البوت.

1. أنشئ **New Service ← Deploy from GitHub repo** واختر `ahmzkdljsuwg-oss/ROZLF-AI`.
2. في إعدادات الخدمة: **Root Directory = `eo_bridge`** (مهم جداً).
3. Railway سيقرأ `eo_bridge/railway.json` ويستخدم `Dockerfile` وأمر التشغيل `python -m eo_bridge.main` وفحص الصحة `/health`.
4. إن كان Start Command مضبوطاً يدوياً على `python main.py` داخل لوحة Railway فلا حاجة لتغييره:
   الصورة تضع مُشغّلاً حقيقياً في `/app/main.py` ينادي `eo_bridge.main`، والكود نفسه يبقى في `/app/eo_bridge`.
   سبب الأعطال القديمة `can't open file '/app/main.py'` هو أن الصورة كانت تحتوي الحزمة فقط في `/app/eo_bridge`.
5. لا تغيّر Root Directory عن `eo_bridge`، ولا تضع أمر تشغيل يخص بوت التليجرام (بدون `scripts/verify_build.py`).
6. أضف المتغيرات: `EO_BRIDGE_KEY`, `EO_TOKEN`, `EO_REGION`, `EO_DEMO`.
7. من **Settings ← Networking ← Generate Domain** احصل على رابط HTTPS.
8. أضف في خدمة البوت المتغيرات: `EO_BRIDGE_URL=https://<الرابط>` و`EO_BRIDGE_KEY=<نفس المفتاح>`.
9. تحقق فعلياً:
   ```bash
   curl -s https://<الرابط>/health
   curl -s -H "X-API-Key: $EO_BRIDGE_KEY" "https://<الرابط>/candles?market=otc&symbol=EURUSD&timeframe=1min&limit=60"
   ```

### أمر التشغيل
```
python -m eo_bridge.main
```

### Docker محلياً
```bash
docker build -t rozlf-eo-bridge ./eo_bridge
docker run --rm -p 8080:8080 -e EO_BRIDGE_KEY=... -e EO_TOKEN=... rozlf-eo-bridge
```

---

## 5) حدود صريحة (لا تُخفى)

- Smarty في ExpertOption يظهر كأصل واحد `SMRTY` (id=240) وليس أزواجاً. لذلك أي طلب `market=smarty&symbol=EURUSD` يُرفض بـ`UNSUPPORTED_SYMBOL` بدل تلفيق أزواج غير موجودة.
- أصول OTC المتاحة تعتمد على الحساب والوقت؛ `/assets?market=otc` هو المصدر الوحيد للحقيقة.
- توكن الجلسة ينتهي عند تسجيل الخروج أو انتهاء صلاحيته؛ الخدمة تعيد المحاولة تلقائياً لكنها لا تستطيع تجديد التوكن بنفسها (لا كلمات مرور ولا متصفح على السيرفر).
- الاتصال بـ `wss://fr24g1eu.expertoption.com/` مفحوص من بيئة العمل، لكن **وصول البيانات لم يُثبت بعد** لأن التوكن غير متوفر. لا تُعلن الخدمة جاهزة للبيانات قبل `probe_real` بنجاح.

---

## 6) الاختبارات

```bash
python -m pytest eo_bridge/tests -q
```

الاختبارات تشغّل سوكيت وهمياً (Mock) يقلد رسائل ExpertOption للتحقق من:
التحقق بالمفتاح، `/health`، تصنيف OTC/Smarty/Gold، رفض الأزواج غير الموجودة، شكل الشموع وترتيبها الزمني، ورفض الفريمات غير المدعومة.
نتائج الـMock لا تُعد دليلاً على وصول بيانات حقيقية؛ الدليل الوحيد هو `probe_real` مع `EO_TOKEN`.
