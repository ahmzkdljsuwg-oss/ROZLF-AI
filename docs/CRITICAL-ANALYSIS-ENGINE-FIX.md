# ROZLF AI — Critical Analysis Engine Fix (Event 45)

## 1. Real cause of NO TRADE

Diagnosis was made from `engines/technical/evidence.py`, `engines/technical/analyzer.py`,
`engines/signals/generator.py` and live bridge output, not from assumptions.

| # | Condition | Effect before | Fix |
|---|-----------|---------------|-----|
| 1 | Higher-timeframe (HTF) disagreement was a hard blocker | A 30–60 s expiry was refused because 5 m/15 m frames disagreed, although the entry is decided on the base frame | HTF disagreement is now a warning when expiry ≤ 60 s or a fresh trigger exists |
| 2 | No ExpertOption-native strategy could act as a trigger | ADX < 13 blocked every quiet ExpertOption market | Added the 8 ExpertOption strategies to `TRIGGER_STRATEGIES` |
| 3 | Level-proximity blocker fired too early | Price within 0.30–0.50 ATR of a level was rejected | Threshold tightened to `max(0.08, level_distance_atr * 0.25)`; the condition remains |
| 4 | Duration/frame mapping mismatch | Engine advertised 5/15/45/105 s frames while the UI offers 30/60/120/180/300 s | `supported_durations()` returns exactly `[30, 60, 120, 180, 300]`; `smarty_timeframe()` maps those to real candle frames |
| 5 | Backtest ignored trade duration | Historical evaluation used the default expiry, not the requested one | `run_backtest` now passes `duration_seconds` into the analyzer |
| 6 | Chosen duration was not reflected in the result | `suggested_expiry_seconds` came only from the volatility profile | Analyzer uses the user-chosen duration when supplied |

Rejection reasons are now logged (`ROZLF DECISION ...`) and translated to Arabic, so
every NO TRADE has a visible cause.

## 2. ExpertOption strategies actually verified and wired

Source: ExpertOption's own education/tools set. Implemented in
`engines/strategies/expertoption.py` and aggregated once per bar, each strategy
emits at most one signal so correlated readouts are not double counted.

- Alligator (jaw 13/8, teeth 8/5, lips 5/3)
- Parabolic SAR (0.02 step, 0.2 maximum)
- Aroon (14)
- Fractals (5-bar)
- Tweezers (top/bottom)
- Three Methods (rising/falling)
- V-Bounce
- RSI + MACD Reversal
- Existing base: EMA 9/21/50/200, RSI, MACD, Bollinger, ATR, Stochastic, ADX, S/R, SMC/ICT (BOS, CHoCH, FVG, OB, liquidity sweeps), price action, MTF.

Not added because they are not verifiable as native ExpertOption tools in this
project: external platform strategies, order-flow tools, proprietary signals.
Martingale is **not** used for direction or confidence.

## 3. Backtesting on real bridge candles

Data: 1 500 real candles per market/frame from the ExpertOption bridge
(`/tmp/market_histories.json`, 2026-11-07 → 2026-11-12). Causal runner: decision
sees only closed candles, entry at next bar close, settlement at the first candle
closed at/after `entry_time + expiry_seconds`. No look-ahead. Losses are kept.

Backtest step = 3 bars (Cricket step = 5). Every market, every supported duration:

| Market | Duration | Trades | W | L | D | Win rate | Profit factor | Expectancy | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SMARTY | 30 s | 336 | 161 | 167 | 8 | 49.09% | 0.96 | -0.018 | — |
| SMARTY | 60 s | 351 | 189 | 158 | 4 | 54.47% | 1.20 | +0.088 | — |
| SMARTY | 120 s | 352 | 180 | 168 | 4 | 51.72% | 1.07 | +0.034 | — |
| SMARTY | 180 s | 352 | 176 | 172 | 4 | 50.57% | 1.02 | +0.011 | — |
| SMARTY | 300 s | 299 | 150 | 148 | 1 | 50.34% | 1.01 | +0.007 | — |
| FOOTBALL | 30 s | 339 | 148 | 177 | 14 | 45.54% | 0.84 | -0.086 | — |
| FOOTBALL | 60 s | 326 | 153 | 166 | 7 | 47.96% | 0.92 | -0.040 | — |
| FOOTBALL | 120 s | 326 | 157 | 163 | 6 | 49.06% | 0.96 | -0.018 | — |
| FOOTBALL | 180 s | 326 | 159 | 164 | 3 | 49.23% | 0.97 | -0.015 | — |
| FOOTBALL | 300 s | 311 | 144 | 162 | 5 | 47.06% | 0.89 | -0.058 | — |
| LUXURY | 30 s | 301 | 143 | 154 | 4 | 48.15% | 0.93 | -0.037 | — |
| LUXURY | 60 s | 307 | 150 | 153 | 4 | 49.50% | 0.98 | -0.010 | — |
| LUXURY | 120 s | 309 | 150 | 155 | 4 | 49.18% | 0.97 | -0.016 | — |
| LUXURY | 180 s | 309 | 155 | 153 | 1 | 50.32% | 1.01 | +0.006 | — |
| LUXURY | 300 s | 247 | 116 | 131 | 0 | 46.96% | 0.89 | -0.061 | — |
| AI | 30 s | 177 | 85 | 82 | 10 | 50.90% | 1.04 | +0.017 | 10.0 |
| AI | 60 s | 24 | 11 | 11 | 2 | 50.00% | 1.00 | 0.000 | 4.0 |
| AI | 120 s | 24 | 15 | 9 | 0 | 62.50% | 1.67 | +0.250 | 2.0 |
| AI | 180 s | 24 | 18 | 6 | 0 | 75.00% | 3.00 | +0.500 | 2.0 |
| AI | 300 s | 155 | 75 | 79 | 1 | 48.70% | 0.95 | -0.026 | 15.0 |
| CRICKET | 30 s | 192 | 87 | 100 | 5 | 46.52% | 0.87 | -0.068 | 31.0 |
| CRICKET | 60 s | 176 | 99 | 74 | 3 | 57.23% | 1.34 | +0.142 | 5.0 |
| CRICKET | 120 s | 177 | 95 | 80 | 2 | 54.29% | 1.19 | +0.085 | 9.0 |
| CRICKET | 180 s | 177 | 100 | 76 | 1 | 56.82% | 1.32 | +0.136 | 9.0 |
| CRICKET | 300 s | 145 | 70 | 73 | 2 | 48.95% | 0.96 | -0.021 | 14.0 |

Small-sample warning: AI 60/120/180 s have 24 trades only. They are **not**
evidence of profitability. The full-period numbers show the engine is close to a
coin flip on most markets; this is reported instead of hidden. No percentage is
presented as win probability.

Backtest-versus-tuning separation: strategy rules and thresholds were set from
ExpertOption documentation, not fitted to these candles. A walk-forward helper
exists (`engines/backtest/runner.py::walk_forward`); a full independent
out-of-sample run still needs a newer capture window.

## 4. Live bridge proof

Re-run against the real bridge on 2026-11-12:

```
SMARTY d=30 tf=30 -> DOWN conf=57.5 ev=63.0 fam=6 opp=4
FOOTBALL d=30 tf=30 -> DOWN conf=68.3 ev=85.1 fam=6 opp=4
FOOTBALL d=60 tf=60 -> UP   conf=57.5 ev=59.0 fam=6 opp=4
SMARTY d=60/120/180 -> NO TRADE (signals conflict, directional edge 51%)
```

These are real candles and real indicator calculations, not mock data.

## 5. What remains unavailable

- No free, documented ExpertOption Smarty/OTC source exists in the researched
  repositories that can be proven to serve those markets. OTC and GOLD stay out
  of scope and are never fed Forex data.
- Micro-expiries below 30 s are not offered by the UI; the bridge probe returns
  `DISCONNECTED` for 15/30/60/180/300/900 s on asset 240, so signals use the
  supported 30/60/120/180/300 s set only.
- Metrics above are backtest results, not live account results.

## 6. Tests

`176 passed, 3 skipped` (`.venv/bin/python -m pytest -q`), including new tests for
Alligator, Parabolic SAR, Aroon and the ExpertOption aggregator, Arabic card
templates, duration lists and the backtester duration fix.
