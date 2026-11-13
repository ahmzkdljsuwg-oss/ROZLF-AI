# ROZLF MT5 Bridge (read-only)

جسر HTTP صغير يقرأ بيانات MT5 الحقيقية من Terminal مسجل الدخول، ويعرضها لبوت ROZLF.

> Railway لا يستطيع تشغيل منصة MT5. شغّل هذا الجسر على Windows PC أو Windows VPS
> يحتوي MetaTrader 5 وبيانات الوسيط. الجسر **لا ينفذ أي صفقة**.

## 1. المتطلبات

- Windows 10/11 أو Windows Server
- MetaTrader 5 مثبت ومسجل الدخول إلى حساب الوسيط (Demo أو Live)
- Python 3.10+ (64-bit)
- منفذ متاح، ويفضل عدم تعريضه للإنترنت مباشرة بدون HTTPS/Tunnel

## 2. التثبيت

```powershell
cd mt5_bridge
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. الإعداد

انسخ `.env.example` إلى `.env` واضبط:

| المتغير | الوصف |
|---|---|
| `MT5_BRIDGE_KEY` | مفتاح عشوائي طويل؛ نفس القيمة في Railway |
| `MT5_BRIDGE_PORT` | المنفذ الافتراضي 8090 |
| `MT5_TERMINAL_PATH` | مسار `terminal64.exe` (اختياري) |
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | اختياري إذا كان Terminal مسجل الدخول |
| `MT5_MAX_AGE_SECONDS` | أقصى عمر للتيك (افتراضي 180 ثانية) |

استخدم مفتاحاً عشوائياً:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 4. التشغيل

```powershell
python -m mt5_bridge.app
```

أو باستخدام `run.ps1`. اترك Terminal مفتوحاً ومتصلأً.

اختبار سريع:

```powershell
curl.exe -H "X-API-Key: YOUR_KEY" "http://127.0.0.1:8090/health"
curl.exe -H "X-API-Key: YOUR_KEY" "http://127.0.0.1:8090/symbols"
curl.exe -H "X-API-Key: YOUR_KEY" "http://127.0.0.1:8090/candles?symbol=AUDCAD&timeframe=5min&limit=320"
```

`/health` متاح بدون مفتاح ويعيد فقط حالة الاتصال. بقية المسارات تتطلب المفتاح.

## 5. توصيل Railway

1. اجعل الجسر قابلاً للوصول من Railway عبر HTTPS موثوق (Cloudflare Tunnel أو
   Tailscale Funnel أو Reverse Proxy مع TLS). لا تفتح منفذاً خاماً على الإنترنت.
2. في خدمة البوت على Railway أضف:
   - `MT5_BRIDGE_URL=https://your-bridge-host`
   - `MT5_BRIDGE_KEY=...` (نفس المفتاح)
3. أعد نشر البوت، ثم من Telegram: **📊 MT5 ANALYSIS**.

## 6. المسارات

| المسار | الوظيفة |
|---|---|
| `GET /health` | حالة Terminal/الحساب |
| `GET /symbols` | أزواج الفوركس المتاحة فعلاً |
| `GET /candles?symbol=AUDCAD&timeframe=1min&limit=320` | شموع OHLC |
| `GET /quote?symbol=AUDCAD` | Bid/Ask وآخر تحديث |

إذا كانت الشموع قديمة أو Terminal غير متصل يعيد الجسر `503` ولا يرسل أسعاراً قديمة.
