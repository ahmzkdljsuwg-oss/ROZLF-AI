"""Telegram commands and inline-keyboard handlers (update in place, no spam)."""
from __future__ import annotations

import asyncio
import html
import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot import formatting as fmt
from bot.context import get_context
from bot.keyboards import menus
from engines.signals.duration import auto_frames, choose_auto_duration
from engines.markets import profile_for
from engines.signals.generator import DURATION_LABELS, supported_durations
from providers.base import DataUnavailable
from providers.catalog import SMARTY_ASSET, TIMEFRAMES, Asset, Market, assets_for, get_asset, timeframe

logger = logging.getLogger(__name__)
router = Router(name="menus")

MARKETS = {market.value: market for market in Market}
INDEX_MARKETS = menus.INDEX_MARKETS
_ANALYSIS_LOCKS: dict[int, asyncio.Lock] = {}
_LAST_ANALYSIS: dict[tuple[int, str], tuple] = {}
_PENDING_MIN: dict[int, float] = {}
_RECS_CACHE: dict[int, tuple[float, str]] = {}
TRADE_DURATION_CHOICES: tuple[int, ...] = (30, 60, 120, 180, 300)


def _analysis_lock(user_id: int) -> asyncio.Lock:
    return _ANALYSIS_LOCKS.setdefault(user_id, asyncio.Lock())


async def _present_result(
    callback: CallbackQuery,
    asset: Asset,
    frame_code: str,
    result,
    record,
    note: str | None = None,
) -> None:
    _LAST_ANALYSIS[(callback.from_user.id, asset.key)] = (result, record, note)
    await _edit(callback, fmt.unified_result_text(result, None, frame_code, record),
                menus.signal_result_menu(asset, frame_code))


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


@router.message(Command("markets"))
async def cmd_markets(message: Message) -> None:
    await message.answer(
        fmt.markets_selector_text(),
        reply_markup=menus.markets_menu(),
        disable_web_page_preview=True,
    )


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
    health = await ctx.market_health(force=True)
    text = fmt.status_text(
        ctx.settings,
        ctx.registry.statuses(),
        health,
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
    if market is None:
        await callback.answer("MARKET غير معروف", show_alert=True)
        return
    await callback.answer(f"⏳ فحص {market.label}...")
    await _show_market(callback, market)


async def _show_market(callback: CallbackQuery, market: Market) -> None:
    ctx = get_context()
    if market is Market.FOREX:
        assets = assets_for(market)
        if not assets:
            await _edit(
                callback,
                fmt.unavailable_text(market.label, "MARKET_UNAVAILABLE", "no verified provider assets"),
                menus.unavailable_menu(market),
            )
            return
        await _show_assets(callback, market, assets)
        return

    inventory = ctx.inventory
    if inventory is None:
        await _edit(
            callback,
            fmt.unavailable_text(market.label, "MARKET_UNAVAILABLE", "Market inventory is not initialised"),
            menus.unavailable_menu(market),
        )
        return
    try:
        assets = await inventory.assets(market, force=True)
    except DataUnavailable as exc:
        title = f"{market.label} UNAVAILABLE"
        code = exc.code or "MARKET_UNAVAILABLE"
        await _edit(
            callback,
            fmt.unavailable_text(title, f"{code} — {exc.message}", exc.detail),
            menus.unavailable_menu(market),
        )
        return
    if not assets:
        await _edit(
            callback,
            fmt.unavailable_text(
                f"{market.label} UNAVAILABLE",
                f"{market.value.upper()}_UNAVAILABLE — no active instrument returned by ExpertOption",
            ),
            menus.unavailable_menu(market),
        )
        return
    await _show_assets(callback, market, assets)


async def _show_assets(callback: CallbackQuery, market: Market, assets: list[Asset]) -> None:
    if len(assets) == 1:
        await _show_duration_method(callback, assets[0])
        return
    text = fmt.markets_text(market.value, assets, [tf.label for tf in TIMEFRAMES.values()])
    await _edit(callback, text, menus.market_menu(market, assets))


def _trade_durations(asset: Asset) -> list[int]:
    supported = set(_manual_durations(asset))
    return [seconds for seconds in TRADE_DURATION_CHOICES if seconds in supported]


async def _show_duration_method(callback: CallbackQuery, asset: Asset) -> None:
    ctx = get_context()
    source = ctx.registry.source_summary(asset)
    durations = _trade_durations(asset)
    if not durations:
        await _edit(
            callback,
            fmt.unavailable_text(asset.market.label, "DURATION_UNAVAILABLE", "no verified expiry for this market"),
            menus.back_to_main(),
        )
        return
    text = fmt.trade_duration_text(asset, source, durations)
    await _edit(callback, text, menus.trade_duration_menu(asset, durations))


@router.callback_query(F.data == "analysis")
async def cb_analysis(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit(callback, fmt.markets_selector_text(), menus.markets_menu())


@router.callback_query(F.data.startswith("td:"))
async def cb_trade_duration(callback: CallbackQuery) -> None:
    _, first, second = callback.data.split(":", 2)
    if first == "smart":
        asset_key, raw = second, "smart"
    else:
        asset_key, raw = first, second
    asset = get_asset(asset_key)
    if asset is None and get_context().inventory is not None:
        asset = await get_context().inventory.resolve(asset_key)
    if asset is None:
        await callback.answer("ASSET غير معروف", show_alert=True)
        return
    durations = _trade_durations(asset)
    if raw == "smart":
        await _run_analyze_time(callback, asset, durations)
        return
    try:
        duration = int(raw)
    except ValueError:
        await callback.answer("مدة غير صالحة", show_alert=True)
        return
    if duration not in durations:
        await callback.answer("هذه المدة غير مدعومة لهذا السوق", show_alert=True)
        return
    await _run_trade(callback, asset, duration)


async def _run_trade(callback: CallbackQuery, asset: Asset, duration: int, note: str | None = None) -> None:
    lock = _analysis_lock(callback.from_user.id)
    if lock.locked():
        await callback.answer("التحليل قيد التنفيذ بالفعل", show_alert=True)
        return
    await callback.answer("⏳ جاري التحليل...")
    async with lock:
        ctx = get_context()
        frame_code = analysis_frame_for_duration(asset, duration)
        await _edit(callback, f"⏳ ANALYSING {asset.display} — {fmt.trade_duration_label(duration)}...", None)
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
                fmt.unavailable_text(f"{asset.market.label} — {asset.display}", exc.code or "UNAVAILABLE", exc.detail or exc.message),
                menus.trade_duration_menu(asset, _trade_durations(asset)),
            )
            return
        await _present_result(callback, asset, frame_code, result, record, note)


def _evidence_rank(result) -> tuple[float, float, float]:
    evidence = float(getattr(result, "evidence_score", 0.0) or 0.0)
    quality = float(getattr(result, "data_quality_score", 0.0) or 0.0)
    return (evidence, quality, float(result.confidence))


async def _run_analyze_time(callback: CallbackQuery, asset: Asset, durations: list[int]) -> None:
    lock = _analysis_lock(callback.from_user.id)
    if lock.locked():
        await callback.answer("التحليل قيد التنفيذ بالفعل", show_alert=True)
        return
    await callback.answer("🧠 مقارنة المدد...")
    async with lock:
        ctx = get_context()
        await _edit(callback, f"🧠 ANALYZE TRADE TIME — {asset.display}...", None)
        notes: list[str] = []
        best = None
        for duration in durations:
            frame_code = analysis_frame_for_duration(asset, duration)
            try:
                _, result = await ctx.generator.fetch_and_analyse(asset, frame_code)
            except DataUnavailable as exc:
                notes.append(f"{fmt.trade_duration_label(duration)}: {exc.message}")
                continue
            if result.direction == "NO TRADE":
                notes.append(f"{fmt.trade_duration_label(duration)}: no actionable evidence")
                continue
            item = {
                "direction": result.direction,
                "confidence": result.confidence,
                "duration": duration,
                "rank": _evidence_rank(result),
            }
            if best is None or item["rank"] > best["rank"]:
                best = item
        await _edit(
            callback,
            fmt.analyze_time_text(asset, best, durations, notes),
            menus.trade_duration_menu(asset, durations),
        )


async def _run_recommendations(callback: CallbackQuery) -> None:
    ctx = get_context()
    user_settings = await ctx.repo.get_user_settings(
        callback.from_user.id, defaults={"min_confidence": ctx.settings.min_confidence}
    )
    threshold = float(user_settings["min_confidence"])
    cached = _RECS_CACHE.get(callback.from_user.id)
    if cached and time.monotonic() - cached[0] < 45:
        await _edit(callback, cached[1], menus.back_to_main())
        return
    await _edit(callback, "🏆 SCANNING SIX MARKETS...", None)
    items: list[dict] = []
    errors: list[str] = []
    for market in (Market.SMARTY, Market.FOOTBALL, Market.LUXURY, Market.AI, Market.CRICKET, Market.FOREX):
        try:
            asset = await _primary_asset(ctx, market)
        except DataUnavailable as exc:
            errors.append(f"{market.label}: {exc.message}")
            continue
        if asset is None:
            errors.append(f"{market.label}: no active asset")
            continue
        best = None
        for frame_code in auto_frames(asset)[:2]:
            try:
                _, result = await ctx.generator.fetch_and_analyse(asset, frame_code)
            except DataUnavailable as exc:
                errors.append(f"{market.label}: {exc.message}")
                continue
            if result.direction == "NO TRADE" or result.confidence < threshold:
                continue
            duration, reason = choose_auto_duration(result, asset)
            if duration is None or duration not in _trade_durations(asset):
                continue
            item = {
                "market": market.label,
                "asset": asset.display,
                "signal": "BUY 🟢" if result.direction == "UP" else "SELL 🛑",
                "duration": duration,
                "confidence": result.confidence,
                "data": result.source or "LIVE",
                "reason": reason,
                "rank": _evidence_rank(result),
            }
            if best is None or item["rank"] > best["rank"]:
                best = item
        if best is not None:
            items.append(best)
    items.sort(key=lambda row: row["rank"], reverse=True)
    text = fmt.recommendation_text(items[:3], threshold, errors[:4])
    _RECS_CACHE[callback.from_user.id] = (time.monotonic(), text)
    await _edit(callback, text, menus.back_to_main())


async def _primary_asset(ctx, market: Market) -> Asset | None:
    if market is Market.FOREX:
        assets = assets_for(market)
        return assets[0] if assets else None
    if ctx.inventory is not None:
        assets = await ctx.inventory.assets(market, force=False)
        return assets[0] if assets else None
    assets = assets_for(market)
    return assets[0] if assets else None


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick_asset(callback: CallbackQuery) -> None:
    asset, _ = await _resolve_asset(callback)
    if asset is None:
        return
    await callback.answer()
    await _show_duration_method(callback, asset)


async def _resolve_asset(callback: CallbackQuery) -> tuple[Asset | None, str]:
    ctx = get_context()
    parts = callback.data.split(":")
    if parts[0] == "dur":
        key = parts[2] if len(parts) > 2 else ""
    else:
        key = parts[1] if len(parts) > 1 else ""
    asset = get_asset(key)
    if asset is None and ctx.inventory is not None:
        asset = await ctx.inventory.resolve(key)
    if asset is None:
        await callback.answer("ASSET غير معروف", show_alert=True)
        return None, key
    return asset, key


async def _show_index_asset(callback: CallbackQuery, asset: Asset) -> None:
    await _show_duration_method(callback, asset)


def analysis_frame_for_duration(asset: Asset, duration_seconds: int) -> str:
    if asset.market.is_expertoption:
        return smarty_timeframe(duration_seconds)
    if duration_seconds <= 60:
        return "1min"
    if duration_seconds <= 300:
        return "5min"
    if duration_seconds <= 900:
        return "15min"
    return "1h"


def _manual_durations(asset: Asset) -> list[int]:
    base = "1min" if asset.market.is_expertoption else "5min"
    frames = profile_for(asset.market).frames
    return [
        seconds for seconds in supported_durations(asset, timeframe(base))
        if analysis_frame_for_duration(asset, seconds) in frames
    ]


@router.callback_query(F.data.startswith("dur:"))
async def cb_duration_mode(callback: CallbackQuery) -> None:
    asset, _ = await _resolve_asset(callback)
    if asset is None:
        return
    mode = callback.data.split(":", 2)[1]
    if mode == "auto":
        await callback.answer("🤖 SMART DURATION...")
        await _run_auto_duration(callback, asset)
        return
    if mode == "manual":
        durations = _manual_durations(asset)
        if not durations:
            await callback.answer("هذا السوق لا يدعم اختيار مدة صفقة", show_alert=True)
            return
        await callback.answer()
        await _edit(
            callback,
            f"<b>{asset.display}</b>\n"
            f"MARKET: {asset.market.label}\n\n"
            "<b>MANUAL DURATION</b>\n"
            "اختر مدة الصفقة المدعومة فعلياً لهذا الأصل:",
            menus.manual_duration_menu(asset, durations),
        )
        return
    await callback.answer("طلب غير صالح", show_alert=True)


async def _run_auto_duration(callback: CallbackQuery, asset: Asset) -> None:
    lock = _analysis_lock(callback.from_user.id)
    if lock.locked():
        await callback.answer("التحليل قيد التنفيذ بالفعل", show_alert=True)
        return
    async with lock:
        ctx = get_context()
        await _edit(callback, f"🤖 SMART DURATION — تحليل {asset.display}...", None)
        best = None
        best_frame = None
        errors: list[str] = []
        for frame_code in auto_frames(asset):
            try:
                _, result = await ctx.generator.fetch_and_analyse(asset, frame_code)
            except DataUnavailable as exc:
                errors.append(f"{frame_code}: {exc.message}")
                continue
            if best is None or result.confidence > best.confidence:
                best, best_frame = result, frame_code
        if best is None or best_frame is None:
            await _edit(
                callback,
                fmt.unavailable_text(
                    f"ROZLF AI — {asset.display}",
                    "DATA UNAVAILABLE",
                    "; ".join(errors[:3]) or "no timeframe returned valid candles",
                ),
                menus.duration_method_menu(asset),
            )
            return
        duration, reason = choose_auto_duration(best, asset)
        record = None
        user_settings = await ctx.repo.get_user_settings(
            callback.from_user.id, defaults={"min_confidence": ctx.settings.min_confidence}
        )
        if duration is not None and best.direction in ("UP", "DOWN") and best.confidence >= user_settings["min_confidence"]:
            try:
                record = await ctx.generator.create_signal(callback.from_user.id, best, duration)
            except ValueError as exc:
                logger.info("AUTO duration rejected by generator: %s", exc)
                duration = None
        await _present_result(callback, asset, best_frame, best, record, f"SMART DURATION: {reason}")


@router.callback_query(F.data.startswith("md:"))
async def cb_manual_duration(callback: CallbackQuery) -> None:
    asset, _ = await _resolve_asset(callback)
    if asset is None:
        return
    try:
        duration = int(callback.data.split(":", 2)[2])
    except (IndexError, ValueError):
        await callback.answer("مدة غير صالحة", show_alert=True)
        return
    if duration not in _manual_durations(asset):
        await callback.answer("هذه المدة غير مدعومة لهذا الأصل", show_alert=True)
        return
    lock = _analysis_lock(callback.from_user.id)
    if lock.locked():
        await callback.answer("التحليل قيد التنفيذ بالفعل", show_alert=True)
        return
    await callback.answer("⏳ جاري التحليل...")
    async with lock:
        ctx = get_context()
        frame_code = analysis_frame_for_duration(asset, duration)
        await _edit(callback, f"⏳ تحليل {asset.display} — {DURATION_LABELS.get(duration, duration)}...", None)
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
                fmt.unavailable_text(f"ROZLF AI — {asset.display}", exc.code or "UNAVAILABLE", exc.detail or exc.message),
                menus.duration_method_menu(asset),
            )
            return
        await _present_result(callback, asset, frame_code, result, record)


@router.callback_query(F.data.startswith("ia:"))
async def cb_index_asset(callback: CallbackQuery) -> None:
    ctx = get_context()
    key = callback.data.split(":", 1)[1]
    asset = get_asset(key)
    if asset is None and ctx.inventory is not None:
        asset = await ctx.inventory.resolve(key)
    if asset is None or asset.market not in INDEX_MARKETS:
        await callback.answer("ASSET غير معروف", show_alert=True)
        return
    await callback.answer()
    await _show_index_asset(callback, asset)


@router.callback_query(F.data.startswith("ix:"))
async def cb_index_signal(callback: CallbackQuery) -> None:
    ctx = get_context()
    _, asset_key, duration_raw = callback.data.split(":", 2)
    asset = get_asset(asset_key)
    if asset is None and ctx.inventory is not None:
        asset = await ctx.inventory.resolve(asset_key)
    try:
        duration = int(duration_raw)
    except ValueError:
        duration = 0
    if asset is None or asset.market not in INDEX_MARKETS or duration <= 0:
        await callback.answer("طلب غير صالح", show_alert=True)
        return
    lock = _analysis_lock(callback.from_user.id)
    if lock.locked():
        await callback.answer("التحليل قيد التنفيذ بالفعل", show_alert=True)
        return
    await callback.answer(f"⏳ تحليل {asset.market.label}...")
    async with lock:
        await _edit(callback, f"⏳ {asset.market.label} — {asset.display} — {duration}s...", None)
        user_settings = await ctx.repo.get_user_settings(
            callback.from_user.id, defaults={"min_confidence": ctx.settings.min_confidence}
        )
        try:
            result, record = await ctx.generator.generate(
                callback.from_user.id,
                asset,
                smarty_timeframe(duration),
                duration_seconds=duration,
                min_confidence=user_settings["min_confidence"],
            )
        except DataUnavailable as exc:
            await _edit(
                callback,
                fmt.unavailable_text(asset.market.label, exc.code or "UNAVAILABLE", exc.detail or exc.message),
                menus.unavailable_menu(asset.market),
            )
            return
        await _present_result(callback, asset, smarty_timeframe(duration), result, record)


async def _show_smarty(callback: CallbackQuery) -> None:
    ctx = get_context()
    inventory = ctx.inventory
    if inventory is None:
        await _edit(
            callback,
            fmt.unavailable_text("🧠 SMARTY MARKET", "SMARTY_UNAVAILABLE", "Market inventory is not initialised"),
            menus.unavailable_menu(Market.SMARTY),
        )
        return
    try:
        assets = await inventory.assets(Market.SMARTY, force=True)
    except DataUnavailable as exc:
        await _edit(
            callback,
            fmt.unavailable_text("🧠 SMARTY MARKET", "SMARTY_UNAVAILABLE", exc.detail or exc.message),
            menus.unavailable_menu(Market.SMARTY),
        )
        return
    if not assets:
        await _edit(
            callback,
            fmt.unavailable_text("🧠 SMARTY MARKET", "SMARTY_UNAVAILABLE", "no SMARTY instrument returned"),
            menus.unavailable_menu(Market.SMARTY),
        )
        return
    if len(assets) == 1:
        await _show_smarty_asset(callback, assets[0])
        return
    text = fmt.smarty_assets_text(assets)
    await _edit(callback, text, menus.smarty_assets_menu(assets))


async def _show_smarty_asset(callback: CallbackQuery, asset: Asset) -> None:
    await _show_duration_method(callback, asset)


@router.callback_query(F.data.startswith("sa:"))
async def cb_smarty_asset(callback: CallbackQuery) -> None:
    ctx = get_context()
    key = callback.data.split(":", 1)[1]
    asset = get_asset(key)
    if asset is None and ctx.inventory is not None:
        asset = await ctx.inventory.resolve(key)
    if asset is None or asset.market is not Market.SMARTY:
        await callback.answer("ASSET غير معروف", show_alert=True)
        return
    await callback.answer()
    await _show_smarty_asset(callback, asset)


@router.callback_query(F.data.startswith("ast:"))
async def cb_asset(callback: CallbackQuery) -> None:
    ctx = get_context()
    key = callback.data.split(":", 1)[1]
    asset: Asset | None = get_asset(key)
    if asset is None and ctx.inventory is not None:
        asset = await ctx.inventory.resolve(key)
    await callback.answer()
    if asset is None:
        await _edit(callback, "ASSET غير معروف.", menus.back_to_main())
        return
    if asset.market is Market.SMARTY:
        await _show_smarty_asset(callback, asset)
        return
    text = (
        f"<b>{asset.display}</b>\n"
        f"MARKET: {asset.market.label}\n"
        f"DATA SOURCE: {ctx.registry.source_summary(asset)}\n\n"
        "اختر الفريم لبدء التحليل الفني + SMC:"
    )
    await _edit(callback, text, menus.asset_menu(asset))


async def _run_analysis(callback: CallbackQuery, asset_key: str, frame_code: str) -> None:
    ctx = get_context()
    asset = get_asset(asset_key)
    if asset is None and ctx.inventory is not None:
        asset = await ctx.inventory.resolve(asset_key)
    if asset is None or frame_code not in TIMEFRAMES:
        await callback.answer("طلب غير صالح", show_alert=True)
        return
    await callback.answer("⏳ جاري التحليل...")
    await _edit(callback, f"⏳ ANALYSING {asset.display} {TIMEFRAMES[frame_code].label}...", None)
    try:
        market_data, result = await ctx.generator.fetch_and_analyse(asset, frame_code)
    except DataUnavailable as exc:
        await _edit(
            callback,
            fmt.unavailable_text(f"ROZLF AI — {asset.display}", exc.message, exc.detail),
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
    if asset is None and ctx.inventory is not None:
        asset = await ctx.inventory.resolve(asset_key)
    try:
        duration = int(duration_raw)
    except ValueError:
        duration = 0
    if asset is None or duration <= 0:
        await callback.answer("طلب غير صالح", show_alert=True)
        return

    lock = _analysis_lock(callback.from_user.id)
    if lock.locked():
        await callback.answer("التحليل قيد التنفيذ بالفعل", show_alert=True)
        return
    await callback.answer("⏳ جاري إنشاء الإشارة...")
    async with lock:
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
                fmt.unavailable_text(f"ROZLF AI — {asset.display}", exc.message, exc.detail),
                menus.back_only(f"ast:{asset.key}", "🔙 BACK"),
            )
            return

        if record is None:
            await _present_result(callback, asset, frame_code, result, None)
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

        await _present_result(callback, asset, frame_code, result, record, ai_note)


@router.callback_query(F.data.startswith("whyd:"))
async def cb_why_signal(callback: CallbackQuery) -> None:
    _, asset_key, frame_code = callback.data.split(":", 2)
    cached = _LAST_ANALYSIS.get((callback.from_user.id, asset_key))
    if cached is None:
        await callback.answer("التحليل غير محفوظ — أعد التحليل.", show_alert=True)
        return
    result, record, note = cached
    await callback.answer()
    text = fmt.analysis_details_text(result, record)
    if note:
        text += f"\n\n<b>AI / DURATION NOTE</b>\n{html.escape(note)}"
    asset = get_asset(asset_key)
    keyboard = menus.signal_result_menu(asset, frame_code, has_details=False) if asset else menus.back_to_main()
    await _edit(callback, text, keyboard)


def smarty_timeframe(duration_seconds: int) -> str:
    if duration_seconds <= 5:
        return "5sec"
    if duration_seconds <= 15:
        return "15sec"
    if duration_seconds <= 30:
        return "30sec"
    return "1min"


@router.callback_query(F.data.startswith("sm:"))
async def cb_smarty_signal(callback: CallbackQuery) -> None:
    ctx = get_context()
    _, asset_key, duration_raw = callback.data.split(":", 2)
    asset = get_asset(asset_key)
    if asset is None and ctx.inventory is not None:
        asset = await ctx.inventory.resolve(asset_key)
    try:
        duration = int(duration_raw)
    except ValueError:
        duration = 0
    if asset is None or asset.market is not Market.SMARTY or duration <= 0:
        await callback.answer("طلب غير صالح", show_alert=True)
        return
    lock = _analysis_lock(callback.from_user.id)
    if lock.locked():
        await callback.answer("التحليل قيد التنفيذ بالفعل", show_alert=True)
        return
    await callback.answer("⏳ تحليل SMARTY...")
    async with lock:
        await _edit(callback, f"⏳ SMARTY — {asset.display} — {duration}s...", None)
        user_settings = await ctx.repo.get_user_settings(
            callback.from_user.id, defaults={"min_confidence": ctx.settings.min_confidence}
        )
        try:
            result, record = await ctx.generator.generate(
                callback.from_user.id,
                asset,
                smarty_timeframe(duration),
                duration_seconds=duration,
                min_confidence=user_settings["min_confidence"],
            )
        except DataUnavailable as exc:
            await _edit(
                callback,
                fmt.unavailable_text("🧠 SMARTY MARKET", "SMARTY_UNAVAILABLE", exc.detail or exc.message),
                menus.unavailable_menu(Market.SMARTY),
            )
            return
        await _present_result(callback, asset, smarty_timeframe(duration), result, record)


@router.callback_query(F.data == "auto")
async def cb_auto(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    scanner = ctx.scanner
    if scanner is None:
        await _edit(callback, "الماسح غير مهيأ.", menus.back_to_main())
        return
    await _edit(callback, _scanner_text(ctx), menus.scanner_menu(scanner.running, scanner.market_selection()))


@router.callback_query(F.data == "analyze")
async def cb_analyze(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit(callback, fmt.markets_selector_text(), menus.markets_menu())


@router.callback_query(F.data == "markets")
async def cb_markets(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit(callback, fmt.markets_selector_text(), menus.markets_menu())


async def _show_trend(callback: CallbackQuery) -> None:
    ctx = get_context()
    asset = get_asset("EUR_USD_FOREX")
    if asset is None:
        await _edit(callback, "ASSET غير متاح.", menus.trend_menu())
        return
    await _edit(callback, "⏳ قراءة الترند والاستراتيجيات...", None)
    try:
        market_data, result = await ctx.generator.fetch_and_analyse(asset, "1min")
    except DataUnavailable as exc:
        await _edit(
            callback,
            fmt.unavailable_text("📈 الترند والاستراتيجيات", exc.message, exc.detail),
            menus.trend_menu(),
        )
        return
    await _edit(callback, fmt.trend_summary_text(result, market_data.source), menus.trend_menu())


@router.callback_query(F.data.in_({"trend", "trend:refresh"}))
async def cb_trend(callback: CallbackQuery) -> None:
    await callback.answer("⏳ تحديث...")
    await _show_trend(callback)


@router.callback_query(F.data == "live")
async def cb_live(callback: CallbackQuery) -> None:
    ctx = get_context()
    await callback.answer()
    records = await ctx.repo.active_signals(callback.from_user.id)
    if not records:
        await _edit(
            callback,
            "📡 <b>LIVE SIGNALS</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            "لا توجد إشارات نشطة الآن.\n"
            "<i>لن يظهر هنا إلا ما تم تسجيله من بيانات حقيقية واجتاز شروط المحرك.</i>",
            menus.back_to_main(),
        )
        return
    parts = ["📡 <b>LIVE SIGNALS</b>", "━━━━━━━━━━━━━━━━━━"]
    for r in records:
        parts.append(
            f"<b>#{r.id} · {r.asset_display}</b>\n"
            f"   {fmt.market_label(r.market)} · {r.direction} · {fmt.duration_label(r.expiry_seconds)}\n"
            f"   ENTRY {fmt.format_price(r.entry_price, r.market)} · CONF {r.confidence:.0f}%\n"
            f"   CLOSES {fmt.local_time(r.expires_at)}"
        )
    await _edit(callback, "\n\n".join(parts), menus.back_to_main())


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


@router.callback_query(F.data == "recs")
async def cb_recommendations(callback: CallbackQuery) -> None:
    await callback.answer("🏆 فحص الأسواق الستة...")
    await _run_recommendations(callback)


@router.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    await _render_settings(callback)


async def _render_settings(callback: CallbackQuery) -> None:
    ctx = get_context()
    user = await ctx.repo.get_user_settings(
        callback.from_user.id, defaults={"min_confidence": ctx.settings.min_confidence}
    )
    selected = _PENDING_MIN.get(callback.from_user.id, float(user["min_confidence"]))
    text = (
        "⚙️ <b>SETTINGS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 <b>MINIMUM TRADE CONFIDENCE</b>\n"
        f"القيمة المحددة الآن: <b>{selected:.0f}%</b>\n\n"
        "اختر الحد الأدنى للثقة قبل إصدار الإشارة.\n"
        "• لا يتم عرض إشارة أقل من هذا الحد.\n"
        "• لا يتم رفع الثقة لتجاوز الحد.\n"
        "• إذا لم توجد فرصة تحققه، تكون النتيجة NO TRADE.\n\n"
        "<i>Confidence Score ليس احتمال ربح مضمون، ولا نضمن أي نسبة نجاح.</i>"
    )
    await _edit(callback, text, menus.settings_menu(selected))


@router.callback_query(F.data.startswith("set:pick:"))
async def cb_set_pick(callback: CallbackQuery) -> None:
    try:
        value = float(callback.data.split(":", 2)[2])
    except (IndexError, ValueError):
        await callback.answer("قيمة غير صالحة", show_alert=True)
        return
    value = max(50.0, min(90.0, value))
    _PENDING_MIN[callback.from_user.id] = value
    await callback.answer(f"محدد: {value:.0f}% — اضغط SAVE SETTINGS")
    await _render_settings(callback)


@router.callback_query(F.data == "set:save")
async def cb_set_save(callback: CallbackQuery) -> None:
    ctx = get_context()
    value = _PENDING_MIN.pop(callback.from_user.id, None)
    if value is None:
        await callback.answer("اختر نسبة أولاً", show_alert=True)
        return
    user = await ctx.repo.get_user_settings(callback.from_user.id)
    user["min_confidence"] = value
    await ctx.repo.save_user_settings(callback.from_user.id, user)
    _RECS_CACHE.pop(callback.from_user.id, None)
    await callback.answer(f"✅ تم الحفظ: {value:.0f}%")
    await _render_settings(callback)


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
    for market, reason in getattr(scanner, "last_skips", {}).items():
        text += f"SKIPPED {market}: {reason[:120]}\n"
    text += (
        "\nالفحص يغطي الأسواق المفعّلة فقط: FOREX، SMARTY، والأسواق المؤشرية عند توفر جسر موثّق.\n"
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
