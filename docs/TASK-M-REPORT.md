# ROZLF AI — TASK M REPORT

تاريخ التنفيذ: 2026-11-11
الأساس: `08a65b7` (main)

## 1. Commit الجديد

- كود Task M: `18ff7e6` — `Task M: per-market analysis profiles and market-first Telegram menu`.
- تقرير التوثيق والـ README داخل commit منفصل يليه.
- لم يُحذف أي commit أو فرع قديم.

## 2. الملفات المعدلة

جديد:
- `engines/markets/__init__.py` و`base.py` و`smarty.py` و`football.py` و`luxury.py` و`ai_index.py` و`cricket.py` و`forex.py`
- `tests/test_market_profiles.py`
- `docs/backtest-results-task-m.json`

معدل:
- `engines/technical/analyzer.py` — اختيار ملف السوق، رفض الفريم غير المدعوم، `UNSUPPORTED_FRAME`
- `engines/technical/evidence.py` — أوزان عائلات الأدلة لكل سوق، منع تكرار المؤشرات المترابطة، حدود الثقة
- `engines/strategies/engine.py` — تمرير ملف السوق، بوابات mean-reversion وICT
- `engines/signals/duration.py` — الفريمات ومدة الانتهاء من ملف السوق (لا من فريم الشموع)
- `services/health.py` و`services/scanner.py` — إزالة OTC وإضافة CRICKET
- `bot/keyboards/menus.py` و`bot/handlers/menus.py` و`bot/formatting.py` — القائمة الرئيسية والأسواق والمدة
- `config.py` و`.env.example` — `SCAN_MARKETS=FOREX,SMARTY,AI,FOOTBALL,LUXURY,CRICKET`
- `scripts/backtest_forex.py` — معاملات limit/step لاختبار أطول
- اختبارات UI وwiring وunified flow

## 3. شكل القائمة الرئيسية

```
🧠 SMARTY MARKET     ⚽ FOOTBALL INDEX
💎 LUXURY INDEX      🤖 AI INDEX
🏏 CRICKET INDEX     💱 FOREX MARKET
📡 LIVE SIGNALS
📜 SIGNAL HISTORY    📊 PERFORMANCE
⚙️ SETTINGS          🖥️ SYSTEM STATUS
```

- كل سوق زر مستقل ويدخل مباشرة إلى اختيار الأصل ثم SMART/MANUAL DURATION.
- OTC غير موجود في القائمة أو الماسح أو فحص الصحة أو الإعدادات.
- لا يوجد زر «تداول الآن» يجمع الأسواق.

## 4. محركات الأسواق

كل سوق له ملف مستقل في `engines/markets`:

| السوق | الفريمات | ADX floor | min families | مدة الانتهاء (LOW/NORMAL/HIGH) |
|---|---|---|---|---|
| SMARTY | 5s, 15s, 30s, 1m, 5m | 20 | 3 | 60 / 30 / 15 ثانية |
| FOOTBALL | 30s, 1m, 5m | 18 | 3 | 300 / 105 / 60 |
| LUXURY | 30s, 1m, 5m | 18 | 3 | 300 / 105 / 60 |
| AI INDEX | 30s, 1m, 5m | 20 | 3 | 105 / 60 / 30 |
| CRICKET | 30s, 1m, 5m | 22 | 3 | 105 / 60 / 30 |
| FOREX | 1m, 5m, 15m, 30m, 1h | 20 | 3 | 900 / 300 / 60 |

لكل ملف عتبة فصل اتجاه، مسافة دعم/مقاومة، سقف تمدد عن EMA21، حد جودة بيانات، وأوزان عائلات أدلة مختلفة. تحليل سوق بفريم لا يخصه يرفض بـ`UNSUPPORTED_FRAME` بدل تمرير بيانات سوق آخر.

## 5. قوة التحليل

- 18 نظاماً موجودة في `engines/strategies/engine.py`: SMC/ICT, BOS/CHoCH, FVG, Order Blocks, Liquidity Sweeps, Equal Highs/Lows, Premium/Discount, EMA 9/21/50/200, RSI/MACD, ADX/ATR, Momentum, MTF, Trend Structure, Breakout/Retest, False Breakout, Reversal, Candle Patterns, Entry Location.
- الأدلة تُجمع في عائلات مستقلة (trend, structure, location, liquidity, momentum, price_action, data)، ولكل عائلة سقف نقاط، والمؤشرات المترابطة (RSI/MACD/Stochastic) لا تُحسب كأدلة منفصلة.
- `trend_strength` أصبحت ضمن عائلة trend بدل تجاهلها.
- بوابات NO TRADE: تعارض الاتجاه، ADX ضعيف، فريمات متعارضة، سوق عرضي، تمدد سعري، كسر وهمي، قرب من مستوى معاكس، جودة بيانات منخفضة، أو عدم كفاية عائلات مؤيدة.

## 6. المدد

- AUTO: يفحص فريمات السوق الفعلية، ثم يختار مدة من `expiry_by_volatility` لملف السوق، ويعرض سبباً. لا مدة عشوائية.
- MANUAL: لا يعرض إلا مدة يمكن تحليلها فعلاً بفريم مدعوم. لذلك لا يظهر 5s/15s لأسواق المؤشرات، ولا 15m/30m/1h لغير FOREX.
- مدة الصفقة منفصلة تماماً عن فريم الشموع.

## 7. نتائج الاختبارات

- اختبارات المشروع: **129 passed, 3 skipped**.
- اختبارات الجسر: **22 passed**.
- `scripts/verify_build.py`: **ROZLF BUILD CHECK OK**.
- اختبارات ملفات الأسواق: 6 أسواق لكل منها إعداد مستقل، رفض فريم غير مدعوم، اختيار المدة من الملف، خلو OTC من القوائم والماسح وفحص الصحة.

## 8. Backtesting ببيانات حقيقية

بيانات Yahoo Forex حقيقية، 1500 شمعة 5m لكل زوج، `step_bars=3`، `latency_bars=1` (لا lookahead)، والمدة 300s/900s.

| الأصل | Expiry | قرارات | NO TRADE | صفقات | WIN | LOSS | DRAW | Win Rate | PF | Expectancy | Max DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR/USD | 300s | 450 | 358 | 92 | 30 | 32 | 30 | 48.39% | 0.94 | -0.0217 | 11 |
| EUR/USD | 900s | 450 | 358 | 92 | 38 | 37 | 17 | 50.67% | 1.03 | 0.0109 | 9 |
| GBP/USD | 300s | 450 | 392 | 58 | 29 | 28 | 1 | 50.88% | 1.04 | 0.0172 | 5 |
| GBP/USD | 900s | 450 | 392 | 58 | 30 | 28 | 0 | 51.72% | 1.07 | 0.0345 | 6 |
| USD/JPY | 300s | 450 | 388 | 62 | 33 | 28 | 1 | 54.10% | 1.18 | 0.0806 | 8 |
| USD/JPY | 900s | 450 | 388 | 62 | 34 | 27 | 1 | 55.74% | 1.26 | 0.1129 | 8 |
| AUD/USD | 300s | 450 | 402 | 48 | 20 | 22 | 6 | 47.62% | 0.91 | -0.0417 | 7 |
| AUD/USD | 900s | 450 | 402 | 48 | 23 | 20 | 5 | 53.49% | 1.15 | 0.0625 | 6 |
| USD/CAD | 300s | 450 | 373 | 77 | 38 | 35 | 4 | 52.05% | 1.09 | 0.0390 | 7 |
| USD/CAD | 900s | 450 | 373 | 77 | 37 | 38 | 2 | 49.33% | 0.97 | -0.0130 | 14 |

## 9. الاختبار المستقل (Out-of-sample)

تقسيم walk-forward مع holdout خارجي لكل تشغيل:

| الأصل | Expiry | OOS trades | OOS Win Rate | OOS PF |
|---|---|---|---|---|
| EUR/USD | 300s | 28 | 39.13% | 0.64 |
| EUR/USD | 900s | 28 | 45.83% | 0.85 |
| GBP/USD | 300s | 18 | 50.00% | 1.00 |
| GBP/USD | 900s | 18 | 44.44% | 0.80 |
| USD/JPY | 300s | 19 | 47.37% | 0.90 |
| USD/JPY | 900s | 19 | 63.16% | 1.71 |
| AUD/USD | 300s | 15 | 58.33% | 1.40 |
| AUD/USD | 900s | 15 | 60.00% | 1.50 |
| USD/CAD | 300s | 24 | 52.17% | 1.09 |
| USD/CAD | 900s | 24 | 56.52% | 1.30 |

EUR/USD 300s أضعف من العينة التطويرية، ولا يوجد دليل كافٍ لاعتباره ربحياً على المدى الطويل. النتائج لا تدعم ادعاء دقة ثابتة، ولا تُستخدم كاحتمال ربح.

## 10. الأسواق التي لم تُختبر ببيانات حقيقية كافية

- SMARTY / FOOTBALL / LUXURY / AI / CRICKET: لا يوجد `EO_BRIDGE_KEY` في بيئة مساحة العمل، والجسر يرفض طلبات الشموع بـ`UNAUTHORIZED`. فحص `/health` العام يُظهر الجسر متصلاً و`151` أصلاً، لكنه لا يثبت شموع السوق المطلوبة بعد deployment.
- لذلك لم أنشئ أرقام backtest لهذه الأسواق. أي رقم كان سيكون تخميناً أو بيانات سوق آخر.
- FOREX تم اختباره على Yahoo بأسعار حقيقية. Gold لم يُعد ضمن نطاق هذه المهمة.

## 11. Telegram Live وRailway

- لم يوجد `TELEGRAM_BOT_TOKEN` في مساحة العمل، لذلك **لم أختبر Telegram Live** في هذه المهمة.
- لم يوجد Railway CLI أو token، لذلك لا أستطيع التحقق من deployment أو logs بنفسي.
- ما تم إثباته: الاختبارات المحلية، فحص البناء، فحص `/health` العام للجسر.
- ما لم يُثبت: وصول شموع جديدة من الجسر بعد النشر، ظهور القائمة الجديدة في Telegram، نجاح Railway deployment.

## 12. المشاكل المتبقية

1. يلزم تشغيل البوت على Railway وفتح القائمة مرة واحدة للتحقق النهائي من Telegram.
2. يلزم اختبار SMARTY/المؤشرات ببيانات الجسر الحقيقية بعد النشر؛ قبل ذلك تظهر `DATA UNAVAILABLE` عند غياب البيانات.
3. EUR/USD على 300s أظهر ضعفاً خارج العينة؛ لا يُرفع الحد أو يُعاد ضبطه للتجميل. أي تحسين لاحق يجب أن يُختبر على بيانات جديدة.
4. عدد صفقات بعض الأسواق أقل من 100 بسبب عدد الشموع المتاح؛ لم تُختلق صفقات للوصول إلى 100.
