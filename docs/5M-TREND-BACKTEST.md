# ROZLF AI — 5-MINUTE TREND MODE: HISTORICAL CHECK

## What was tested

The 5-minute trend mode (`engines/technical/trend5m.py`) was run walk-forward on
**separate real historical data that was not used for tuning**:

- Source: Yahoo Finance public FX chart endpoint (`providers/yahoo.py`), 1-minute bars.
- Window: 2026-11-09 00:00 UTC → 2026-11-13 ~14:45 UTC (five trading days).
- Pairs: EUR/USD, GBP/USD, USD/JPY.
- Method: at each sampled closed candle the engine received only the preceding
  candles, with `now` set to that candle's close time. No future candle was
  visible to the engine. A signal was scored against the market close exactly
  5 minutes later (5 × 1-minute bars).
- Sampling: every 5th bar for EUR/USD and GBP/USD, every 10th bar for USD/JPY
  (non-overlapping trade outcomes).
- The fixed duration was always 300 seconds. No duration substitution was allowed.

## Results

| Pair | Bars | Setups evaluated | Signals | WIN | LOSS | DRAW | NO TRADE | Avg confidence | Win rate (WIN/(WIN+LOSS)) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EUR/USD | 6,635 | 1,274 | 124 | 42 | 49 | 33 | 1,150 | 83.3% | 46.2% |
| GBP/USD | 6,640 | 1,275 | 85 | 31 | 50 | 4 | 1,190 | 82.3% | 38.3% |
| USD/JPY | 6,647 | 639 | 18 | 9 | 9 | 0 | 621 | 81.5% | 50.0% |

Errors during evaluation: 0.

## Reading the results

- The mode is deliberately selective: it returned NO TRADE in roughly 90–97% of
  evaluated setups. That is the intended safety behaviour, not a failure.
- On this short sample the raw win rate was **below 50% on two of three pairs**.
  The signal confidence value is **not** a probability of winning, and these
  results must not be presented as proof of profitability.
- DRAW outcomes are treated as neither WIN nor LOSS and are excluded from the
  win-rate denominator, matching how the production signal tracker verifies
  results.

## Limits of this check

- Only five trading days of 1-minute data were available from this keyless source.
- Yahoo FX quotes are delayed and are not ExpertOption/Smarty/OTC quotes; this
  test covers the FOREX path only and says nothing about the other five markets.
- Spread, commission and broker payout were not modelled.
- No parameter was tuned on this window. The parameters were fixed before this
  run on a synthetic fixture used only for unit tests.
- A larger independent sample (several weeks/months, including different
  volatility regimes) is required before any performance claim.

## Reproduction

```bash
PYTHONPATH=. python -m pytest tests/test_trend5m.py -q
```

The walk-forward script is intentionally kept outside the repository so test data
cannot be confused with production data; the method is recorded above.
