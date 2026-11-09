"""Central message formatting (HTML). All user-facing text lives here."""
from __future__ import annotations

from datetime import datetime, timezone

from config import Settings
from database.repository import SignalRecord
from engines.signals.generator import DURATION_LABELS
from engines.technical.analyzer import AnalysisResult
from providers.catalog import Asset, Market, TIMEFRAMES

DISCLAIMER = "⚠️ تحليل تعليمي فقط — لا ينفّذ ROZLF AI أي صفقات."
DATA_UNAVAILABLE = "DATA UNAVAILABLE"


def format_price(value: float | None, market: str | None = None) -> str:
    if value is None:
        return "N/A"
    if market in ("GOLD",) or (abs(value) > 500):
        return f"{value:,.2f}"
    if abs(value) >= 20:
        return f"{value:,.3f}"
    return f"{value:.5f}"


def duration_label(seconds: int) -> str:
    return DURATION_LABELS.get(seconds, f"{seconds} SEC")


def local_time(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def market_label(market: str) -> str:
    labels = {
        Market.FOREX.value: "FOREX",
        Market.GOLD.value: "GOLD",
        Market.OTC.value: "OTC",
        Market.SMARTY.value: "SMARTY",
    }
    return labels.get(market, market)


def welcome_text(settings: Settings) -> str:
    ai_status = "MISTRAL AI ONLINE" if settings.mistral_api_key else "MISTRAL AI NOT CONFIGURED"
    return (
        "<b>ROZLF AI</b>\n"
        "<i>ADVANCED TRADING INTELLIGENCE</i>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "مرحباً بك في نظام <b>ROZLF AI</b>.\n"
        "تحليل فني + Smart Money Concepts + إشارات موثّقة.\n\n"
        "<b>الأقسام الرئيسية:</b>\n"
        "🧠 SMARTY MARKET\n"
        "🌐 OTC MARKET\n"
        "💱 FOREX MARKET\n"
        "🥇 GOLD ANALYSIS\n"
        "🛰 AUTO SCANNER\n"
        "🖼 AI IMAGE ANALYSIS\n"
        "📡 LIVE SIGNALS\n"
        "🗂 SIGNAL HISTORY\n"
        "📊 PERFORMANCE STATISTICS\n"
        "⚙️ SETTINGS\n\n"
        f"AI STATUS: <b>{ai_status}</b>\n"
        f"MIN CONFIDENCE: <b>{settings.min_confidence:.0f}%</b>\n\n"
        f"<i>{DISCLAIMER}</i>"
    )


def signal_text(signal: SignalRecord, ai_note: str | None = None) -> str:
    lines = [
        "<b>ROZLF AI SIGNAL</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"ASSET: <b>{signal.asset_display}</b> ({market_label(signal.market)})",
        f"MARKET: {market_label(signal.market)}",
        f"DIRECTION: <b>{signal.direction}</b>",
        f"EXPIRATION: {duration_label(signal.expiry_seconds)}",
        f"ENTRY: {format_price(signal.entry_price, signal.market)}",
        f"TIMEFRAME: {signal.timeframe}",
        f"CONFIDENCE: <b>{signal.confidence:.0f}%</b>",
        f"DATA SOURCE: {signal.source}",
        f"TIME: {local_time(signal.created_at)}",
    ]
    if signal.reasons:
        lines.append("")
        lines.append("<b>TECHNICAL REASONS:</b>")
        lines.extend(f"• {reason}" for reason in signal.reasons)
    if signal.warnings:
        lines.append("")
        lines.append("<b>RISK NOTES:</b>")
        lines.extend(f"• {warning}" for warning in signal.warnings)
    if ai_note:
        lines.append("")
        lines.append("<b>AI SUMMARY:</b>")
        lines.append(ai_note)
    lines.append("")
    lines.append(f"STATUS: <b>{signal.status}</b>")
    lines.append(f"<i>{DISCLAIMER}</i>")
    return "\n".join(lines)


def analysis_text(result: AnalysisResult) -> str:
    indicators = result.indicators
    smc = result.smc
    support = ", ".join(format_price(level, result.market) for level in indicators.get("support", [])) or "—"
    resistance = ", ".join(format_price(level, result.market) for level in indicators.get("resistance", [])) or "—"
    fvgs = smc.get("fair_value_gaps", [])
    blocks = smc.get("order_blocks", [])
    sweeps = smc.get("sweeps", [])
    pd_zone = smc.get("premium_discount", {}).get("zone", "UNKNOWN")
    lines = [
        f"<b>ROZLF AI ANALYSIS — {result.asset_display}</b>",
        f"MARKET: {market_label(result.market)} | TF: {result.timeframe}",
        "━━━━━━━━━━━━━━━━━━",
        f"PRICE: <b>{format_price(result.price, result.market)}</b>",
        f"DECISION: <b>{result.direction}</b>",
        f"CONFIDENCE: <b>{result.confidence:.0f}%</b> (UP {result.score_up:.0f} / DOWN {result.score_down:.0f})",
        f"TREND: {indicators.get('trend')} | MOMENTUM: {indicators.get('momentum')}",
        f"VOLATILITY: {indicators.get('volatility')} (ATR {indicators.get('atr_pct')}%)",
        "",
        "<b>INDICATORS</b>",
        f"RSI: {indicators.get('rsi')} | MACD HIST: {indicators.get('macd_hist')}",
        f"EMA9: {format_price(indicators.get('ema9'), result.market)} | EMA21: {format_price(indicators.get('ema21'), result.market)}",
        f"EMA50: {format_price(indicators.get('ema50'), result.market)}",
        f"SUPPORT: {support}",
        f"RESISTANCE: {resistance}",
        "",
        "<b>SMART MONEY CONCEPTS</b>",
        f"STRUCTURE: {smc.get('trend')} | ZONE: {pd_zone}",
        f"FVG ACTIVE: {len(fvgs)} | ORDER BLOCKS: {len(blocks)} | SWEEPS: {len(sweeps)}",
    ]
    last_event = smc.get("last_event")
    if last_event:
        lines.append(
            f"LAST EVENT: {last_event['event']} ({last_event['direction']}) @ {format_price(last_event['price'], result.market)}"
        )
    for gap in fvgs[:2]:
        lines.append(
            f"FVG {gap['direction'].upper()}: {format_price(gap['bottom'], result.market)} — {format_price(gap['top'], result.market)}"
        )
    if result.reasons:
        lines.append("")
        lines.append("<b>REASONS</b>")
        lines.extend(f"• {reason}" for reason in result.reasons)
    if result.warnings:
        lines.append("")
        lines.append("<b>WARNINGS</b>")
        lines.extend(f"• {warning}" for warning in result.warnings)
    lines.append("")
    lines.append(f"<i>{DISCLAIMER}</i>")
    return "\n".join(lines)


def history_text(records: list[SignalRecord]) -> str:
    if not records:
        return "📭 لا توجد إشارات مسجلة بعد."
    icons = {"WIN": "✅", "LOSS": "❌", "DRAW": "➖", "ACTIVE": "⏳", "UNVERIFIED": "❔"}
    lines = ["<b>🗂 SIGNAL HISTORY</b>", "━━━━━━━━━━━━━━━━━━"]
    for record in records:
        icon = icons.get(record.status, "•")
        lines.append(
            f"{icon} #{record.id} {record.asset_display} {record.direction} "
            f"{duration_label(record.expiry_seconds)} — {record.confidence:.0f}% — {record.status}"
        )
        close = f" → {format_price(record.close_price, record.market)}" if record.close_price else ""
        lines.append(
            f"   entry {format_price(record.entry_price, record.market)}{close} · {local_time(record.created_at)}"
        )
    return "\n".join(lines)


def stats_text(stats: dict) -> str:
    accuracy = stats.get("accuracy")
    accuracy_text = f"{accuracy}%" if accuracy is not None else "N/A (لا نتائج متحققة بعد)"
    return (
        "<b>📊 PERFORMANCE STATISTICS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"TOTAL SIGNALS: {stats.get('total', 0)}\n"
        f"ACTIVE: {stats.get('active', 0)}\n"
        f"VERIFIED: {stats.get('verified', 0)}\n"
        f"WINS: {stats.get('wins', 0)} | LOSSES: {stats.get('losses', 0)} | DRAWS: {stats.get('draws', 0)}\n"
        f"UNVERIFIED: {stats.get('unverified', 0)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"ACCURACY (verified only): <b>{accuracy_text}</b>\n"
        f"AVG CONFIDENCE: {stats.get('avg_confidence') or '—'}\n"
        f"BEST ASSET: {stats.get('best_asset') or '—'}\n\n"
        "<i>الإحصائيات تعتمد فقط على الإشارات التي تم التحقق من سعر إغلاقها.</i>"
    )


def verification_text(record: SignalRecord) -> str:
    icons = {"WIN": "✅ WIN", "LOSS": "❌ LOSS", "DRAW": "➖ DRAW", "UNVERIFIED": "❔ UNVERIFIED"}
    return (
        f"<b>ROZLF AI — SIGNAL #{record.id} CLOSED</b>\n"
        f"ASSET: {record.asset_display} ({market_label(record.market)})\n"
        f"DIRECTION: {record.direction} | EXPIRY: {duration_label(record.expiry_seconds)}\n"
        f"ENTRY: {format_price(record.entry_price, record.market)} → "
        f"CLOSE: {format_price(record.close_price, record.market)}\n"
        f"RESULT: <b>{icons.get(record.status, record.status)}</b>\n"
        f"VERIFIED VIA: {record.verification_source or '—'}"
    )


def status_text(settings: Settings, statuses: list[dict], health: dict, ai_health: dict) -> str:
    lines = ["<b>ROZLF AI — SYSTEM STATUS</b>", "━━━━━━━━━━━━━━━━━━"]
    lines.append("<b>PROVIDERS</b>")
    for status in statuses:
        state = "🟢 CONFIGURED" if status["configured"] else "⚪ NOT CONFIGURED"
        role = "candles" if status["can_serve_candles"] else "quotes"
        lines.append(f"{status['name']}: {state} ({role})")
        if status.get("detail"):
            lines.append(f"   · {status['detail']}")
    lines.append("")
    lines.append("<b>MARKET COVERAGE (LIVE PROBE)</b>")
    for market in (Market.FOREX, Market.GOLD, Market.OTC, Market.SMARTY):
        entry = health.get(market.value)
        if entry is None:
            lines.append(f"{market_label(market.value)}: ⚪ NOT PROBED")
            continue
        if entry.ok:
            stamp = local_time(entry.last_time)
            lines.append(f"{market_label(market.value)}: 🟢 LIVE — {entry.source}")
            lines.append(f"   · {entry.asset} · last candle {stamp}")
        else:
            lines.append(f"{market_label(market.value)}: 🔴 UNAVAILABLE")
            lines.append(f"   · {entry.error}")
            if entry.detail:
                lines.append(f"   · {entry.detail[:160]}")
    lines.append("")
    ai_state = "🟢 READY" if ai_health.get("configured") else "⚪ NOT CONFIGURED"
    lines.append(f"MISTRAL AI: {ai_state}")
    if ai_health.get("model"):
        lines.append(f"TEXT MODEL: {ai_health['model']}")
    if ai_health.get("vision_model"):
        lines.append(f"VISION MODEL: {ai_health['vision_model']}")
    if ai_health.get("last_error"):
        lines.append(f"LAST AI ERROR: {ai_health['last_error']}")
    lines.append("")
    lines.append(f"MIN CONFIDENCE: {settings.min_confidence:.0f}%")
    lines.append(f"SCAN INTERVAL: {settings.scan_interval}s")
    return "\n".join(lines)


def unavailable_text(title: str, message: str, detail: str | None = None) -> str:
    lines = [f"<b>{title}</b>", "━━━━━━━━━━━━━━━━━━", f"<b>{DATA_UNAVAILABLE}</b>", message]
    if detail:
        lines.append(f"DETAIL: {detail}")
    lines.append("")
    lines.append("لن يتم إصدار أي إشارة من بيانات ناقصة أو غير موثوقة.")
    return "\n".join(lines)


def smarty_card_text(asset: Asset, source_state: str, detail: str | None = None) -> str:
    lines = [
        "<b>🧠 SMARTY MARKET</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"ASSET: <b>{asset.display}</b>",
        f"MARKET: SMARTY (ExpertOption)",
        f"EO ASSET ID: {asset.bridge_id or 'N/A'}",
        f"DATA SOURCE: {source_state}",
    ]
    if detail:
        lines.append(f"STATUS: {detail}")
    lines.append("")
    lines.append("اختر مدة الصفقة لتحليل SMARTY وإصدار الإشارة:")
    lines.append("<i>مدة الصفقة مستقلة عن فريم الشموع المستخدم في التحليل.</i>")
    return "\n".join(lines)


def smarty_result_text(result: AnalysisResult, record: SignalRecord | None) -> str:
    lines = [
        "<b>ROZLF AI — SMARTY ANALYSIS</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"ASSET: <b>{result.asset_display}</b>",
        f"MARKET: SMARTY",
        f"DIRECTION: <b>{result.direction}</b>",
        f"CONFIDENCE: <b>{result.confidence:.0f}%</b>",
        f"ENTRY: {format_price(result.price, result.market)}",
        f"SOURCE: {result.source}",
    ]
    ind = result.indicators or {}
    if ind:
        lines.append("")
        lines.append("<b>INDICATORS</b>")
        rsi = ind.get("rsi")
        macd = ind.get("macd_hist")
        if isinstance(rsi, (int, float)):
            lines.append(f"RSI: {rsi:.1f}")
        if isinstance(macd, (int, float)):
            lines.append(f"MACD HIST: {macd:+.6f}")
        lines.append(
            f"TREND: {ind.get('trend', '—')} · MOMENTUM: {ind.get('momentum', '—')}"
            f" · VOLATILITY: {ind.get('volatility', '—')}"
        )
        support = ind.get("support") or []
        resistance = ind.get("resistance") or []
        if support:
            lines.append(f"SUPPORT: {format_price(support[0], result.market)}")
        if resistance:
            lines.append(f"RESISTANCE: {format_price(resistance[0], result.market)}")
    if record is not None:
        lines.append("")
        lines.append(f"ENTRY TIME: {local_time(record.created_at)}")
        lines.append(f"TRADE DURATION: {duration_label(record.expiry_seconds)}")
        lines.append(f"EXPIRY: {local_time(record.expires_at)}")
        lines.append(f"SIGNAL ID: #{record.id}")
    elif result.direction == "NO TRADE":
        lines.append("")
        lines.append(
            f"SUGGESTED DURATION: {duration_label(result.suggested_expiry_seconds)} "
            f"(only if a setup appears)"
        )
    if result.reasons:
        lines.append("")
        lines.append("<b>TECHNICAL REASONS</b>")
        lines.extend(f"• {reason}" for reason in result.reasons)
    if result.warnings:
        lines.append("")
        lines.extend(f"⚠️ {warning}" for warning in result.warnings)
    lines.append("")
    lines.append(f"STATUS: <b>{'ACTIVE' if record is not None else 'NO TRADE'}</b>")
    lines.append(f"<i>{DISCLAIMER}</i>")
    return "\n".join(lines)


def markets_text(market: str, assets: list[Asset], tfs: list[str]) -> str:
    title = {
        Market.FOREX.value: "💱 FOREX MARKET",
        Market.GOLD.value: "🥇 GOLD ANALYSIS",
        Market.OTC.value: "🌐 OTC MARKET",
        Market.SMARTY.value: "🧠 SMARTY MARKET",
    }.get(market, market)
    lines = [f"<b>{title}</b>", "━━━━━━━━━━━━━━━━━━"]
    if not assets:
        lines.append("لا توجد أصول معرفة لهذا السوق.")
        return "\n".join(lines)
    lines.extend(f"• {asset.display}" for asset in assets)
    lines.append("")
    lines.append(f"FRAMES: {', '.join(tfs)}")
    return "\n".join(lines)


def timeframes_line() -> str:
    frames = ", ".join(TIMEFRAMES[code].label for code in ("1min", "5min", "15min", "30min", "1h"))
    return f"AVAILABLE FRAMES: {frames}"
