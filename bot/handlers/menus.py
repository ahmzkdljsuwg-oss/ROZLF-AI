"""Telegram commands and inline-keyboard handlers (update in place, no spam)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot import formatting as fmt
from bot.context import get_context
from bot.keyboards import menus
from engines.signals.generator import DURATION_LABELS
from providers.base import DataUnavailable
from providers.catalog import TIMEFRAMES, Market, assets_for, get_asset, timeframe

logger = logging.getLogger(__name__)
router = Router(name="menus")

MARKETS = {market.value: market for market in Market}


async def _edit(callback: CallbackQuery, text: str, keyboard=None) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc):
            await callback.message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


async def _show_main(message: Message) -> None:
    ctx = get_context()
    await message.answer(
        fmt.welcome_text(ctx.settings),
        reply_markup=menus.main_menu(),
        disable_web_page_preview=True,
    )


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message) -> None:
    await _show_main(message)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"CHAT ID: <code>{message.chat.id}</code>\nUSER ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    stats = await get_context().repo.statistics(message.from_user.id)
    await message.answer(fmt.stats_text(stats), reply_markup=menus.back_to_main())


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    records = await get_context().repo.recent_signals(10, message.from_user.id)
    await message.answer(fmt.history_text(records), reply_markup=menus.back_to_main())


@router.message(Command("scan"))
async def cmd_scan(message: Message) -> None:
    ctx = get_context()
    scanner = ctx.scanner
    if scanner is None:
        await message.answer("الماسح غير مهيأ.")
        return
    await message.answer(
        _scanner_text(ctx), reply_markup=menus.scanner_menu(scanner.running, scanner.market_selection())
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    await _send_status(message)


async def _send_status(message: Message) -> None:
    ctx = get_context()
    scanner = ctx.scanner
    text = fmt.status_text(
        ctx.settings,
        ctx.registry.statuses(),
        ctx.source_map(),
        ctx.ai_health(),
    )
    if scanner is not None:
        text += (
            f"\n\nSCANNER: {'🟢 RUNNING' if scanner.running else '⏹ STOPPED'}"
            f"\nMARKETS: {', '.join(scanner.market_selection())}"
        )
        if scanner.last_run:
            text += f"\nLAST SCAN: {fmt.local_time(scanner.last_run)} ({scanner.last_found} signals)"
        if scanner.last_error:
            text += f"\nLAST SCANNER ERROR: {scanner.last_error[:120]}"
    await message.answer(text, disable_web_page_preview=True)


@router.callback_query(F.data.in_({"menu:main", "menu:refresh"}))
async def cb_main(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    await _edit(callback, fmt.welcome_text(ctx.settings), menus.main_menu())


@router.callback_query(F.data.startswith("mkt:"))
async def cb_market(callback: CallbackQuery) -> None:
    market = MARKETS.get(callback.data.split(":", 1)[1].lower())
    await callback.answer()
    if market is None:
        await _edit(callback, "MARKET غير معروف.", menus.back_to_main())
        return
    assets = assets_for(market)
    text = fmt.markets_text(market.value, assets, [tf.label for tf in TIMEFRAMES.values()])
    if market.is_expertoption:
        text += "\n\n<i>هذا السوق يعمل فقط عند توصيل جسر ExpertOption موثّق.</i>"
    await _edit(callback, text, menus.market_menu(market))


@router.callback_query(F.data.startswith("ast:"))
async def cb_asset(callback: CallbackQuery) -> None:
    asset = get_asset(callback.data.split(":", 1)[1])
    await callback.answer()
    if asset is None:
        await _edit(callback, "ASSET غير معروف.", menus.back_to_main())
        return
    text = (
        f"<b>{asset.display}</b>\n"
        f"MARKET: {asset.market.label}\n"
        f"DATA SOURCE: {get_context().registry.source_summary(asset)}\n\n"
        "اختر الفريم لبدء التحليل الفني + SMC:"
    )
    await _edit(callback, text, menus.asset_menu(asset))


async def _run_analysis(callback: CallbackQuery, asset_key: str, frame_code: str) -> None:
    ctx = get_context()
    asset = get_asset(asset_key)
    if asset is None or frame_code not in TIMEFRAMES:
        await callback.answer("طلب غير صالح", show_alert=True)
        return
    await callback.answer("⏳ جاري التحليل...")
    await _edit(callback, f"⏳ ANALYSING {asset.display} {TIMEFRAMES[frame_code].label}...", None)
    try:
        market_data, result = await ctx.generator.fetch_and_analyse(asset, frame_code)
    except DataUnavailable as exc:
        detail = f"\n\nDETAIL: {exc.detail}" if exc.detail else ""
        await _edit(
            callback,
            f"<b>ROZLF AI — {asset.display}</b>\n\n<b>{fmt.DATA_UNAVAILABLE}</b>\n"
            f"{exc.message}{detail}\n\n"
            "لن يتم إصدار إشارة من بيانات غير موثوقة.",
            menus.back_only(f"ast:{asset.key}", "🔙 BACK"),
        )
        return

    note = ""
    try:
        ai_note = await ctx.mistral.analyse_setup(
            {
                "asset": result.asset_display,
                "market": result.market,
                "timeframe": result.timeframe,
                "decision": result.direction,
                "confidence": result.confidence,
                "price": result.price,
                "trend": result.indicators.get("trend"),
                "rsi": result.indicators.get("rsi"),
                "macd_hist": result.indicators.get("macd_hist"),
                "structure": result.smc.get("trend"),
                "reasons": result.reasons,
                "warnings": result.warnings,
            }
        )
        note = f"<b>AI SUMMARY</b>\n{ai_note}\n\n"
    except Exception as exc:
        logger.info("Mistral summary unavailable: %s", exc)

    text = fmt.analysis_text(result)
    if note:
        text += "\n\n" + note.rstrip()
    if result.direction == "NO TRADE":
        text += "\n\n<i>لا توجد إشارة: الأدلة غير كافية. يمكنك إعادة التحليل لاحقاً.</i>"
    text += f"\n\nDATA: {market_data.source} | {market_data.validation.bar_count} bars"
    await _edit(callback, text, menus.analysis_actions(asset, frame_code))


@router.callback_query(F.data.startswith("tf:") | F.data.startswith("an:"))
async def cb_analyse(callback: CallbackQuery) -> None:
    _, asset_key, frame_code = callback.data.split(":", 2)
    await _run_analysis(callback, asset_key, frame_code)


@router.callback_query(F.data.startswith("sg:"))
async def cb_signal(callback: CallbackQuery) -> None:
    ctx = get_context()
    _, asset_key, frame_code, duration_raw = callback.data.split(":", 3)
    asset = get_asset(asset_key)
    try:
        duration = int(duration_raw)
    except ValueError:
        duration = 0
    if asset is None or duration <= 0:
        await callback.answer("طلب غير صالح", show_alert=True)
        return

    await callback.answer("⏳ جاري إنشاء الإشارة...")
    await _edit(callback, f"⏳ GENERATING SIGNAL — {asset.display}...", None)
    user_settings = await ctx.repo.get_user_settings(
        callback.from_user.id, defaults={"min_confidence": ctx.settings.min_confidence}
    )
    try:
        result, record = await ctx.generator.generate(
            callback.from_user.id,
            asset,
            frame_code,
            duration_seconds=duration,
            min_confidence=user_settings["min_confidence"],
        )
    except DataUnavailable as exc:
        await _edit(
            callback,
            f"<b>ROZLF AI — {asset.display}</b>\n\n<b>{fmt.DATA_UNAVAILABLE}</b>\n{exc.message}",
            menus.back_only(f"ast:{asset.key}", "🔙 BACK"),
        )
        return

    if record is None:
        await _edit(
            callback,
            f"<b>ROZLF AI — {asset.display}</b>\n\n"
            f"NO TRADE — الثقة {result.confidence:.0f}% أقل من الحد "
            f"({user_settings['min_confidence']:.0f}%) أو الأدلة متعارضة.\n\n"
            "لم يتم تسجيل أي إشارة.",
            menus.analysis_actions(asset, frame_code),
        )
        return

    ai_note = None
    try:
        ai_note = await ctx.mistral.analyse_setup(
            {
                "asset": record.asset_display,
                "market": record.market,
                "direction": record.direction,
                "expiry_seconds": record.expiry_seconds,
                "confidence": record.confidence,
                "entry": record.entry_price,
                "reasons": record.reasons,
                "indicators": result.indicators,
                "structure": result.smc,
            }
        )
    except Exception as exc:
        logger.info("Mistral signal note unavailable: %s", exc)

    await _edit(
        callback,
        fmt.signal_text(record, ai_note),
        menus.back_only(f"ast:{asset.key}", "🔙 BACK"),
    )


@router.callback_query(F.data == "live")
async def cb_live(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    records = await ctx.repo.active_signals(callback.from_user.id)
    if not records:
        await _edit(callback, "📡 لا توجد إشارات نشطة الآن.", menus.back_to_main())
        return
    body = "\n\n".join(
        f"#{r.id} {r.asset_display} — {r.direction} — {fmt.duration_label(r.expiry_seconds)}\n"
        f"ENTRY {fmt.format_price(r.entry_price, r.market)} · CONF {r.confidence:.0f}% · "
        f"CLOSES {fmt.local_time(r.expires_at)}"
        for r in records
    )
    await _edit(callback, f"<b>📡 LIVE SIGNALS</b>\n━━━━━━━━━━━━━━━━━━\n{body}", menus.back_to_main())


@router.callback_query(F.data == "hist")
async def cb_history(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    records = await ctx.repo.recent_signals(10, callback.from_user.id)
    await _edit(callback, fmt.history_text(records), menus.back_to_main())


@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    stats = await ctx.repo.statistics(callback.from_user.id)
    await _edit(callback, fmt.stats_text(stats), menus.back_to_main())


@router.callback_query(F.data == "status")
async def cb_status(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    await _send_status(callback.message)


@router.callback_query(F.data == "img:help")
async def cb_image_help(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit(
        callback,
        "<b>🖼 AI IMAGE ANALYSIS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "أرسل صورة شارت (PNG / JPG / JPEG / WEBP) وسيقوم ROZLF AI بتحليلها.\n\n"
        "سيتم فحص: الجودة، الأصل، الفريم، الاتجاه، الدعم والمقاومة، BOS/CHoCH/FVG.\n\n"
        "ملاحظات مهمة:\n"
        "• لا يستخرج البوت سعراً حياً من صورة قديمة.\n"
        "• الصورة الغامضة ستُرفض مع طلب صورة أوضح.\n"
        "• تحليل الصور يعمل عبر Mistral Vision عند إعداد المفتاح.",
        menus.image_help_back(),
    )


@router.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    user = await ctx.repo.get_user_settings(
        callback.from_user.id, defaults={"min_confidence": ctx.settings.min_confidence, "scanner_enabled": ctx.settings.scanner_enabled}
    )
    text = (
        "<b>⚙️ SETTINGS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"MIN CONFIDENCE: <b>{user['min_confidence']:.0f}%</b>\n"
        f"SCANNER: {'ON ✅' if user['scanner_enabled'] else 'OFF ⬜'}\n"
        f"EXCHANGE-RATE SOURCES: {', '.join(f'{k}: {v}' for k, v in ctx.source_map().items())}\n\n"
        "اختر حد الثقة الأدنى للإشارات:"
    )
    await _edit(callback, text, menus.settings_menu(user["min_confidence"], user["scanner_enabled"]))


@router.callback_query(F.data.startswith("set:min:"))
async def cb_set_min(callback: CallbackQuery) -> None:
    ctx = get_context()
    try:
        value = float(callback.data.split(":", 2)[2])
    except (IndexError, ValueError):
        await callback.answer("قيمة غير صالحة", show_alert=True)
        return
    value = max(50.0, min(95.0, value))
    user = await ctx.repo.get_user_settings(callback.from_user.id)
    user["min_confidence"] = value
    await ctx.repo.save_user_settings(callback.from_user.id, user)
    await callback.answer(f"تم ضبط الحد على {value:.0f}%")
    await cb_settings(callback)


@router.callback_query(F.data == "set:scan")
async def cb_set_scan(callback: CallbackQuery) -> None:
    ctx = get_context()
    user = await ctx.repo.get_user_settings(callback.from_user.id)
    user["scanner_enabled"] = not user["scanner_enabled"]
    await ctx.repo.save_user_settings(callback.from_user.id, user)
    if ctx.scanner is not None:
        if user["scanner_enabled"]:
            await ctx.scanner.start()
        else:
            await ctx.scanner.stop()
    await callback.answer("تم تحديث حالة الماسح")
    await cb_settings(callback)


@router.callback_query(F.data == "scan:menu")
async def cb_scanner(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    scanner = ctx.scanner
    if scanner is None:
        await _edit(callback, "الماسح غير مهيأ.", menus.back_to_main())
        return
    await _edit(
        callback,
        _scanner_text(ctx),
        menus.scanner_menu(scanner.running, scanner.market_selection()),
    )


def _scanner_text(ctx) -> str:
    scanner = ctx.scanner
    text = (
        "<b>🛰 AUTO SCANNER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"STATUS: {'🟢 RUNNING' if scanner.running else '⏹ STOPPED'}\n"
        f"MARKETS: {', '.join(scanner.market_selection())}\n"
        f"MIN CONFIDENCE: {ctx.settings.min_confidence:.0f}%\n"
        f"INTERVAL: {ctx.settings.scan_interval}s\n"
    )
    if scanner.last_run:
        text += f"LAST SCAN: {fmt.local_time(scanner.last_run)}\nSIGNALS: {scanner.last_found}\n"
    if scanner.last_error:
        text += f"LAST ERROR: {scanner.last_error[:150]}\n"
    text += (
        "\nالفحص يغطي: FOREX M5/M15، GOLD M15، OTC/SMARTY M1/M5 (عند توفر جسر موثّق).\n"
        "يتم منع الإشارات المكررة وتجاهل البيانات الضعيفة تلقائياً."
    )
    return text


@router.callback_query(F.data == "scan:toggle")
async def cb_scan_toggle(callback: CallbackQuery) -> None:
    ctx = get_context()
    scanner = ctx.scanner
    if scanner is None:
        await callback.answer("الماسح غير مهيأ", show_alert=True)
        return
    if scanner.running:
        await scanner.stop()
        await callback.answer("تم إيقاف الماسح")
    else:
        await scanner.start()
        await callback.answer("تم تشغيل الماسح")
    await cb_scanner(callback)


@router.callback_query(F.data == "scan:now")
async def cb_scan_now(callback: CallbackQuery) -> None:
    ctx = get_context()
    scanner = ctx.scanner
    if scanner is None:
        await callback.answer("الماسح غير مهيأ", show_alert=True)
        return
    await callback.answer("⏳ جاري فحص الأسواق...")
    await _edit(callback, "⏳ SCANNING MARKETS...", None)
    records = await scanner.scan_once(
        user_ids=[callback.from_user.id],
        min_confidence=ctx.settings.min_confidence,
    )
    if not records:
        await _edit(
            callback,
            "<b>🛰 SCAN COMPLETE</b>\n\nلا توجد فرص تتجاوز حد الثقة حالياً.\n"
            "لم يتم إصدار إشارات ضعيفة.",
            menus.back_only("scan:menu", "🔙 SCANNER"),
        )
        return
    body = "\n\n".join(fmt.signal_text(record) for record in records)
    await _edit(callback, body, menus.back_only("scan:menu", "🔙 SCANNER"))


@router.callback_query(F.data.startswith("scan:mk:"))
async def cb_scan_market(callback: CallbackQuery) -> None:
    ctx = get_context()
    scanner = ctx.scanner
    if scanner is None:
        await callback.answer("الماسح غير مهيأ", show_alert=True)
        return
    market = callback.data.split(":", 2)[2].upper()
    selection = scanner.toggle_market(market)
    await callback.answer(f"MARKETS: {', '.join(selection)}")
    await cb_scanner(callback)
