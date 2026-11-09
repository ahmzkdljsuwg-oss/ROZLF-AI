"""Message templates (HTML parse mode)."""

from __future__ import annotations

from datetime import datetime, timezone

from ..engines.signals.generator import SignalDraft
from ..engines.technical.analyzer import DOWN, UP
from ..providers.base import Asset
from ..providers.catalog import market_label, timeframe_label

DIRECTION_AR = {UP: "UP · شراء", DOWN: "DOWN · بيع"}


def welcome(version: str, ai_ready: bool, forex_ready: bool, otc_ready: bool) -> str:
    def dot(flag: bool) -> str:
        return "🟢" if flag else "🔴"

    return (
        "<b>ROZLF AI</b>\n"
        "<i>Advanced Trading Intelligence</i>\n\n"
        "تحليل فني حقيقي على بيانات سوق مباشرة، مع هيكل سوق (SMC) وإدارة إشارات وقياس دقة فعلي.\n\n"
        f"{dot(forex_ready)} FOREX — Twelve Data\n"
        f"{dot(otc_ready)} OTC / SMARTY — جسر ExpertOption\n"
        f"{dot(ai_ready)} Mistral AI\n\n"
        "اختر التحليل من الأزرار. للصور: أرسل صورة الشارت مباشرة بعد الضغط على «تحليل صورة».\n\n"
        f"<i>v{version} · لا توجد ضمانات أرباح. التحليل أداة مساعدة لا نصيحة استثمارية.</i>"
    )


def signal_card(draft: SignalDraft, *, ai_note: str = "", ai_state: str = "") -> str:
    a = draft.analysis
    asset = draft.asset
    lines = [
        f"<b>إشارة {DIRECTION_AR.get(a.direction, a.direction)}</b>",
        f"الأصل: <b>{asset.symbol}</b> · {asset.name}",
        f"السوق: <b>{market_label(asset.market)}</b>",
        f"الفريم: {timeframe_label(draft.timeframe)} · الصلاحية: <b>{draft.expiry} ثانية</b>",
        f"سعر الدخول: <code>{a.entry}</code>",
    ]
    if a.stop:
        lines.append(f"وقف الخسارة: <code>{a.stop}</code>")
    if a.target:
        lines.append(f"الهدف: <code>{a.target}</code> · R:R {a.rr}")
    lines.append(f"قوة الإشارة: <b>{a.score}/100</b>")
    lines.append(f"مصدر البيانات: <code>{draft.source}</code> · جودة: {draft.validation_quality}")
    lines.append("\n<b>الأسباب</b>")
    lines.extend(f"• {reason}" for reason in a.reasons[:8])
    warnings = draft.warnings_text()
    if warnings:
        lines.append("\n<b>تحذيرات</b>")
        lines.extend(f"• {w}" for w in warnings.split("\n")[:6])
    if ai_state:
        lines.append(f"\n<b>Mistral AI</b> · {ai_state}")
        if ai_note:
            lines.append(ai_note)
    elif ai_note:
        lines.append(f"\n<b>Mistral AI</b>\n{ai_note}")
    lines.append(
        "\n<i>هذه إشارة تعليمية مبنية على البيانات أعلاه فقط. النتيجة تُحسب بعد انتهاء الصلاحية بسعر حقيقي.</i>"
    )
    return "\n".join(lines)


def no_trade_card(asset: Asset, timeframe: int, score: int, warnings: list[str], reasons: list[str]) -> str:
    lines = [
        "<b>NO TRADE</b>",
        f"{asset.symbol} · {market_label(asset.market)} · {timeframe_label(timeframe)}",
        f"الدرجة: <b>{score}/100</b>",
        "",
        "<b>لماذا لا توجد صفقة</b>",
    ]
    for warning in warnings[:6]:
        lines.append(f"• {warning}")
    if reasons:
        lines.append("")
        lines.append("<b>ما ظهر في التحليل</b>")
        lines.extend(f"• {r}" for r in reasons[:5])
    lines.append("\n<i>لا تُفتح صفقة بدون تحقق الشروط — هذا هو السلوك الصحيح.</i>")
    return "\n".join(lines)


def result_card(row: dict) -> str:
    icon = {"WIN": "✅", "LOSS": "❌", "DRAW": "➖"}.get(row["result"], "❔")
    duration = max(0, row["resolved_at"] - row["created_at"])
    return (
        f"{icon} <b>النتيجة: {row['result']}</b>\n"
        f"{row['symbol']} · {row['market']} · {DIRECTION_AR.get(row['direction'], row['direction'])}\n"
        f"الدخول: <code>{row['entry']}</code> → الخروج: <code>{row['exit']}</code>\n"
        f"المدة: {duration} ثانية · المصدر: {row['source']}\n"
        f"<i>النتيجة محسوبة من سعر حقيقي بعد انتهاء الصلاحية.</i>"
    )


def live_block(rows: list[dict]) -> str:
    if not rows:
        return "<b>الإشارات الحية</b>\n\nلا توجد إشارات مفتوحة الآن."
    now = int(datetime.now(timezone.utc).timestamp())
    lines = ["<b>الإشارات الحية</b>", ""]
    for row in rows:
        left = max(0, row["expires_at"] - now)
        lines.append(
            f"#{row['id']} <b>{row['symbol']}</b> {row['direction']} · دخول {row['entry']} · "
            f"متبقٍ {left}ث · score {row['score']}"
        )
    return "\n".join(lines)


def history_block(rows: list[dict], page: int, per_page: int) -> str:
    if not rows:
        return "<b>سجل الإشارات</b>\n\nالسجل فارغ."
    lines = [f"<b>سجل الإشارات</b> · صفحة {page}", ""]
    for row in rows:
        when = datetime.fromtimestamp(row["created_at"], tz=timezone.utc).strftime("%m-%d %H:%M")
        tag = row["result"] or row["status"]
        lines.append(
            f"#{row['id']} {when} · <b>{row['symbol']}</b> {row['direction']} {row['expiry_seconds']}s · "
            f"{row['status']} {tag} · score {row['score']}"
        )
    return "\n".join(lines)


def stats_block(stats: dict) -> str:
    def pct(value, suffix="%"):
        return "—" if value is None else f"{value}{suffix}"

    lines = [
        "<b>إحصاء الدقة</b>",
        "",
        f"إجمالي الإشارات: <b>{stats.get('total', 0)}</b>",
        f"محسومة: <b>{stats.get('resolved', 0)}</b> (WIN/LOSS/DRAW)",
        f"WIN: <b>{stats.get('wins', 0)}</b> · LOSS: <b>{stats.get('losses', 0)}</b> · DRAW: {stats.get('draws', 0)}",
        f"غير متحقق: {stats.get('unverified', 0)} · مفتوحة: {stats.get('open', 0)}",
        f"الدقة الفعلية: <b>{pct(stats.get('accuracy'))}</b>",
        f"اليوم: {stats.get('today', 0)} إشارة",
    ]
    streak = stats.get("streak") or {}
    if streak.get("count"):
        lines.append(f"سلسلة حالية: {streak.get('kind')} × {streak.get('count')}")
    per_market = stats.get("per_market") or []
    if per_market:
        lines.append("")
        lines.append("<b>حسب السوق</b>")
        for row in per_market:
            lines.append(
                f"• {row['market']}: {row['wins']}W/{row['losses']}L · {pct(row['accuracy'])}"
            )
    if stats.get("note"):
        lines.append(f"\n<i>{stats['note']}</i>")
    return "\n".join(lines)


def sources_block(statuses: list[dict], markets: list[dict]) -> str:
    lines = ["<b>مصادر البيانات</b>", ""]
    for row in statuses:
        icon = "🟢" if row.get("connected") else ("🟡" if row.get("configured") else "🔴")
        lines.append(f"{icon} <b>{row.get('title') or row.get('name')}</b>")
        lines.append(f"   {row.get('detail') or ''}")
    lines.append("")
    lines.append("<b>جاهزية الأسواق</b>")
    for row in markets:
        icon = "🟢" if row.get("available") else "🔴"
        lines.append(f"{icon} {row['market']} · {row['assets']} أصل · {row['provider']}")
    return "\n".join(lines)


def catalog_block(rows: list[dict], page: int, per_page: int) -> str:
    chunk = rows[page * per_page : (page + 1) * per_page]
    lines = [f"<b>الكتالوج</b> · صفحة {page + 1}", ""]
    for row in chunk:
        lines.append(
            f"<b>{row['symbol']}</b> · {row['market']} · {row['provider']}\n"
            f"   {row['name']} · {'/'.join(row['timeframes'])}"
        )
    return "\n".join(lines)
