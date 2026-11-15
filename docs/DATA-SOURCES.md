# DATA SOURCES — ROZLF AI

هذا التقرير يوثّق ما تم فحصه فعلياً في 2026-11. لا يحتوي على أي ادعاء بتوافق لم يُختبر.

## 1. المصادر المستخدمة فعلياً

### Twelve Data (FOREX / GOLD — شموع)
- Endpoint: `https://api.twelvedata.com/time_series`
- لا يوجد وضع demo ولا مفتاح مشترك: بدون `TWELVE_DATA_API_KEY` حقيقي يعتبر المزود غير مهيأ.
- عند الفشل أو غياب المفتاح تُعاد `DATA UNAVAILABLE` ولا تُصدر إشارة.
- القيود: حدود الخطة قد ترفض بعض الأزواج أو XAU/USD.

### Swissquote public quotes (FOREX / GOLD — سعر لحظي)
- Endpoint: `https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/{symbol}`
- تم اختباره وأعاد bid/ask مع timestamp. يُستخدم للسعر الحالي وللتحقق من نتيجة الإشارة.
- لا يوفّر شموعاً؛ الشموع تأتي من Twelve Data.

### ExpertOption Bridge (SMARTY / INDEX MARKETS — تم التحقق)
- أي مصدر OTC أو Smarty يجب أن يمر عبر `EO_BRIDGE_URL` + `EO_BRIDGE_KEY` يوفّرهما المستخدم.
- العقد المدعوم: `GET /candles` و`GET /quote` مع التحقق من أن السوق المُعاد يطابق السوق المطلوب.
- بدون إعداد الجسر: يظهر `DATA UNAVAILABLE` ولا تُصدر أي إشارة. **لا يتم استخدام أسعار Forex مكان أي سوق مؤشرات.**
- تحقق حقيقي سابق: الجسر أعاد شموع SMARTY حقيقية وربط أصول المؤشرات `278/285/286/276`؛ فحص `/health` في 2026-11 أعاد `connected=true` و`151` أصلاً.
- مسار OTC أُعيد في لوحة V2 (زر + ماسح + فحص صحة) لكنه مقيد بنفس الجسر: لا مزوّد OTC عام، وبدون `EO_BRIDGE_URL` تظهر `DATA UNAVAILABLE`. لا تُستخدم أسعار Forex أو منصات أخرى كبديل.

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
- لا يوجد مستودع عام موثّق لأسعار OTC. أما SMARTY فتم إثبات وصول شموعه عبر ExpertOption Bridge الخاص بالمشروع، وليس عبر مكتبة GitHub عامة. OTC وGOLD/SMARTY كلها تعتمد على الجسر أو مزوّد مرخّص، وأي فشل يظهر كـ `DATA UNAVAILABLE`.

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

## 6. مصدر Forex الاحتياطي — معطّل

- `providers/yahoo.py` بقي في الشيفرة للمرجع والاختبارات فقط، ولا يُسجّل في `build_registry`.
- السبب: Yahoo Finance واجهة غير رسمية وغير مرخّصة تجارياً؛ لا تُستخدم لبيانات التداول.
- FOREX وGOLD يعتمدان على Twelve Data بمفتاح حقيقي فقط. بدون مفتاح تظهر `DATA UNAVAILABLE`.

## 7. اكتشاف SMARTY من الجسر
- المصدر الأساسي: `GET /assets?market=smarty` من حساب ExpertOption الحقيقي.
- إن أعاد الجسر قائمة فارغة/فشلاً، يحاول البوت `GET /smarty` (معرّف 240) ويبني أصلاً ديناميكياً واحداً فقط من `payload.asset`.
- إن فشل الاثنان يظهر `SMARTY_UNAVAILABLE` ولا تُعرض أي عملة بديلة.

## 8. تشخيص مسار SMARTY (2026-11-09)

الأعراض المبلَّغ عنها: `ExpertOption socket closed`، `ExpertOption returned no assets`،
`token is invalid or expired`، و HTTP 503 على `/assets?market=smarty` وبيانات SMARTY.

الأسباب التي تم إثباتها بالكود والاختبار المحلي:

| السبب | الملف | الإصلاح |
|---|---|---|
| طلب `permessage-deflate` (`compress=15`) على WebSocket؛ بوابات ExpertOption تغلق المقبس في هذه الحالة | `eo_bridge/eo_client.py` | `compress=0` |
| إغلاق المقبس محلياً كان يلغي مهمة الاستقبال، فيموت `_supervise` ولا يوجد إعادة اتصال | `eo_bridge/eo_client.py` | `_wait_closed` يتعامل مع `CancelledError` كمحاولة منتهية |
| الاشتراكات لم تُمسح عند الانقطاع، فلا يُعاد إرسال `subscribeCandles` بعد الاتصال | `eo_bridge/eo_client.py` | مسح `_subscriptions` عند الإغلاق |
| أخطاء المصادقة كانت تُترجم إلى `DISCONNECTED` وتُعاد المحاولة كل ثانية | `eo_bridge/eo_client.py` | تصنيف `TOKEN_INVALID` / `AUTH_FAILED` وإرجاعها فوراً، وتهدئة إعادة المحاولة بعد 3 محاولات |
| أزمنة الشموع قد تصل بالميلي ثانية | `eo_bridge/eo_client.py` | `_normalise_ts` |
| ترتيب قيم الشمعة قد يكون `[open, close, low, high]` أو `[open, close, high, low]` | `eo_bridge/eo_client.py` | `_row_to_candle` يقبل أول ترتيب OHLC صالح ويرفض الشموع غير المتسقة |
| شموع بتوقيت مستقبلي تُفسد التحليل | `eo_bridge/eo_client.py` | استبعاد أي شمعة بعد `now + tf` |
| SMARTY قديم أو غير معروض | `eo_bridge/app.py` | `SMARTY_STALE` و`SMARTY_UNAVAILABLE` بدل إشارة |
| `/assets?market=smarty` كان يرجع 200 بقائمة فارغة | `eo_bridge/app.py` | 404 `SMARTY_UNAVAILABLE` |
| خطأ في اسم رمز SMARTY (`SMRTY` / `SMARTY`) كان يوقف التحليل | `providers/eobridge.py` | مطابقة أسماء SMARTY كمرادفات |

ما لم يُثبت بعد: لم يتوفر `EO_TOKEN` حقيقي، لذلك لم تُختبر المصافحة مع خادم
ExpertOption المباشر ولا معرّف 240 من حمولة حقيقية. كل الاختبارات أعلاه تُشغّل
بوابة WebSocket محلية تحاكي شكل الحمولة، وهي تثبت منطق الجسر لا الحساب الحقيقي.

## 9. مسار التحقق المستقل (Task L)

- `GET /verify/history?id=<asset>&timeframe=5sec&limit=1200` — عام للقراءة فقط، بلا أي مفاتيح.
- يعيد نفس شموع ExpertOption الحقيقية التي يراها البوت، مع `asset_id`، `symbol`، `market`، `active`، `connected`، `last_error`، وقائمة OHLC.
- الإطار الزمني والحد يُتحققان برمجياً؛ المعدل محدود إلى 120 طلباً/دقيقة لكل IP.
- الغرض: إجراء اختبارات Backtest حقيقية على البيانات المنشورة، لا على بيانات وهمية أو محلية.
- تحقق فعلي بعد النشر: 240 / 278 / 285 / 286 / 276 / 142 أعادت شموعاً حقيقية.

## 10. ملاحظة على Yahoo Forex

- `providers/yahoo.py` أعاد حالياً شموعاً مسطحة (`open = high = low = close`) لكل شمعة EUR/USD.
- لذلك لم تُستخدم بيانات Yahoo في تقرير Task L؛ تم استخدام بيانات ExpertOption الحقيقية للأصل 142.
- المشكلة في شكل الحمولة من Yahoo وليست في محرك التحليل، وتحتاج مراجعة منفصلة قبل الاعتماد عليها.
