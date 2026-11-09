# ROZLF AI — SMARTY Fix Test Report (2026-11-09)

## ما تم تشغيله فعلياً

| الاختبار | الأمر | النتيجة |
|---|---|---|
| حزمة البوت كاملة | `.venv/bin/python -m pytest -q` | **77 passed, 3 skipped** |
| حزمة الجسر كاملة | `cd eo_bridge && ../.venv/bin/python -m pytest -q` | **21 passed** |
| اختبار مسار SMARTY | `pytest tests/test_smarty_pipeline.py -q` | **5 passed** (مصافحة، 240، شموع ms، ترتيب OHLC، توكن منتهي، إعادة اتصال، HTTP `/smarty`) |
| مسار البوت SMARTY | `pytest tests/test_smarty_flow.py -q` | **3 passed** (اكتشاف الأصل، سبب UNAVAILABLE، تحليل + RSI/MACD + رسالة الإشارة) |
| حارس البناء | `python scripts/verify_build.py` | `ROZLF BUILD CHECK OK` |

## ما يثبته الاختبار
- الجسر يرفض التوكن المنتهي برسالة `TOKEN_INVALID` بدلاً من `DISCONNECTED` أو محاولات لا نهائية.
- شموع SMARTY تُقرأ بأزمنة ثانية أو ميلي ثانية، وترتيب `[open, close, low, high]` يُعاد ترتيبه، والشمعة غير المتسقة تُرفض.
- الانقطاع يعيد الاتصال ويُعيد إرسال `subscribeCandles` (مسح الاشتراكات عند الإغلاق).
- `/assets?market=smarty` يرجع أصل 240 فقط، و`/smarty` يرجع شموعاً حديثة وإلا `SMARTY_STALE`.
- البوت يبني التحليل من بيانات SMARTY فقط، ويعرض RSI/MACD/الدعم/المقاومة والاتجاه والثقة، أو NO TRADE مع عدم إنشاء إشارة.

## ما لا يثبته
بوابة WebSocket محلية تحاكي شكل حمولة ExpertOption. **لم** تُختبر مصافحة حقيقية مع
`wss://fr24g1eu.expertoption.com/` ولا معرّف 240 من حساب حقيقي، لأن `EO_TOKEN` غير متوفر.
لإثبات التشغيل الحقيقي بعد ضبط `EO_TOKEN`:

```bash
curl -s "$EO_BRIDGE_URL/health" -H "X-API-Key: $EO_BRIDGE_KEY"
curl -s "$EO_BRIDGE_URL/discover" -H "X-API-Key: $EO_BRIDGE_KEY"
curl -s "$EO_BRIDGE_URL/assets?market=smarty" -H "X-API-Key: $EO_BRIDGE_KEY"
curl -s "$EO_BRIDGE_URL/smarty?timeframe=1min&limit=120" -H "X-API-Key: $EO_BRIDGE_KEY"
```
النجاح يعني: `connected=true`، `assets` تعرض id 240، و`/smarty` يرجع شموعاً `stale_seconds` صغيرة؛
وبعدها زر SMARTY في Telegram يعرض تحليلاً حقيقياً.
