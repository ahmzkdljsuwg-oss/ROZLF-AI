# ROZLF AI — MT5 Market Analysis

## 1. الوصول من Telegram

القائمة الرئيسية → **📊 MT5 ANALYSIS** → اختر الزوج → اختر المدة:

- ⏱️ 1 MINUTE
- ⏱️ 5 MINUTES
- ⏱️ 15 MINUTES
- ⏱️ 30 MINUTES
- ⏱️ 1 HOUR

النتيجة تعرض: BUY / SELL / NO TRADE، الزوج والمدة، السعر الحالي، وقت آخر تحديث،
الاتجاه، حالة Alligator، موقع السعر من EMA 200، قوة الإشارة والأسباب، ونقطة إبطال
التحليل ومستوى المخاطر. القسم **للتحليل فقط** ولا ينفذ أي صفقة.

## 2. بنية البيانات

```
MetaTrader 5 Terminal (Windows PC/VPS, logged in)
        │  MetaTrader5 Python API
        ▼
mt5_bridge/  (HTTP read-only, X-API-Key)
        │  HTTPS tunnel
        ▼
providers/mt5.py → providers/catalog.py → analyzer → bot formatter
```

- Railway لا يستطيع تشغيل منصة MT5 (لا يوجد Terminal/Windows)، لذلك Railway لا
  يتصل بـ MetaTrader5 مباشرة ولا يحتوي حزمة `MetaTrader5`.
- الجسر يقرأ فقط: `symbols_get`, `copy_rates_from_pos`, `symbol_info_tick`.
  لا توجد دوال تنفيذ صفقات في الكود.
- البيانات المعروضة هي بيانات MT5 فقط. لا يتم استخدام Yahoo أو Twelve Data
  كبديل ولا تُخلط معها.

## 3. الأزواج

- تُجلب القائمة من وسيط MT5 نفسه عبر `/symbols`.
- تُقبل أزواج الفوركس فقط (6 أحرف لاتينية) مثل `AUDCAD`, ويُدعم لاحقة الوسيط
  مثل `AUDCAD.a` أو `EURUSD_pro`.
- إذا وُجد أكثر من رمز لنفس الزوج، تُفضَّل نسخة Market Watch الظاهرة.
- الأزواج الـ28 المطلوبة موجودة في الكتالوج الأساسي، وأي زوج فوركس إضافي متاح
  لدى الوسيط يظهر تلقائياً في القائمة مع Pagination.
- لا يظهر أي زوج لا يعيده الوسيط فعلياً.

## 4. التحليل

- Williams Alligator: Jaw 13 (shift 8), Teeth 8 (shift 5), Lips 5 (shift 3).
- EMA 200 (نوع MA النظام الحالي، ويُعرض نوعه في النتيجة).
- الاتجاه العام وقوته (ADX عند توفره).
- الشموع اليابانية، الدعم والمقاومة، ATR، اختراق واختراق كاذب.
- تأكيد الدخول من شمعة مكتملة، ولا تُستخدم الشمعة الجارية كتأكيد.
- تعارض Alligator مع EMA 200 أو نقص البيانات → NO TRADE.

## 5. حماية البيانات

| الحالة | السلوك |
|---|---|
| Terminal غير متصل | `MT5 OFFLINE` — لا إشارة |
| شموع أقدم من `timeframe×2 + 120s` | `MT5_STALE_DATA` — لا إشارة |
| Tick أقدم من 180 ثانية | `MT5_STALE_TICK` — لا إشارة |
| رمز/سوق مختلف عن MT5 | `MT5_OFFLINE` / `MT5_SYMBOL_MISMATCH` |
| بيانات أقل من 200 شمعة مكتملة | NO TRADE بسبب عدم كفاية البيانات |
| Bridge غير مضبوط | `MT5_NOT_CONFIGURED` — يظهر MT5 OFFLINE |

## 6. إعداد Railway

أضف في خدمة البوت:

```
MT5_BRIDGE_URL=https://your-bridge-host
MT5_BRIDGE_KEY=<same random key as the bridge>
```

ثم أعد النشر. إذا لم يُضبط المتغيران يظل باقي البوت يعمل طبيعياً ويظهر MT5 OFFLINE
فقط داخل قسم MT5.

## 7. إعداد الجسر

راجع `mt5_bridge/README.md`. ملخص:

```powershell
cd mt5_bridge
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # set MT5_BRIDGE_KEY
python -m mt5_bridge.app
```

افتح منفذاً آمناً (Cloudflare Tunnel / Tailscale Funnel / Reverse Proxy مع TLS).
لا تعرض المنفذ الخام للإنترنت.

## 8. الاختبارات المنفذة

`tests/test_mt5.py` (156 حالة اختبار):

- كتالوج الأزواج الـ28.
- تطبيع رموز الوسيط (`AUDCAD.a`, `EURUSD_pro`, رفض غير الفوركس).
- بروتوكول الجسر عبر HTTP Mock: المصادقة، الرموز، الشموع، Quote.
- رفض مصدر غير MT5، رمز مختلف، شموع قديمة، Tick قديم، جسر غير مضبوط.
- تحليل حقيقي على شموع اصطناعية: Alligator + EMA 200 + مخرجات النتيجة.
- القوائم والأزرار والـ callbacks وصيغ النصوص.
- اختبار تكاملي للجسر نفسه: 401 بدون مفتاح، 200 بالشموع الصحيحة، 503 للبيانات القديمة.

`370 passed, 3 skipped` في كامل الحزمة بعد الإضافة.

## 9. ما لم يُختبر بعد

- لم يتم الاتصال بمنصة MT5 حقيقية أو حساب وسيط بعد، لأن ذلك يتطلب Terminal
  مسجل الدخول على جهاز/VPS. جميع اختبارات الجسر استخدمت عميل MT5 وهمياً (Mock)
  يطابق عقد البيانات، وليست دليلاً على بيانات وسيط حقيقي.
- لم تُختبر الأزواج الثمانية والعشرون والمدة الخمس على بيانات حقيقية حتى الآن.
- اختبار Telegram الفعلي يحتاج تشغيل الجسر أولاً. عندها اختبر كل زوج وكل مدة
  وتأكد من ظهور السعر ووقت التحديث أو MT5 OFFLINE.
