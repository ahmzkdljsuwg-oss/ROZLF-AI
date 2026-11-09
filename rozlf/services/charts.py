"""Chart rendering for Telegram (real candles only, never synthetic data)."""

from __future__ import annotations

import io
import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from ..engines.technical.indicators import ema, rsi, to_frame  # noqa: E402
from ..providers.base import Candle  # noqa: E402

log = logging.getLogger(__name__)

BG = "#0b1220"
PANEL = "#111a2b"
GRID = "#1f2a3d"
UP = "#22c55e"
DOWN = "#ef4444"
TEXT = "#e8eefc"
ACCENT = "#38bdf8"


def render_signal_chart(
    candles: list[Candle],
    *,
    symbol: str,
    timeframe_label: str,
    direction: str,
    entry: float,
    stop: float | None,
    target: float | None,
    score: int,
) -> bytes | None:
    try:
        df = to_frame(candles)
        if len(df) < 20:
            return None
        df = df.tail(90).reset_index(drop=True)
        fig, (ax, ax2) = plt.subplots(
            2, 1, figsize=(9, 5.6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}, dpi=130
        )
        _style(fig, ax)
        _style(fig, ax2)

        width = 0.62
        for i, row in df.iterrows():
            color = UP if row["close"] >= row["open"] else DOWN
            ax.add_patch(
                Rectangle((i - width / 2, min(row["open"], row["close"])), width,
                          max(abs(row["close"] - row["open"]), 1e-9), color=color, alpha=0.95)
            )
            ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.8, alpha=0.9)

        ax.plot(df.index, ema(df["close"], 9), color="#facc15", linewidth=1.1, label="EMA 9")
        ax.plot(df.index, ema(df["close"], 21), color="#a78bfa", linewidth=1.1, label="EMA 21")
        ax.plot(df.index, ema(df["close"], 50), color="#38bdf8", linewidth=1.1, label="EMA 50")

        ax.axhline(entry, color=ACCENT, linestyle="--", linewidth=1.0)
        ax.annotate(f"ENTRY {entry}", (0, entry), color=ACCENT, fontsize=8, va="bottom")
        if stop:
            ax.axhline(stop, color=DOWN, linestyle=":", linewidth=1.0)
            ax.annotate(f"SL {stop}", (0, stop), color=DOWN, fontsize=8, va="top")
        if target:
            ax.axhline(target, color=UP, linestyle=":", linewidth=1.0)
            ax.annotate(f"TP {target}", (0, target), color=UP, fontsize=8, va="bottom")

        ax.set_title(
            f"{symbol}  {timeframe_label}  |  {direction}  |  score {score}",
            color=TEXT, fontsize=11, loc="left", pad=8,
        )
        ax.legend(loc="upper left", fontsize=7, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, ncol=3)
        ax.set_ylabel("Price", color=TEXT, fontsize=8)
        ax.margins(x=0.01)

        ax2.plot(df.index, rsi(df["close"]), color=ACCENT, linewidth=1.0)
        ax2.axhline(70, color=DOWN, linewidth=0.7, linestyle=":")
        ax2.axhline(30, color=UP, linewidth=0.7, linestyle=":")
        ax2.set_ylim(0, 100)
        ax2.set_ylabel("RSI", color=TEXT, fontsize=8)
        ax2.set_xlabel("candles", color=TEXT, fontsize=8)

        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf.getvalue()
    except Exception as exc:  # charts must never break signal delivery
        log.warning("chart render failed: %s", exc)
        return None


def render_result_chart(
    candles: list[Candle],
    *,
    symbol: str,
    direction: str,
    entry: float,
    exit_price: float | None,
    result: str,
) -> bytes | None:
    try:
        df = to_frame(candles)
        if len(df) < 10:
            return None
        df = df.tail(60).reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(9, 4.6), dpi=130)
        _style(fig, ax)
        ax.plot(df.index, df["close"], color=ACCENT, linewidth=1.2, label="Close")
        ax.fill_between(df.index, df["close"].min(), df["close"], color=ACCENT, alpha=0.08)
        ax.axhline(entry, color="#facc15", linestyle="--", linewidth=1.0)
        ax.annotate(f"ENTRY {entry}", (0, entry), color="#facc15", fontsize=8, va="bottom")
        if exit_price:
            ax.scatter([df.index[-1]], [exit_price], color=UP if result == "WIN" else DOWN, s=45, zorder=5)
            ax.annotate(f"EXIT {exit_price}", (df.index[-1], exit_price),
                        color=UP if result == "WIN" else DOWN, fontsize=8, ha="right", va="bottom")
        color = UP if result == "WIN" else (DOWN if result == "LOSS" else TEXT)
        ax.set_title(f"{symbol}  {direction}  →  {result}", color=color, fontsize=12, loc="left", pad=8)
        ax.set_ylabel("Price", color=TEXT, fontsize=8)
        ax.set_xlabel("candles", color=TEXT, fontsize=8)

        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf.getvalue()
    except Exception as exc:
        log.warning("result chart render failed: %s", exc)
        return None


def _style(fig, ax) -> None:
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    ax.grid(True, color=GRID, linewidth=0.5, alpha=0.6)
    ax.tick_params(colors=TEXT, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.xaxis.set_major_locator(MaxNLocator(6))
