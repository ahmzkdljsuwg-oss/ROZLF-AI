"""Analysis engine: combines indicators and SMC into UP / DOWN / NO TRADE."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..validation import ValidationReport
from . import smc
from .indicators import snapshot

UP = "UP"
DOWN = "DOWN"
NO_TRADE = "NO TRADE"


@dataclass
class SignalScore:
    direction: str
    score: int
    bull: float
    bear: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    rr: float | None = None
    snapshot: dict = field(default_factory=dict)
    smc: dict = field(default_factory=dict)
    timeframe: int = 300

    def as_dict(self) -> dict:
        return {
            "direction": self.direction,
            "score": self.score,
            "bull": round(self.bull, 2),
            "bear": round(self.bear, 2),
            "reasons": self.reasons,
            "warnings": self.warnings,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "rr": self.rr,
            "timeframe": self.timeframe,
        }


def analyze(
    candles,
    timeframe: int,
    *,
    min_score: int = 62,
    validation: ValidationReport | None = None,
    spread: float | None = None,
) -> SignalScore:
    snap = snapshot(candles)
    if not snap.get("ok"):
        return SignalScore(NO_TRADE, 0, 0, 0, warnings=[snap.get("reason", "بيانات غير كافية.")], timeframe=timeframe)

    structure = smc.analyze(candles)
    bull = 0.0
    bear = 0.0
    reasons: list[str] = []
    warnings: list[str] = []

    price = snap["price"]
    atr_val = snap["atr"] or 0.0

    # --- trend via EMAs (weight 18) -------------------------------------
    e9, e21, e50, e200 = snap["ema9"], snap["ema21"], snap["ema50"], snap["ema200"]
    if e9 and e21 and e50:
        if price > e50 and e9 > e21:
            bull += 12
            reasons.append("السعر فوق EMA50 وEMA9 فوق EMA21 (اتجاه صاعد).")
        elif price < e50 and e9 < e21:
            bear += 12
            reasons.append("السعر تحت EMA50 وEMA9 تحت EMA21 (اتجاه هابط).")
        else:
            warnings.append("ترتيب المتوسطات غير واضح.")
    if e200:
        if price > e200:
            bull += 6
            reasons.append("السعر فوق EMA200 (سياق صاعد).")
        else:
            bear += 6
            reasons.append("السعر تحت EMA200 (سياق هابط).")

    # --- MACD (weight 16) ----------------------------------------------
    hist, prev_hist = snap["macd_hist"], snap["macd_hist_prev"]
    if hist is not None:
        if hist > 0:
            bull += 8
            reasons.append("MACD histogram موجب.")
        elif hist < 0:
            bear += 8
            reasons.append("MACD histogram سالب.")
        if prev_hist is not None:
            if prev_hist <= 0 < hist:
                bull += 8
                reasons.append("تقاطع MACD صاعد.")
            elif prev_hist >= 0 > hist:
                bear += 8
                reasons.append("تقاطع MACD هابط.")

    # --- RSI (weight 10) -----------------------------------------------
    rsi_val = snap["rsi"]
    if rsi_val is not None:
        if rsi_val < 30:
            bull += 8
            reasons.append(f"RSI في منطقة التشبع البيعي ({rsi_val:.1f}).")
        elif rsi_val > 70:
            bear += 8
            reasons.append(f"RSI في منطقة التشبع الشرائي ({rsi_val:.1f}).")
        elif 50 < rsi_val <= 70:
            bull += 4
            reasons.append(f"RSI فوق 50 ({rsi_val:.1f}) يدعم الصعود.")
        elif 30 <= rsi_val < 50:
            bear += 4
            reasons.append(f"RSI تحت 50 ({rsi_val:.1f}) يدعم الهبوط.")

    # --- Bollinger (weight 10) -----------------------------------------
    if snap["bb_lower"] and snap["bb_upper"]:
        if price <= snap["bb_lower"]:
            bull += 7
            reasons.append("السعر عند حد بولينجر السفلي.")
        elif price >= snap["bb_upper"]:
            bear += 7
            reasons.append("السعر عند حد بولينجر العلوي.")
        width = snap["bb_width"] or 0
        if width and width < 0.0015:
            warnings.append("عرض بولينجر ضيق جداً: سوق عرضي.")

    # --- Stochastic (weight 6) -----------------------------------------
    k, d = snap["stoch_k"], snap["stoch_d"]
    if k is not None and d is not None:
        if k < 20 and k > d:
            bull += 6
            reasons.append("Stochastic خرج من التشبع البيعي.")
        elif k > 80 and k < d:
            bear += 6
            reasons.append("Stochastic خرج من التشبع الشرائي.")

    # --- SMC structure (weight 20) -------------------------------------
    s = structure.get("structure", {}) if structure.get("ok") else {}
    if s.get("trend") == "BULLISH":
        bull += 8
        reasons.append("هيكل السوق صاعد (HH/HL).")
    elif s.get("trend") == "BEARISH":
        bear += 8
        reasons.append("هيكل السوق هابط (LH/LL).")
    if s.get("bos") == "BULLISH":
        bull += 7
        reasons.append("BOS صاعد: اختراق قمة سابقة.")
    elif s.get("bos") == "BEARISH":
        bear += 7
        reasons.append("BOS هابط: كسر قاع سابق.")
    if s.get("choch") == "BULLISH":
        bull += 7
        reasons.append("CHoCH صاعد: تغيّر هيكل السوق.")
    elif s.get("choch") == "BEARISH":
        bear += 7
        reasons.append("CHoCH هابط: تغيّر هيكل السوق.")

    # --- FVG / order blocks / sweeps (weight 12) -----------------------
    for gap in structure.get("fvg", []):
        near = _near(price, gap["from"], gap["to"], atr_val)
        if not near:
            continue
        if gap["kind"] == "BULLISH":
            bull += 6
            reasons.append(f"FVG صاعد غير مغلق {gap['from']}–{gap['to']}.")
        else:
            bear += 6
            reasons.append(f"FVG هابط غير مغلق {gap['from']}–{gap['to']}.")
        break
    for block in structure.get("order_blocks", []):
        if _near(price, block["from"], block["to"], atr_val):
            if block["kind"] == "BULLISH":
                bull += 5
                reasons.append("السعر عند Order Block شرائي.")
            else:
                bear += 5
                reasons.append("السعر عند Order Block بيعي.")
            break
    for sweep in structure.get("sweeps", [])[-1:]:
        if sweep["kind"] == "BULLISH":
            bull += 6
            reasons.append(f"Liquidity Sweep أسفل {sweep['level']} ثم إغلاق أعلى.")
        else:
            bear += 6
            reasons.append(f"Liquidity Sweep أعلى {sweep['level']} ثم إغلاق أدنى.")

    # --- premium/discount filter --------------------------------------
    if s.get("zone") == "PREMIUM":
        bear += 3
        warnings.append("السعر في منطقة Premium (أفضل للبيع).")
    elif s.get("zone") == "DISCOUNT":
        bull += 3
        warnings.append("السعر في منطقة Discount (أفضل للشراء).")

    # --- volatility / spread guards ------------------------------------
    if atr_val <= 0:
        warnings.append("ATR غير متاح: تقلّب غير مقروء.")
    elif snap["atr_pct"] and snap["atr_pct"] < 0.01:
        warnings.append("تقلّب منخفض جداً (ATR%).")
    if spread is not None and atr_val:
        if spread > atr_val * 0.35:
            warnings.append("السبريد مرتفع مقابل ATR.")
    if validation and validation.warnings:
        warnings.extend(validation.warnings)

    total = bull + bear
    score = 50 if total == 0 else round(50 + 50 * (bull - bear) / total)
    score = max(0, min(100, score))

    if bull > bear:
        direction = UP
    elif bear > bull:
        direction = DOWN
    else:
        direction = NO_TRADE

    adx_val = snap["adx"] or 0
    if direction != NO_TRADE and adx_val and adx_val < 18:
        warnings.append(f"ADX منخفض ({adx_val:.1f}): سوق عرضي.")
    if direction != NO_TRADE and abs(bull - bear) < 9:
        warnings.append("المؤشرات متعارضة: أفضلية ضعيفة.")
        direction = NO_TRADE

    if direction != NO_TRADE and score < min_score:
        warnings.append(f"الدرجة {score} أقل من الحد المطلوب {min_score}.")
        direction = NO_TRADE

    if direction == NO_TRADE:
        return SignalScore(
            NO_TRADE,
            score,
            bull,
            bear,
            reasons,
            warnings,
            entry=round(price, 6),
            snapshot=snap,
            smc=structure,
            timeframe=timeframe,
        )

    entry = price
    risk = max(atr_val * 1.5, price * 0.0004)
    reward = max(atr_val * 2.6, price * 0.0007)
    if direction == UP:
        stop, target = entry - risk, entry + reward
    else:
        stop, target = entry + risk, entry + reward
    rr = round(abs(target - entry) / abs(entry - stop), 2) if stop != entry else None

    return SignalScore(
        direction,
        score,
        bull,
        bear,
        reasons,
        warnings,
        entry=round(entry, 6),
        stop=round(stop, 6),
        target=round(target, 6),
        rr=rr,
        snapshot=snap,
        smc=structure,
        timeframe=timeframe,
    )


def _near(price: float, low: float, high: float, atr_val: float) -> bool:
    pad = max(atr_val * 0.6, price * 0.0002)
    return low - pad <= price <= high + pad
