# ROZLF AI — تقرير المهمة F

## 1) الاستراتيجيات التي دُرست
SMC/ICT، Price Action (Al Brooks)، Trend Following (Turtle/EMA/ADX)، Momentum (Linda Raschke/Bollinger)، وإدارة المخاطر (Mark Douglas)، وCAN SLIM كمبدأ قوة نسبية. المصادر الكاملة والقيد على الجلسات في `docs/STRATEGY-SOURCES.md`.

## 2) الاستراتيجيات المنفَّذة فعلياً
SMC: BOS/CHoCH، FVG، Order Blocks، Liquidity Sweep/Raid، Equal Highs/Lows، Premium/Discount.
ICT: Kill Zones، Silver Bullet، Displacement/MSS، OTE، FVG Entry — فقط على Forex ذي جلسات حقيقية.
PA: S&R، Breakout & Retest، False Breakout، Pin Bar/Rejection، Engulfing، Inside Bar، Trendline Break.
Trend: EMA 9/21/50/200، MA Cross، ADX/DI، Supertrend، MACD، HH/HL وLH/LL، MTF.
Momentum: RSI/MACD Divergence، Stochastic، Bollinger، ATR، Mean Reversion، Momentum Breakout؛ VWAP يُحسب فقط عند حجم موثوق ولا يُستخدم كدليل.

## 3) شروط كل استراتيجية
لكل إشارة `reason` و`invalidation` في `engines/strategies/engine.py`، ولها عائلة أدلة مستقلة. التفاصيل في `docs/STRATEGY-SOURCES.md`.

## 4) نتائج الاختبار
- اختبار تاريخي حقيقي (Yahoo FX) على 9 أزواج × فريمين × مدتين = 36 تشغيلاً، مع walk-forward وOOS: `docs/BACKTEST-RESULTS.md`.
- العينات 300 شمعة/تشغيل؛ لا تُعرض نسب نجاح في البوت لهذا السبب.
- اختبارات الوحدات: 90 ناجحة + 3 متجاوزة في الجذر، 21 ناجحة في الجسر.
- تراجع بعض الأزواج في OOS (مثل GBP/USD 1m) موثّق ولم يُخفَ.

## 5) الملفات المعدّلة
حُذف: `ai/vision.py`, `bot/handlers/images.py`, `tests/test_vision.py`.
أُضيف: `engines/strategies/`, `engines/backtest/`, `scripts/backtest_forex.py`, `tests/test_strategies.py`, `tests/test_backtest.py`, `docs/STRATEGY-SOURCES.md`, `docs/BACKTEST-RESULTS.md`, `docs/backtest-results.json`.
عُدّل: `engines/technical/indicators.py`, `engines/technical/analyzer.py`, `bot/keyboards/menus.py`, `bot/handlers/menus.py`, `bot/formatting.py`, `main.py`, `ai/mistral.py`, `config.py`, `requirements.txt`, `README.md`, `docs/TEST-REPORT.md` واختبارات الواجهة.

## 6) الاختبارات
ناجحة: 90 + 21. لم يُشغّل أي اختبار حقيقي على SMARTY/AI/Football/Luxury تاريخياً لعدم توفر عمق تاريخي كافٍ من الجسر.

## 7) حالة الأسواق بعد التحديث
Forex: يعمل (Twelve Data/Yahoo/Swissquote كما كان). SMARTY: يعمل عبر الجسر (asset 240). AI 285 / Football 278 / Luxury 286: تعمل عبر الجسر. Gold وOTC: لم يُلمسا ولم يُضافا للوحة.

## 8) إزالة تحليل الصور
أُزيل الزر والقوائم والـ handlers والاختبارات واعتمادية Pillow وكود الرؤية في Mistral. لا يوجد أي callback لتحليل الصور.

## 9) اللوحة الحالية
القائمة الرئيسية خمسة أزرار فقط: تحليل تلقائي، الأسواق، الترند والاستراتيجيات، سجل الإشارات، الإعدادات. الأسواق تعرض Forex/SMARTY/AI/Football/Luxury فقط.
