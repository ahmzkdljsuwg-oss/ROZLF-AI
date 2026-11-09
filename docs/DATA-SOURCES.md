# DATA SOURCES — ROZLF AI

هذا التقرير يوثّق ما تم فحصه فعلياً في 2026-11. لا يحتوي على أي ادعاء بتوافق لم يُختبر.

## 1. المصادر المستخدمة فعلياً

### Twelve Data (FOREX / GOLD — شموع)
- Endpoint: `https://api.twelvedata.com/time_series`
- تم اختبار `EUR/USD`, `interval=1min` بنجاح وأعاد شموع OHLC حقيقية (بدون مفتاح، وضع demo).
- مع مفتاح `TWELVE_DATA_API_KEY` تزيد الحصص والأصول المتاحة.
- القيود: حدود الطلبات في وضع demo، وقد تُرفض بعض الأزواج. عند الفشل يتحول المشروع إلى مزود آخر أو يعيد `DATA UNAVAILABLE`.

### Swissquote public quotes (FOREX / GOLD — سعر لحظي)
- Endpoint: `https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/{symbol}`
- تم اختباره وأعاد bid/ask مع timestamp. يُستخدم للسعر الحالي وللتحقق من نتيجة الإشارة.
- لا يوفّر شموعاً؛ الشموع تأتي من Twelve Data.

### ExpertOption Bridge (OTC / SMARTY — اختياري)
- أي مصدر OTC أو Smarty يجب أن يمر عبر `EO_BRIDGE_URL` + `EO_BRIDGE_KEY` يوفّرهما المستخدم.
- العقد المدعوم: `GET /candles` و`GET /quote` مع التحقق من أن السوق المُعاد يطابق السوق المطلوب.
- بدون إعداد الجسر: يظهر `DATA UNAVAILABLE` ولا تُصدر أي إشارة. **لا يتم استخدام أسعار Forex مكان OTC أو Smarty.**

## 2. مستودعات GitHub التي تم فحصها

| المستودع | النجوم | آخر تحديث | الترخيص | ما يقدمه | التوافق / القيود |
|---|---|---|---|---|---|
| [ChipaDevTeam/ExpertOptionApi](https://github.com/ChipaDevTeam/ExpertOptionApi) | 6 | 2026-10 | MIT | WebSocket غير رسمي: تسجيل دخول، قائمة أصول (`action: assets`)، شموع (`subscribeCandles`)، أوامر تداول | لا يذكر Smarty أو OTC صراحةً في الشيفرة أو README؛ يتطلب حساباً وتوكن؛ غير مُختبر هنا. يصلح كمرجع لعقد WebSocket فقط |
| [Anthonyzok521/server_expert_option_read_file](https://github.com/Anthonyzok521/server_expert_option_read_file) | 0 | 2026-10 | MIT | قراءة ملفات/بيانات ExpertOption | غير موثّق، لم يُختبر |
| zayed331S-max/expertoption-signal-bot | 0 | 2026-10 | — | بوت إشارات | لا شيفرة مصدر موثوقة للأسعار |
| allroundadvert/ExpertOptionAssistant | 0 | 2026-08 | — | مساعد | غير مناسب كمصدر بيانات |
| kyanwh1-alt/ExpertOption- | 0 | 2026-07 | — | تجريبي | غير موثّق |

### نتائج البحث عن Smarty / OTC
- `expertoption+smarty` → **0 مستودعات**
- `expertoption+otc` → **0 مستودعات**
- لذلك لا يوجد مصدر عام موثّق لأسعار ExpertOption OTC أو Smarty حتى تاريخ التقرير. المشروع لا يدّعي دعماً حقيقياً لهما بدون جسر موثّق.

## 3. مصادر قريبة تم استبعادها

| المصدر | السبب |
|---|---|
| PocketOptionApi (chema-creator) | منصة مختلفة؛ أسعارها ليست أسعار ExpertOption |
| Quotex / Deriv / IQ Option wrappers | منصات مختلفة |
| MT4/MT5 bridges | تتطلب حساب وسيط؛ ليست ExpertOption |
| `xapi-python` (pawelkn) | بروتوكول xStation (XTB) وليس ExpertOption |

## 4. قواعد الاعتماد
1. لا تُستخدم بيانات شموع إذا كانت قديمة أو ناقصة (`engines/validation.py`).
2. لا يُسمح بمزج بيانات سواق مختلفة للتحقق من إشارة واحدة.
3. مصدر الإشارة يُذكر في كل رسالة، ومصدر التحقق يُحفظ في قاعدة البيانات.
4. أي أصل بلا مصدر متوافق يظهر له `DATA UNAVAILABLE`.

## 5. التوصية لمصادر OTC / Smarty
- استخدم جسراً مقفلاً (bridge) يتحدث مباشرة إلى حساب ExpertOption المسجّل، ويُرجع:
  `{"asset": "...", "market": "OTC|SMARTY", "timeframe": "1min", "candles": [{"time", "open", "high", "low", "close"}], "source": "..."}`
- يجب أن يتحقق الجسر من مطابقة اسم الأصل والسوق والتوقيت، وأن يرفض الأسعار القديمة.
- عند رفض الجسر للطلب سيظهر `DATA UNAVAILABLE` بدلاً من إشارة.
