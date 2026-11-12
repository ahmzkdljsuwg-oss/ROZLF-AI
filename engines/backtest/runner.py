"""Causal backtester: every decision only sees candles closed before it.

Latency is applied by entering at the close of the bar that follows the
decision; the trade expires at ``entry_time + expiry_seconds`` and is settled
with the first candle closed at or after that timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from engines.technical.analyzer import analyze_market_data
from providers.base import Candle, DataUnavailable, MarketData, Quote, ValidationReport
from providers.catalog import Asset, Timeframe


@dataclass(slots=True)
class BacktestConfig:
    asset: Asset
    timeframe: Timeframe
    expiry_seconds: int
    warmup_bars: int = 150
    latency_bars: int = 1
    step_bars: int = 1


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    decision_index: int
    entry_time: datetime
    expiry_time: datetime
    direction: str
    confidence: float
    entry_price: float
    exit_price: float
    result: str
    settled_at: datetime | None = None
    expiry_seconds: int = 0
    setup_reasons: tuple[str, ...] = ()
    strategy_labels: tuple[str, ...] = ()
    result_reason: str = ""


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    trades: int
    wins: int
    losses: int
    draws: int
    win_rate: float | None
    profit_factor: float | None
    expectancy: float
    max_drawdown: float
    decisions: int = 0
    no_trade: int = 0


@dataclass(slots=True)
class BacktestResult:
    config: BacktestConfig
    trades: list[BacktestTrade]
    metrics: BacktestMetrics
    source: str
    bars: int

    def as_dict(self) -> dict:
        return {
            "asset": self.config.asset.symbol,
            "market": self.config.asset.market.value,
            "timeframe": self.config.timeframe.code,
            "expiry_seconds": self.config.expiry_seconds,
            "source": self.source,
            "bars": self.bars,
            "metrics": metrics_dict(self.metrics),
        }


def _drawdown(pnls: list[float]) -> float:
    peak = equity = worst = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def compute_metrics(trades: list[BacktestTrade], decisions: int | None = None) -> BacktestMetrics:
    wins = sum(1 for trade in trades if trade.result == "WIN")
    losses = sum(1 for trade in trades if trade.result == "LOSS")
    draws = sum(1 for trade in trades if trade.result == "DRAW")
    decided = wins + losses
    pnls = [1.0 if trade.result == "WIN" else -1.0 if trade.result == "LOSS" else 0.0 for trade in trades]
    gross_win = float(wins)
    gross_loss = float(losses)
    return BacktestMetrics(
        trades=len(trades),
        wins=wins,
        losses=losses,
        draws=draws,
        win_rate=(wins / decided * 100) if decided else None,
        profit_factor=(gross_win / gross_loss) if gross_loss else None,
        expectancy=(sum(pnls) / len(pnls)) if pnls else 0.0,
        max_drawdown=_drawdown(pnls),
        decisions=decisions if decisions is not None else len(trades),
        no_trade=max(0, (decisions if decisions is not None else len(trades)) - len(trades)),
    )


def metrics_dict(metrics: BacktestMetrics) -> dict:
    return {
        "trades": metrics.trades,
        "wins": metrics.wins,
        "losses": metrics.losses,
        "draws": metrics.draws,
        "win_rate": round(metrics.win_rate, 2) if metrics.win_rate is not None else None,
        "profit_factor": round(metrics.profit_factor, 2) if metrics.profit_factor is not None else None,
        "expectancy": round(metrics.expectancy, 4),
        "max_drawdown": round(metrics.max_drawdown, 2),
        "decisions": metrics.decisions,
        "no_trade": metrics.no_trade,
        "no_trade_rate": round(metrics.no_trade / metrics.decisions * 100, 2) if metrics.decisions else None,
    }


def _settlement_index(
    candles: list[Candle], start: int, expiry_time: datetime, bar_seconds: int
) -> int | None:
    """Return the last candle whose close is at or before the expiry.

    Using the first candle that *opens* at/after expiry would settle one whole
    bar late and leak post-expiry price action into the result.
    """
    chosen: int | None = None
    for index in range(start, len(candles)):
        close_time = candles[index].time + timedelta(seconds=bar_seconds)
        if close_time > expiry_time:
            break
        chosen = index
    return chosen


def run_backtest(config: BacktestConfig, candles: list[Candle], source: str) -> BacktestResult:
    trades: list[BacktestTrade] = []
    decisions = 0
    first = max(config.warmup_bars, 20)
    for index in range(first, len(candles) - config.latency_bars - 1, config.step_bars):
        window = candles[: index + 1]
        decision = window[-1]
        market_data = MarketData(
            asset=config.asset,
            timeframe=config.timeframe,
            candles=window,
            source=source,
            quote=Quote(config.asset.symbol, decision.close, decision.close, decision.time, source),
            validation=ValidationReport(ok=True, bar_count=len(window), last_candle_time=decision.time),
        )
        decisions += 1
        try:
            analysis = analyze_market_data(
                market_data, now=decision.time, duration_seconds=config.expiry_seconds
            )
        except DataUnavailable:
            continue
        if analysis.direction not in ("UP", "DOWN"):
            continue
        entry_index = index + config.latency_bars
        entry = candles[entry_index]
        # Enter at the next bar open: that is the first price available after
        # the decision candle closed. Using its close would add one extra bar
        # of delay that a real trader never has.
        entry_price = entry.open
        expiry_time = entry.time + timedelta(seconds=config.expiry_seconds)
        settle_index = _settlement_index(
            candles, entry_index, expiry_time, config.timeframe.seconds
        )
        if settle_index is None:
            break
        settled_at = candles[settle_index].time + timedelta(seconds=config.timeframe.seconds)
        exit_price = candles[settle_index].close
        if exit_price == entry_price:
            outcome = "DRAW"
        elif (analysis.direction == "UP") == (exit_price > entry_price):
            outcome = "WIN"
        else:
            outcome = "LOSS"
        direction_word = "rose" if exit_price > entry_price else "fell" if exit_price < entry_price else "stayed flat"
        reason = (
            f"At a {config.expiry_seconds}s expiry the price {direction_word} "
            f"from {entry_price:.5f} to {exit_price:.5f}"
        )
        trades.append(
            BacktestTrade(
                decision_index=index,
                entry_time=entry.time,
                expiry_time=expiry_time,
                direction=analysis.direction,
                confidence=analysis.confidence,
                entry_price=entry_price,
                exit_price=exit_price,
                result=outcome,
                settled_at=settled_at,
                expiry_seconds=config.expiry_seconds,
                setup_reasons=tuple(analysis.reasons[:3]),
                strategy_labels=tuple(analysis.strategy_labels),
                result_reason=reason,
            )
        )
    return BacktestResult(config, trades, compute_metrics(trades, decisions), source, len(candles))


def walk_forward(trades: list[BacktestTrade], folds: int = 5) -> dict:
    """Chronological anchored evaluation. No parameter fitting is performed,
    so every fold is out-of-sample with respect to the fixed rule set."""
    if len(trades) < folds:
        return {"folds": [], "out_of_sample": metrics_dict(compute_metrics(trades))}
    size = len(trades) // folds
    report = []
    for fold in range(folds):
        start = fold * size
        end = len(trades) if fold == folds - 1 else (fold + 1) * size
        chunk = trades[start:end]
        report.append({"fold": fold + 1, "start": chunk[0].entry_time.isoformat(), **metrics_dict(compute_metrics(chunk))})
    holdout = trades[int(len(trades) * 0.7):]
    return {"folds": report, "out_of_sample": metrics_dict(compute_metrics(holdout))}
