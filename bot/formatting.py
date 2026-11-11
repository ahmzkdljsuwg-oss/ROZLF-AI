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
        Market.AI.value: "AI INDEX",
        Market.FOOTBALL.value: "FOOTBALL INDEX",
        Market.LUXURY.value: "LUXURY INDEX",
        Market.CRICKET.value: "CRICKET INDEX",
    }
    return labels.get(market, market)


def welcome_text(settings: Settings) -> str:
    ai_status = "🟢 ONLINE" if settings.mistral_api_key else "⚪ NOT CONFIGURED"
    return (
        "🧠 <b>ROZLF AI</b>\n"
        "<i>ADVANCED TRADING INTELLIGENCE</i>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "أهلاً بك في منصة التحليل الذكية.\n"
        "كل سوق بمحرك مستقل · بيانات حقيقية · قرارات مبنية على الأدلة.\n\n"
        "<b>MARKET DESK — الأسواق</b>\n"
        "🧠 SMARTY MARKET\n"
        "⚽ FOOTBALL INDEX\n"
        "💎 LUXURY INDEX\n"
        "🤖 AI INDEX\n"
        "🏏 CRICKET INDEX\n"
        "💱 FOREX MARKET\n\n"
        "<b>INTELLIGENCE — الأدوات</b>\n"
        "📡 LIVE SIGNALS    📜 SIGNAL HISTORY\n"
        "📊 PERFORMANCE STATISTICS\n"
        "⚙️ SETTINGS        🖥️ SYSTEM STATUS\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"AI ENGINE: <b>{ai_status}</b>\n"
        f"MIN CONFIDENCE: <b>{settings.min_confidence:.0f}%</b>\n\n"
        f"<i>{DISCLAIMER}</i>"
    )


def signal_card_text(
    market: str,
    asset_display: str,
    direction: str,
    expiry_seconds: int | None,
    confidence: float | None,
) -> str:
    if direction == "UP":
        signal_line = "🟢 SIGNAL: <b>BUY 🟢</b>"
    elif direction == "DOWN":
        signal_line = "🔴 SIGNAL: <b>SELL 🛑</b>"
    else:
        signal_line = "⚪ SIGNAL: <b>NO TRADE</b>"
    trade_time = duration_label(expiry_seconds) if expiry_seconds and direction in ("UP", "DOWN") else "—"
    conf = f"{confidence:.0f}%" if confidence is not None and direction in ("UP", "DOWN") else "—"
    return (
        f"📊 MARKET: <b>{market_label(market)}</b>\n"
        f"💹 ASSET: <b>{asset_display}</b>\n\n"
        f"{signal_line}\n\n"
        f"⏱️ TRADE TIME: <b>{trade_time}</b>\n\n"
        f"🎯 TRADE CONFIDENCE: <b>{conf}</b>"
    )


def signal_text(signal: SignalRecord, ai_note: str | None = None) -> str:
    return signal_card_text(
        signal.market,
        signal.asset_display,
        signal.direction,
        signal.expiry_seconds,
        signal.confidence,
    )


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
        f"EVIDENCE SCORE: <b>{result.confidence:.0f}%</b> (UP {result.score_up:.0f} / DOWN {result.score_down:.0f})",
        f"TREND: {result.trend_summary} | MOMENTUM: {result.momentum_strength}",
        f"TIMEFRAMES: {result.mtf.get('short')} / {result.mtf.get('medium')} / {result.mtf.get('long')}",
        f"DATA QUALITY: {result.data_confidence.get('level', '—')} ({result.data_confidence.get('score', 0)}%)",
        f"SESSION: {result.session}",
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
        lines.append("<b>CONFIRMED STRATEGIES / REASONS</b>")
        lines.extend(f"• {reason}" for reason in result.reasons)
    if result.opposing_strategies:
        lines.append("")
        lines.append("<b>OPPOSING STRATEGIES</b>")
        lines.extend(f"• {item['name']} — {item['reason']}" for item in result.opposing_strategies[:3])
    if result.cancellation_reason:
        lines.append("")
        lines.append(f"<b>CANCELLED:</b> {result.cancellation_reason}")
    if result.invalidation:
        lines.append("")
        lines.append("<b>INVALIDATION</b>")
        lines.extend(f"• {item}" for item in result.invalidation)
    if result.warnings:
        lines.append("")
        lines.append("<b>WARNINGS</b>")
        lines.extend(f"• {warning}" for warning in result.warnings)
    lines.append("")
    lines.append(f"<i>{DISCLAIMER}</i>")
    return "\n".join(lines)


def trend_summary_text(result: AnalysisResult, source: str) -> str:
    mtf = result.mtf or {}
    labels = {"short": "قصير", "medium": "متوسط", "long": "طويل"}
    lines = [
        "<b>📈 الترند والاستراتيجيات</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"ASSET: <b>{result.asset_display}</b> ({market_label(result.market)})",
        f"TIMEFRAME: {result.timeframe} | PRICE: {format_price(result.price, result.market)}",
        f"OVERALL TREND: <b>{result.trend_summary}</b>",
    ]
    for key, label in labels.items():
        lines.append(f"{label}: {mtf.get(key, '—')}")
    lines.append(f"MOMENTUM: {result.momentum_strength} | SESSION: {result.session}")
    lines.append(f"DATA QUALITY: {result.data_confidence.get('level', '—')} ({result.data_confidence.get('score', 0)}%)")
    lines.append("")
    if result.confirmed_strategies:
        lines.append("<b>استراتيجيات متوافقة</b>")
        for item in result.confirmed_strategies[:6]:
            lines.append(f"✅ {item['name']} — {item['reason']}")
    else:
        lines.append("لا توجد استراتيجيات متوافقة حالياً.")
    if result.opposing_strategies:
        lines.append("")
        lines.append("<b>استراتيجيات معارضة</b>")
        for item in result.opposing_strategies[:3]:
            lines.append(f"⚠️ {item['name']} — {item['reason']}")
    if result.cancellation_reason:
        lines.append("")
        lines.append(f"<b>سبب إلغاء الإشارة:</b> {result.cancellation_reason}")
    lines.append("")
    lines.append(f"SOURCE: {source}")
    lines.append(f"<i>{DISCLAIMER}</i>")
    return "\n".join(lines)


def history_text(records: list[SignalRecord]) -> str:
    if not records:
        return (
            "📜 <b>SIGNAL HISTORY</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📭 لا توجد إشارات مسجلة بعد."
        )
    icons = {"WIN": "✅", "LOSS": "❌", "DRAW": "➖", "ACTIVE": "⏳", "UNVERIFIED": "❔"}
    names = {"WIN": "WIN", "LOSS": "LOSS", "DRAW": "DRAW", "ACTIVE": "PENDING", "UNVERIFIED": "UNVERIFIED"}
    lines = ["📜 <b>SIGNAL HISTORY</b>", "━━━━━━━━━━━━━━━━━━"]
    for record in records:
        icon = icons.get(record.status, "•")
        lines.append(
            f"{icon} <b>#{record.id} · {record.asset_display}</b>\n"
            f"   {market_label(record.market)} · {record.direction} · {duration_label(record.expiry_seconds)}\n"
            f"   {names.get(record.status, record.status)} · CONF {record.confidence:.0f}% · {local_time(record.created_at)}"
        )
        if record.close_price is not None:
            lines.append(
                f"   ENTRY {format_price(record.entry_price, record.market)} → CLOSE {format_price(record.close_price, record.market)}"
            )
        if record.result_reason:
            lines.append(f"   ↳ {record.result_reason[:110]}")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("<i>النتائج القديمة لا تُعاد كتابتها.</i>")
    return "\n".join(lines)


def stats_text(stats: dict) -> str:
    accuracy = stats.get("accuracy")
    accuracy_text = f"{accuracy}%" if accuracy is not None else "N/A"
    profit_factor = stats.get("profit_factor")
    pf_text = f"{profit_factor:.2f}" if profit_factor is not None else "N/A"
    lines = [
        "📊 <b>PERFORMANCE STATISTICS</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"TOTAL SIGNALS: <b>{stats.get('total', 0)}</b>",
        f"CLOSED: {stats.get('verified', 0)} · PENDING: {stats.get('active', 0)} · UNVERIFIED: {stats.get('unverified', 0)}",
        "",
        f"✅ WINS: <b>{stats.get('wins', 0)}</b>",
        f"❌ LOSSES: <b>{stats.get('losses', 0)}</b>",
        f"➖ DRAWS: <b>{stats.get('draws', 0)}</b>",
        "",
        f"WIN RATE (closed): <b>{accuracy_text}</b>",
        f"PROFIT FACTOR (price-based): <b>{pf_text}</b>",
        f"AVG CONFIDENCE: {stats.get('avg_confidence') or '—'}",
        "━━━━━━━━━━━━━━━━━━",
        "<b>BY MARKET</b>",
    ]
    per_market = stats.get("per_market") or {}
    if not per_market:
        lines.append("لا توجد نتائج مغلقة بعد.")
    for market, row in per_market.items():
        rate = f"{row['win_rate']:.1f}%" if row.get("win_rate") is not None else "N/A"
        lines.append(
            f"{market}: W {row['wins']} · L {row['losses']} · D {row['draws']} · WR {rate}"
        )
    lines.append("")
    lines.append("<i>Win Rate يُحسب من النتائج المغلقة فقط، وليس نسبة ربح مضمونة.</i>")
    return "\n".join(lines)


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
        f"\nREASON: {record.result_reason or '—'}"
    )


def status_text(settings: Settings, statuses: list[dict], health: dict, ai_health: dict) -> str:
    lines = ["🖥️ <b>SYSTEM STATUS</b>", "━━━━━━━━━━━━━━━━━━"]
    bot_state = "🟢 CONFIGURED" if getattr(settings, "telegram_bot_token", None) else "🔴 MISSING TOKEN"
    lines.append("<b>CORE</b>")
    lines.append(f"TELEGRAM BOT: {bot_state}")
    lines.append(f"EO BRIDGE: {'🟢 CONFIGURED' if getattr(settings, 'eo_bridge_url', None) else '⚪ NOT CONFIGURED'}")
    lines.append("")
    lines.append("<b>DATA PROVIDERS</b>")
    for status in statuses:
        state = "🟢 READY" if status["configured"] else "⚪ NOT CONFIGURED"
        role = "candles" if status["can_serve_candles"] else "quotes"
        lines.append(f"{status['name']}: {state} ({role})")
    lines.append("")
    lines.append("<b>MARKET COVERAGE (LIVE PROBE)</b>")
    for market in (
        Market.FOREX, Market.SMARTY,
        Market.AI, Market.FOOTBALL, Market.LUXURY, Market.CRICKET,
    ):
        entry = health.get(market.value)
        if entry is None:
            lines.append(f"{market_label(market.value)}: ⚪ NOT PROBED")
            continue
        if entry.ok:
            stamp = local_time(entry.last_time)
            lines.append(f"{market_label(market.value)}: 🟢 LIVE")
            lines.append(f"   · {entry.source} · {entry.asset}")
            lines.append(f"   · last candle {stamp}")
        else:
            lines.append(f"{market_label(market.value)}: 🔴 UNAVAILABLE")
            lines.append(f"   · {entry.error}")
    lines.append("")
    ai_state = "🟢 READY" if ai_health.get("configured") else "⚪ NOT CONFIGURED"
    lines.append(f"MISTRAL AI: {ai_state}")
    if ai_health.get("model"):
        lines.append(f"MODEL: {ai_health['model']}")
    if ai_health.get("last_error"):
        lines.append(f"LAST AI ERROR: {ai_health['last_error']}")
    lines.append("")
    lines.append(f"MIN CONFIDENCE: {settings.min_confidence:.0f}%")
    lines.append(f"SCAN INTERVAL: {settings.scan_interval}s")
    return "\n".join(lines)


def unavailable_text(title: str, message: str, detail: str | None = None) -> str:
    lines = [
        f"🚫 <b>{title}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"<b>{DATA_UNAVAILABLE}</b>",
        message,
    ]
    if detail:
        lines.append(f"DETAIL: {detail}")
    lines.append("")
    lines.append("لن يتم إصدار أي إشارة من بيانات ناقصة أو قديمة أو غير موثوقة.")
    return "\n".join(lines)


def market_page_text(asset: Asset, source_state: str, detail: str | None = None) -> str:
    lines = [
        f"{market_label(asset.market.value)}",
        "━━━━━━━━━━━━━━━━━━",
        f"💹 ASSET: <b>{asset.display}</b>",
        f"🆔 EO ASSET ID: <b>{asset.bridge_id or 'N/A'}</b>",
        f"📡 DATA: <b>{source_state}</b>",
    ]
    if detail:
        lines.append(f"ℹ️ {detail}")
    lines.append("")
    lines.append("<b>TRADE DURATION</b>")
    lines.append("🤖 SMART DURATION — البوت يختار المدة من بيانات السوق.")
    lines.append("✋ MANUAL DURATION — أنت تختار من المدد المدعومة فعلياً.")
    lines.append("")
    lines.append("<i>مدة الصفقة مستقلة عن فريم الشموع المستخدم في التحليل.</i>")
    return "\n".join(lines)


def smarty_card_text(asset: Asset, source_state: str, detail: str | None = None) -> str:
    return market_page_text(asset, source_state, detail)


def smarty_assets_text(assets: list[Asset], market: Market | None = None) -> str:
    label = market_label(market.value) if market else "SMARTY"
    lines = [
        f"<b>{label} MARKET</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"أصول {label} المكتشفة من حساب ExpertOption:",
        "",
    ]
    for asset in assets:
        ident = f" · ID {asset.bridge_id}" if asset.bridge_id else ""
        lines.append(f"• {asset.display}{ident}")
    lines.append("")
    lines.append("اختر الأصل بضغطة واحدة، ثم اختر مدة الصفقة.")
    return "\n".join(lines)


def _smc_lines(result: AnalysisResult) -> list[str]:
    smc = result.smc or {}
    if not smc:
        return []
    lines = ["", "<b>STRUCTURE / SMC</b>"]
    lines.append(f"MARKET STRUCTURE: {smc.get('trend', '—')}")
    event = smc.get("last_event") or {}
    if event:
        lines.append(f"LAST EVENT: {event.get('event', '—')} ({event.get('direction', '—')})")
    zone = (smc.get("premium_discount") or {}).get("zone")
    if zone:
        lines.append(f"ZONE: {zone}")
    gaps = smc.get("fair_value_gaps") or []
    if gaps:
        last_gap = gaps[-1]
        lines.append(f"FVG: {len(gaps)} active · nearest {last_gap['direction']}")
    blocks = smc.get("order_blocks") or []
    if blocks:
        lines.append(f"ORDER BLOCKS: {len(blocks)}")
    sweeps = smc.get("sweeps") or []
    if sweeps:
        last_sweep = sweeps[-1]
        lines.append(f"LIQUIDITY SWEEPS: {len(sweeps)} · last {last_sweep['direction']}")
    if smc.get("equal_highs"):
        lines.append(f"EQUAL HIGHS: {len(smc['equal_highs'])}")
    if smc.get("equal_lows"):
        lines.append(f"EQUAL LOWS: {len(smc['equal_lows'])}")
    return lines


def smarty_result_text(result: AnalysisResult, record: SignalRecord | None) -> str:
    ind = result.indicators or {}
    lines = [
        f"<b>ROZLF AI — {market_label(result.market)} ANALYSIS</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"ASSET: <b>{result.asset_display}</b>",
        f"MARKET: {market_label(result.market)}",
        f"DIRECTION: <b>{result.direction}</b>",
        f"EVIDENCE SCORE: <b>{result.confidence:.0f}%</b> "
        f"<i>(UP {result.score_up:.0f} · DOWN {result.score_down:.0f})</i>",
        f"ENTRY: {format_price(result.price, result.market)}",
        f"TREND: {result.trend_summary} | MOMENTUM: {result.momentum_strength}",
        f"DATA QUALITY: {result.data_confidence.get('level', '—')} ({result.data_confidence.get('score', 0)}%)",
        f"SOURCE: {result.source}",
    ]
    last_candle = ind.get("last_candle_at")
    if last_candle:
        lines.append(f"LAST CANDLE: {last_candle.replace('T', ' ')[:19]} UTC")
    lines.append(f"ANALYSED AT: {local_time(result.generated_at)}")
    if ind:
        lines.append("")
        lines.append("<b>INDICATORS</b>")
        rsi = ind.get("rsi")
        macd = ind.get("macd_hist")
        if isinstance(rsi, (int, float)):
            lines.append(f"RSI: {rsi:.1f}")
        if isinstance(macd, (int, float)):
            lines.append(f"MACD HIST: {macd:+.6f}")
        emas = [
            f"EMA{period} {format_price(ind[key], result.market)}"
            for period, key in (("9", "ema9"), ("21", "ema21"), ("50", "ema50"), ("200", "ema200"))
            if ind.get(key)
        ]
        if emas:
            lines.append(" · ".join(emas))
        k, d = ind.get("stoch_k"), ind.get("stoch_d")
        if k is not None and d is not None:
            lines.append(f"STOCHASTIC: K {k:.1f} / D {d:.1f}")
        lines.append(
            f"TREND: {ind.get('trend', '—')} · MOMENTUM: {ind.get('momentum', '—')}"
            f" · VOLATILITY: {ind.get('volatility', '—')}"
        )
        buyers, sellers = ind.get("buyers"), ind.get("sellers")
        if buyers is not None and sellers is not None:
            lines.append(f"BUYERS: {buyers}% · SELLERS: {sellers}%")
        atr = ind.get("atr")
        atr_pct = ind.get("atr_pct")
        if atr:
            suffix = f" ({atr_pct:.3f}%)" if isinstance(atr_pct, (int, float)) else ""
            lines.append(f"ATR: {format_price(atr, result.market)}{suffix}")
        support = ind.get("support") or []
        resistance = ind.get("resistance") or []
        if support:
            lines.append(f"SUPPORT: {format_price(support[0], result.market)}")
        if resistance:
            lines.append(f"RESISTANCE: {format_price(resistance[0], result.market)}")
    lines.extend(_smc_lines(result))
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


def markets_selector_text() -> str:
    return (
        "🌐 <b>MARKET DESK</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>EXPERT-OPTION MARKETS</b>\n"
        "🧠 SMARTY MARKET\n"
        "⚽ FOOTBALL INDEX\n"
        "💎 LUXURY INDEX\n"
        "🤖 AI INDEX\n"
        "🏏 CRICKET INDEX\n\n"
        "<b>CURRENCY MARKET</b>\n"
        "💱 FOREX MARKET\n\n"
        "كل سوق يعمل بمحرك مستقل وبياناته الحقيقية. "
        "اختر السوق مباشرة."
    )


def unified_result_text(
    result: AnalysisResult,
    duration_seconds: int | None,
    analysis_frame: str,
    record: SignalRecord | None = None,
) -> str:
    direction = getattr(record, "direction", None) or "NO TRADE"
    expiry = getattr(record, "expiry_seconds", None)
    confidence = getattr(record, "confidence", None)
    if confidence is None:
        confidence = getattr(result, "confidence", None)
    return signal_card_text(
        getattr(result, "market", ""),
        getattr(result, "asset_display", ""),
        direction,
        expiry,
        confidence,
    )


def analysis_details_text(result: AnalysisResult, record: SignalRecord | None = None) -> str:
    indicators = result.indicators
    lines = [
        f"🔍 <b>ANALYSIS DETAILS — {result.asset_display}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"MARKET: {market_label(result.market)}",
        f"TIMEFRAME: {result.timeframe}",
        f"TREND: {result.trend_summary or 'NEUTRAL'} · MOMENTUM: {result.momentum_strength}",
        f"EVIDENCE SCORE: {result.confidence:.0f}% · DATA QUALITY: {result.data_quality_score:.1f}/10",
    ]
    rsi = indicators.get("rsi")
    if isinstance(rsi, (int, float)):
        lines.append(f"RSI: {rsi:.1f}")
    if result.reasons:
        lines.append("")
        lines.append("<b>TECHNICAL REASONS</b>")
        lines.extend(f"• {reason}" for reason in result.reasons[:6])
    lines.extend(_smc_lines(result))
    if result.warnings:
        lines.append("")
        lines.extend(f"⚠️ {warning}" for warning in result.warnings[:4])
    if record is not None:
        entry = getattr(record, "entry_price", None)
        if entry is not None:
            lines.append("")
            lines.append(f"ENTRY: {format_price(entry, getattr(record, 'market', result.market))}")
            created = getattr(record, "created_at", None)
            expires = getattr(record, "expires_at", None)
            if created:
                lines.append(f"SIGNAL TIME: {local_time(created)}")
            if expires:
                lines.append(f"EXPIRY: {local_time(expires)} · ID #{getattr(record, 'id', '—')}")
    lines.append("")
    lines.append("<i>Confidence Score يقيس جودة الأدلة، وليس نسبة ربح مضمونة.</i>")
    return "\n".join(lines)


def markets_text(market: str, assets: list[Asset], tfs: list[str]) -> str:
    title = {
        Market.FOREX.value: "💱 FOREX MARKET",
        Market.SMARTY.value: "🧠 SMARTY MARKET",
        Market.AI.value: "🤖 AI INDEX",
        Market.FOOTBALL.value: "⚽ FOOTBALL INDEX",
        Market.LUXURY.value: "💎 LUXURY INDEX",
        Market.CRICKET.value: "🏏 CRICKET INDEX",
    }.get(market, market)
    lines = [f"{title}", "━━━━━━━━━━━━━━━━━━", "📡 DATA: <b>LIVE</b>", ""]
    if not assets:
        lines.append("لا توجد أصول نشطة لهذا السوق الآن.")
        return "\n".join(lines)
    lines.append(f"🎯 ASSETS: <b>{len(assets)}</b>")
    for asset in assets:
        ident = f" · ID {asset.bridge_id}" if asset.bridge_id else ""
        lines.append(f"• {asset.display}{ident}")
    lines.append("")
    lines.append("اختر الأصل الحقيقي المتاح، ثم اختر طريقة تحديد مدة الصفقة.")
    return "\n".join(lines)


def timeframes_line() -> str:
    frames = ", ".join(TIMEFRAMES[code].label for code in ("1min", "5min", "15min", "30min", "1h"))
    return f"AVAILABLE FRAMES: {frames}"
