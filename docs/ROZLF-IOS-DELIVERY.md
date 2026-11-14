# ROZLF AI — تقرير تسليم تطبيق iPhone

تاريخ التقرير: 2026-11-14

## 1. ما تم بناؤه

| العنصر | الحالة |
|---|---|
| تطبيق iOS أصلي SwiftUI (6 أسواق، توصيات، سجل، إعدادات، AR/EN) | ✅ مبني في CI |
| ملف IPA للجهاز (arm64) | ✅ مبني كـ **Unsigned** |
| الاختبارات الخلفية (377 passed / 3 skipped) | ✅ |
| اختبارات واجهة iOS (2 tests) | ✅ نجحت في CI |
| ربط `/api/app/*` بالمحرك الحقيقي | ✅ يعمل محلياً على بيانات FOREX حقيقية |
| نشر الإصدار الجديد على Railway | ❌ لم يتم: `RAILWAY_TOKEN` غير صالح |
| توقيع IPA وتثبيت على iPhone | ❌ لم يتم: لا شهادة توقيع ولا Provisioning Profile |

## 2. ملف IPA

- الملف: `artifacts/rozlf-ios/ROZLFAI-unsigned.ipa`
- SHA256: `6b3e3eeb702d4a059775b9d555a53c86e501f406c87d606a54397b73446fc497`
- Bundle ID: `ai.rozlf.app`
- الإصدار: `1.0.0` (build 1)
- أدنى iOS: `16.0`
- المعمارية: `arm64` (iphoneos)
- موقّع: **لا** (`_CodeSignature` غير موجود)

هذا الملف **لا يُثبّت مباشرة** على iPhone. يجب توقيعه بشهادة Apple أو عبر ESign باستخدام شهادة/بروفايل تملكهما.

## 3. نتائج الاختبارات

### خلفية (Python)
```
377 passed, 3 skipped in 14.25s
```
تشمل: `/api/app/*`، التوصيات، المدد اليدوية والتحليل حسب الشمعة، الأسواق الستة، الإحصاءات، SMC، Alligator/MA200، Backtest.

### iOS CI
- Workflow: `.github/workflows/ios.yml`
- Run: `43615745299` — **success**
- `test`: نجحت اختباران (رفض HTTP غير المحلي، فتح الواجهة الرئيسية بعنوان خادم مُمرّر).
- `build-ipa`: نجح إنتاج IPA غير موقّع.

### اختبار حقيقي للـ API محلياً
```
GET  /api/app/health              -> 200 engine ONLINE
GET  /api/app/markets             -> 6 أسواق منفصلة، SMARTY/FOOTBALL/LUXURY/AI/CRICKET = UNAVAILABLE بصدق
GET  /api/app/market/FOREX        -> LIVE، 9 أزواج، Twelve Data
GET  /api/app/recommendations     -> توصية USD/JPY UP 75.2% مع تحليل شموع كامل
POST /api/app/analyse             -> asset keys هي USD_JPY_FOREX ... إلخ
```

## 4. اختبارات التسليم العشرة

| # | الاختبار | النتيجة |
|---|---|---|
| 1 | صفحات التطبيق | ✅ اختبار فتح الواجهة الرئيسية في CI |
| 2 | كل الأزرار | ⚠️ لم تُختبر كلها آلياً (تحتاج جهاز/محاكي تفاعلي) |
| 3 | توصيات لكل سوق | ✅ FOREX حقيقي؛ الباقي `UNAVAILABLE` لعدم وجود جسر ExpertOption |
| 4 | «تحليل الوقت حسب الشمعة» | ✅ اختبار خلفي `duration_mode=auto` |
| 5 | المدد اليدوية | ✅ اختبار خلفي `duration_mode=manual` |
| 6 | اتصال التطبيق بـ Railway | ❌ لا يوجد نشر جديد؛ الروابط القديمة لا تحتوي `/api/app` |
| 7 | انقطاع البيانات وعودة الاتصال | ✅ حالة `OFFLINE/UNAVAILABLE` في الخلفية؛ اختبار iOS يرصد حالة الاتصال |
| 8 | تسجيل نتائج الصفقات | ✅ اختبارات الإحصاءات والسجل |
| 9 | اختبار تاريخي للمحرك | ✅ `tests/test_backtest.py` ضمن 377 |
| 10 | عدم ادّعاء ميزة قبل اختبارها | ✅ هذا التقرير يفرّق بين المُختبر وغير المُختبر |

## 5. متطلبات التوقيع

1. Apple Developer account + شهادة توزيع (`.p12` + كلمة مرور).
2. App ID `ai.rozlf.app`.
3. Provisioning Profile (Ad Hoc أو Development) يضم أجهزة الاختبار.
4. توقيع عبر Xcode أو `codesign` + ESign على الجهاز.

لإنتاج IPA موقّع في CI أضف Secrets:
```
IOS_CERTIFICATE_P12_BASE64
IOS_CERTIFICATE_PASSWORD
IOS_PROVISIONING_PROFILE_BASE64
IOS_TEAM_ID
```

## 6. خطوات النشر على Railway (عند توفر `RAILWAY_TOKEN` صالح)

```bash
railway login --token "$RAILWAY_TOKEN"
railway link
railway up --service rozlf-ai
curl https://<service>.up.railway.app/api/app/health
```

يجب ضبط `DATABASE_URL` على PostgreSQL في Railway.

## 7. ما يحتاج تدخلاً من المستخدم

- `RAILWAY_TOKEN` صالح (الحالي يعيد `Unauthorized`).
- شهادة توقيع + Provisioning Profile.
- `EO_BRIDGE_URL` و`EO_BRIDGE_KEY` لبيانات SMARTY/FOOTBALL/LUXURY/AI/CRICKET.
- `MISTRAL_API_KEY` للتحليل النصي (المحرك الفني يعمل بدونه).
- `TWELVE_DATA_API_KEY` لباقي أزواج FOREX وGOLD (EUR/USD وUSD/JPY يعملان بدون مفتاح).
