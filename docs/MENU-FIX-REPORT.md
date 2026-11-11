# ROZLF AI — MENU FIX REPORT (M2)

## ما تم إصلاحه
- ضبط اسم زر الإحصائيات ليطابق المطلوب حرفياً: `📊 PERFORMANCE STATISTICS`.
- إضافة إلغاء Webhook قديم عند إقلاع البوت، حتى لا تُوجّه تحديثات Telegram إلى نسخة سابقة.
- إضافة بصمة القائمة الفعلية إلى `/health` (`menu_version` و`menu`).
- إضافة سجل إقلاع: `ROZLF MENU M2 READY: ...`.
- إضافة اختبارات لكل زر سوق تتحقق من فتح السوق ومعرّف الأصل الصحيح.

## القائمة الناتجة من `/start` فعلياً
```
🧠 SMARTY MARKET -> mkt:SMARTY | ⚽ FOOTBALL INDEX -> mkt:FOOTBALL
💎 LUXURY INDEX -> mkt:LUXURY | 🤖 AI INDEX -> mkt:AI
🏏 CRICKET INDEX -> mkt:CRICKET | 💱 FOREX MARKET -> mkt:FOREX
📡 LIVE SIGNALS -> live
📜 SIGNAL HISTORY -> hist | 📊 PERFORMANCE STATISTICS -> stats
⚙️ SETTINGS -> settings | 🖥️ SYSTEM STATUS -> status
```

## معرّفات الأصول التي يفتحها كل زر
| الزر | Callback | الأصل |
|---|---|---|
| SMARTY MARKET | `mkt:SMARTY` | SMRTY #240 |
| FOOTBALL INDEX | `mkt:FOOTBALL` | Football Index #278 |
| LUXURY INDEX | `mkt:LUXURY` | Luxury Index #286 |
| AI INDEX | `mkt:AI` | AI Index #285 |
| CRICKET INDEX | `mkt:CRICKET` | Cricket Index #276 مع احترام `is_active` |
| FOREX MARKET | `mkt:FOREX` | أزواج الفوركس الحقيقية فقط |

## الاختبارات
- `137 passed, 3 skipped`
- اختبار `/start` يطابق نص الأزرار وترتيبها.
- اختبار كل سوق يتحقق من ظهور ID الصحيح ووجود `dur:auto` و`dur:manual`.
- اختبار CRICKET غير النشط: `CRICKET UNAVAILABLE` ولا تظهر أي مدد أو إشارات.
- اختبار FOREX: الأزواج التسعة فقط، و`XAU/USD` غير موجود.
- `ROZLF BUILD CHECK OK`

## قيد التحقق
اختبار Telegram الحي يحتاج صلاحية Bot API أو جلسة Telegram، وليست متاحة داخل مساحة العمل.
الدليل المتاح هنا هو الناتج الفعلي لدالة `/start`، وبصمة القائمة المنشورة في `/health` بعد النشر.
