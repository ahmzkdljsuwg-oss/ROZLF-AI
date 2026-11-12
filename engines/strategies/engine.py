"""ExpertOption-specific trading strategies.

Five strategies tuned for short-expiry binary options (30s – 5m):
  1. EMA Trend Stack      — ترتيب المتوسطات الأسية يدعم الاتجاه
  2. RSI Momentum         — زخم RSI مع منطقة ذروة
  3. Candle Body Pressure — ضغط الشمعة: الجسم يعكس قوة المشترين/البائعين
  4. Market Structure BOS — كسر هيكل السوق (BOS/CHoCH)
  5. MACD Signal Cross    — تقاطع خط MACD مع خط الإشارة
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from engines.markets import MarketProfile
from engines.strategies.models import StrategyReport, StrategySignal
from engines.technical.indicators import macd, rsi
from providers.catalog import Market


def _add(
    signals: list[StrategySignal],
    name: str,
    family: str,
    direction: str,
    score: float,
    reason: str,
    invalidation: str,
) -> None:
    if direction in ("UP", "DOWN"):
        signals.append(
            StrategySignal(name, family, direction, float(score), reason, invalidation)
        )


def multi_timeframe(frame: pd.DataFrame, timeframe_seconds: int) -> dict:
    """تحليل بسيط للاتجاه العام من فريمات متعددة."""
    close = frame["close"]
    if len(close) < 10:
        return {"direction": "MIXED", "aligned": False, "short": "—", "medium": "—", "long": "—"}

    def _dir(fast: int, slow: int) -> str:
        e_fast = close.ewm(span=min(fast, len(close) - 1), adjust=False).mean()
        e_slow = close.ewm(span=min(slow, len(close) - 1), adjust=False).mean()
        return "UP" if e_fast.iloc[-1] > e_slow.iloc[-1] else "DOWN"

    s = _dir(5, 10)
    m = _dir(10, 20)
    l = _dir(20, 40)
    if s == m == l:
        return {"direction": s, "aligned": True, "short": s, "medium": m, "long": l}
    return {"direction": "MIXED", "aligned": False, "short": s, "medium": m, "long": l}


def evaluate_strategies(
    frame: pd.DataFrame,
    ind: dict,
    smc: dict,
    market: Market,
    timeframe_seconds: int,
    now: datetime | None = None,
    profile: MarketProfile | None = None,
) -> StrategyReport:
    now = now or datetime.now(timezone.utc)
    price = ind["price"]
    atr = ind["atr"] or price * 1e-5
    signals: list[StrategySignal] = []
    warnings: list[str] = []
    close = frame["close"]
    mtf = multi_timeframe(frame, timeframe_seconds)

    # ── 1. EMA Trend Stack ───────────────────────────────────────────────────
    # ترتيب المتوسطات الأسية يدعم الاتجاه
    if len(frame) >= 22:
        e9  = close.ewm(span=9,  adjust=False).mean().iloc[-1]
        e21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        e50 = close.ewm(span=min(50, len(frame) - 1), adjust=False).mean().iloc[-1]
        if e9 > e21 > e50 and price > e9:
            _add(
                signals,
                "EMA Trend Stack",
                "trend",
                "UP",
                16,
                "ترتيب المتوسطات الأسية يدعم الاتجاه الصاعد",
                "إغلاق شمعة تحت EMA 9",
            )
        elif e9 < e21 < e50 and price < e9:
            _add(
                signals,
                "EMA Trend Stack",
                "trend",
                "DOWN",
                16,
                "ترتيب المتوسطات الأسية يدعم الاتجاه الهابط",
                "إغلاق شمعة فوق EMA 9",
            )

    # ── 2. RSI Momentum ──────────────────────────────────────────────────────
    # زخم RSI مع منطقة ذروة
    rsi_series = rsi(close)
    if len(rsi_series) >= 2:
        rsi_val  = float(rsi_series.iloc[-1])
        rsi_prev = float(rsi_series.iloc[-2])
        if 50 < rsi_val < 70 and rsi_val > rsi_prev:
            _add(
                signals,
                "RSI Momentum",
                "momentum",
                "UP",
                12,
                f"زخم RSI صاعد ({rsi_val:.0f}) مع استمرار القوة",
                "RSI يتراجع تحت 50",
            )
        elif 30 < rsi_val < 50 and rsi_val < rsi_prev:
            _add(
                signals,
                "RSI Momentum",
                "momentum",
                "DOWN",
                12,
                f"زخم RSI هابط ({rsi_val:.0f}) مع استمرار الضعف",
                "RSI يرتفع فوق 50",
            )
        elif rsi_val <= 30 and rsi_val > rsi_prev:
            _add(
                signals,
                "RSI Reversal",
                "momentum",
                "UP",
                10,
                f"ارتداد RSI من منطقة البيع المفرط ({rsi_val:.0f})",
                "RSI ينخفض من جديد تحت 30",
            )
        elif rsi_val >= 70 and rsi_val < rsi_prev:
            _add(
                signals,
                "RSI Reversal",
                "momentum",
                "DOWN",
                10,
                f"ارتداد RSI من منطقة الشراء المفرط ({rsi_val:.0f})",
                "RSI يرتفع من جديد فوق 70",
            )

    # ── 3. Candle Body Pressure ───────────────────────────────────────────────
    # ضغط الشمعة: الجسم يعكس قوة المشترين/البائعين
    if len(frame) >= 3:
        last  = frame.iloc[-1]
        prev  = frame.iloc[-2]
        body  = abs(float(last["close"]) - float(last["open"]))
        candle_range = float(last["high"]) - float(last["low"])
        if candle_range > 0:
            body_ratio = body / candle_range
            bullish_candle = float(last["close"]) > float(last["open"])
            strong = body_ratio >= 0.6
            if strong and bullish_candle and float(last["close"]) > float(prev["close"]):
                _add(
                    signals,
                    "Candle Body Pressure",
                    "confirmation",
                    "UP",
                    10,
                    "شمعة صاعدة قوية — المشترون يسيطرون على الجلسة",
                    "إغلاق شمعة تالية هابطة",
                )
            elif strong and not bullish_candle and float(last["close"]) < float(prev["close"]):
                _add(
                    signals,
                    "Candle Body Pressure",
                    "confirmation",
                    "DOWN",
                    10,
                    "شمعة هابطة قوية — البائعون يسيطرون على الجلسة",
                    "إغلاق شمعة تالية صاعدة",
                )

    # ── 4. Market Structure BOS/CHoCH ─────────────────────────────────────────
    # كسر هيكل السوق (BOS/CHoCH)
    last_event = smc.get("last_event")
    if last_event and (len(frame) - 1 - last_event["index"]) <= 8:
        bullish = last_event["direction"] == "bullish"
        event_type = last_event["event"]
        score = 14 if event_type == "CHoCH" else 13
        _add(
            signals,
            "Market Structure BOS" if event_type == "BOS" else "Market Structure CHoCH",
            "structure",
            "UP" if bullish else "DOWN",
            score,
            f"كسر هيكل السوق ({event_type}) — {'صاعد' if bullish else 'هابط'}",
            f"إغلاق {'تحت' if bullish else 'فوق'} مستوى {last_event['price']:.6f}",
        )
    elif smc.get("trend") in ("BULLISH", "BEARISH"):
        bullish = smc["trend"] == "BULLISH"
        _add(
            signals,
            "Market Structure Trend",
            "structure",
            "UP" if bullish else "DOWN",
            6,
            f"اتجاه السوق يدعم {'الصعود' if bullish else 'الهبوط'}",
            "كسر الهيكل في الاتجاه المعاكس",
        )

    # ── 5. MACD Signal Cross ──────────────────────────────────────────────────
    # تقاطع خط MACD مع خط الإشارة
    _, sig_line, hist_series = macd(close)
    if len(hist_series) >= 2:
        hist_now  = float(hist_series.iloc[-1])
        hist_prev = float(hist_series.iloc[-2])
        if hist_prev < 0 <= hist_now:
            _add(
                signals,
                "MACD Signal Cross",
                "macd",
                "UP",
                11,
                "تقاطع MACD صاعد — خط MACD يتجاوز خط الإشارة للأعلى",
                "MACD يرجع تحت خط الإشارة",
            )
        elif hist_prev > 0 >= hist_now:
            _add(
                signals,
                "MACD Signal Cross",
                "macd",
                "DOWN",
                11,
                "تقاطع MACD هابط — خط MACD يتجاوز خط الإشارة للأسفل",
                "MACD يرجع فوق خط الإشارة",
            )
        elif hist_now > 0 and hist_now > hist_prev:
            _add(
                signals,
                "MACD Momentum",
                "macd",
                "UP",
                7,
                "زخم MACD إيجابي ومتسارع — المشترون يكتسبون قوة",
                "MACD Histogram يتراجع",
            )
        elif hist_now < 0 and hist_now < hist_prev:
            _add(
                signals,
                "MACD Momentum",
                "macd",
                "DOWN",
                7,
                "زخم MACD سلبي ومتسارع — البائعون يكتسبون قوة",
                "MACD Histogram يرتفع",
            )

    # ── تحذيرات ───────────────────────────────────────────────────────────────
    if ind.get("volatility") == "HIGH":
        warnings.append("تقلب عالٍ — استخدم مدة صفقة أقصر وكن حذراً")
    if mtf.get("direction") == "MIXED":
        warnings.append("الفريمات الزمنية المتعددة متعارضة — ثقة الإشارة منخفضة")

    return StrategyReport(
        signals=signals,
        mtf=mtf,
        session="MARKET",
        context={
            "warnings": warnings,
        },
    )
