from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from ...engines.technical.analyzer import NO_TRADE
from ...providers.base import DataUnavailable, ProviderError
from ...providers.catalog import market_label, timeframe_label
from ...services.container import AppContainer
from ...services.charts import render_signal_chart
from .. import keyboards, texts
from ..utils import edit_or_send

log = logging.getLogger(__name__)
router = Router(name="analysis")


@router.callback_query(F.data.startswith("m:"))
async def cb_market(query: CallbackQuery) -> None:
    market = (query.data or "").split(":", 1)[1]
    await edit_or_send(
        query.message,  # type: ignore[arg-type]
        f"<b>{market_label(market)}</b>\nاختر الأصل:",
        keyboards.assets_menu(market),
    )
    await query.answer()


@router.callback_query(F.data.startswith("p:"))
async def cb_page(query: CallbackQuery) -> None:
    _, market, page = (query.data or "").split(":")
    await edit_or_send(
        query.message,  # type: ignore[arg-type]
        f"<b>{market_label(market)}</b>\nاختر الأصل:",
        keyboards.assets_menu(market, int(page)),
    )
    await query.answer()


@router.callback_query(F.data.startswith("a:REFRESH:"))
async def cb_refresh(query: CallbackQuery, container: AppContainer) -> None:
    symbol = (query.data or "").split(":")[2]
    asset = container.registry.asset(symbol)
    await edit_or_send(
        query.message,  # type: ignore[arg-type]
        f"<b>{asset.symbol}</b> · {asset.name}\nاختر الفريم:",
        keyboards.timeframes_menu(asset),
    )
    await query.answer()


@router.callback_query(F.data.startswith("a:"))
async def cb_asset(query: CallbackQuery, container: AppContainer) -> None:
    _, _, symbol = (query.data or "").split(":", 2)
    asset = container.registry.asset(symbol)
    await edit_or_send(
        query.message,  # type: ignore[arg-type]
        f"<b>{asset.symbol}</b> · {asset.name}\n"
        f"السوق: {market_label(asset.market)}\n"
        f"المصدر: <code>{asset.provider}</code>\n\nاختر الفريم:",
        keyboards.timeframes_menu(asset),
    )
    await query.answer()


@router.callback_query(F.data.startswith("t:"))
async def cb_timeframe(query: CallbackQuery, container: AppContainer) -> None:
    _, symbol, tf_raw = (query.data or "").split(":", 2)
    timeframe = int(tf_raw)
    await query.answer("جارٍ التحليل…")
    await edit_or_send(query.message, f"⏳ تحليل {symbol} · {timeframe_label(timeframe)} …")

    try:
        data = await container.service.analyze(symbol, timeframe)  # type: ignore[union-attr]
    except DataUnavailable as exc:
        await query.message.answer(  # type: ignore[union-attr]
            f"<b>DATA UNAVAILABLE</b>\n{symbol} · {timeframe_label(timeframe)}\n{exc}\n\n"
            "<i>لا تُصدر إشارة بدون بيانات حقيقية.</i>",
            reply_markup=keyboards.back_to_menu(),
        )
        return
    except ProviderError as exc:
        await query.message.answer(  # type: ignore[union-attr]
            f"<b>خطأ مصدر البيانات</b>\n<code>{exc.code}</code>\n{exc}",
            reply_markup=keyboards.back_to_menu(),
        )
        return

    asset = data["asset"]
    analysis = data["analysis"]
    if analysis.direction == NO_TRADE:
        await query.message.answer(  # type: ignore[union-attr]
            texts.no_trade_card(asset, timeframe, analysis.score, analysis.warnings, analysis.reasons),
            reply_markup=keyboards.after_analysis(symbol),
        )
        return

    from ...engines.signals.generator import SignalDraft

    draft = SignalDraft(
        asset=asset,
        timeframe=timeframe,
        analysis=analysis,
        source=asset.provider,
        validation_quality=data["report"].quality,
        cross=data["cross"],
        candles=data["candles"],
    )
    ai_result = await container.service.ai_comment(draft)  # type: ignore[union-attr]
    from ...services.signal_service import _ai_text

    ai_note, ai_state = _ai_text(ai_result)
    caption = texts.signal_card(draft, ai_note=ai_note, ai_state=ai_state)
    row = await container.service.publish(draft, notify=False)  # type: ignore[union-attr]
    if row:
        caption += f"\n\n<i>تم تسجيل الإشارة #{row['id']} وستُحسم بعد {draft.expiry} ثانية.</i>"

    chart = render_signal_chart(
        data["candles"],
        symbol=asset.symbol,
        timeframe_label=timeframe_label(timeframe),
        direction=analysis.direction,
        entry=analysis.entry,
        stop=analysis.stop,
        target=analysis.target,
        score=analysis.score,
    )
    if chart:
        await query.message.answer_photo(  # type: ignore[union-attr]
            BufferedInputFile(chart, filename=f"{asset.symbol}-{timeframe}.png"),
            caption=caption[:1024],
            reply_markup=keyboards.after_analysis(symbol),
        )
    else:
        await query.message.answer(  # type: ignore[union-attr]
            caption, reply_markup=keyboards.after_analysis(symbol)
        )
