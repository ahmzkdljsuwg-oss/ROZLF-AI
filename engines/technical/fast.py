"""Lightweight closed-candle technical read. No calibrated win percentage."""
from datetime import timedelta
from statistics import mean

from engines.markets import profile_for
from engines.technical.candle_reading import valid_candle
from engines.validation import closed_candles
from providers.base import DataUnavailable


def _ema(values, n):
    value = values[0]
    alpha = 2 / (n + 1)
    for close in values[1:]:
        value += alpha * (close - value)
    return value


def analyze_fast(data, now):
    from engines.technical.analyzer import AnalysisResult
    tf = data.timeframe
    if tf.code not in profile_for(data.asset.market).frames:
        raise DataUnavailable("UNSUPPORTED_FRAME", "الإطار غير مدعوم للأصل")
    bars = closed_candles(data.candles, tf, min(now, data.closure_cutoff))
    if len(bars) < 200:
        raise DataUnavailable("INSUFFICIENT_BARS", "نحتاج 200 شمعة مغلقة لحساب EMA200")
    step = timedelta(seconds=tf.seconds)
    last = bars[-1]
    target = last.time + step * 2
    if target <= now or any(y.time - x.time != step for x,y in zip(bars[-16:-1],bars[-15:])):
        raise DataUnavailable("MISSING_RECENT_CANDLE", "الشموع الأخيرة متأخرة أو غير متتابعة")
    candles = bars[-300:]
    if any(not valid_candle(b) for b in candles):
        raise DataUnavailable("INVALID_DATA", "المصدر أعاد أسعاراً غير صالحة")
    close = [b.close for b in candles]
    fast, mid, slow, base = (_ema(close,n) for n in (9,21,50,200))
    ranges = [max(y.high-y.low, abs(y.high-x.close), abs(y.low-x.close))
              for x,y in zip(candles[-31:-1],candles[-30:])]
    atr = mean(ranges[-14:])
    baseline = mean(ranges)
    volatility = "HIGH" if baseline and atr > baseline * 1.6 else "LOW" if baseline and atr < baseline * .75 else "NORMAL"
    trend = ("UP" if fast>mid>slow and last.close>base else
             "DOWN" if fast<mid<slow and last.close<base else "RANGE")
    sign = 1 if trend=="UP" else -1 if trend=="DOWN" else 0
    body, momentum = last.close-last.open, last.close-close[-6]
    score = min(100, 15 + 18 * min(abs(momentum)/max(atr,1e-12),3) +
                15 * min(abs(body)/max(atr,1e-12),2))
    if sign and atr > 0 and volatility != "HIGH" and (
        sign * momentum >= .45*atr and sign * body >= .10*atr and last.high-last.low <= atr*2.8
    ):
        direction = trend
        reasons = ["اتفاق المتوسطات مع الزخم واتجاه الشمعة المغلقة",
                   "قراءة فنية سريعة غير معايرة"]
    else:
        direction = "NO TRADE"
        reasons = ["السوق عرضي أو الزخم والشمعة لا يتفقان مع الاتجاه" if volatility != "HIGH"
                   else "التذبذب الحالي مرتفع مقارنة بحركة السوق الأخيرة"]
    return AnalysisResult(asset_key=data.asset.key,asset_display=data.asset.display,
        market=data.asset.market.value,timeframe=tf.code,direction=direction,confidence=0.0,
        score_up=score if direction=="UP" else 0,score_down=score if direction=="DOWN" else 0,
        price=last.close,source=data.source,generated_at=now,reasons=reasons,
        indicators={"trend":trend,"volatility":volatility,"ema9":fast,"ema21":mid,"ema50":slow,
                    "ema200":base,"atr":atr,"momentum":momentum,"last_candle_at":last.time.isoformat()},
        suggested_expiry_seconds=tf.seconds,trend_summary=trend,evidence_score=score,
        closed_candles=len(bars),target_open_at=target,target_timeframe=tf.code,
        confidence_verified=False,analysis_mode="fast")
