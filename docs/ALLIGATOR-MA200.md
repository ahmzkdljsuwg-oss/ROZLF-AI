# ROZLF AI — Williams Alligator + MA 200 strategy

## Settings

| Component | Period | Offset |
| --- | --- | --- |
| Jaw | 13 | 8 |
| Teeth | 8 | 5 |
| Lips | 5 | 3 |
| MA 200 | 200 | — |

The moving average is the system's existing trend average type: **EMA 200**. The
result card states `MA 200: EMA 200` explicitly. Alligator lines are smoothed on
the candle median price `(high + low) / 2`, with the standard shifts above.

Implementation: `engines/strategies/alligator_ma.py`.

## Decision rules

1. Refuse to decide until at least **200 closed candles** exist.
2. EMA 200 direction: close above = UP, close below = DOWN.
3. Alligator awake:
   - bullish: `Lips > Teeth > Jaw` and jaw rising;
   - bearish: `Lips < Teeth < Jaw` and jaw falling;
   - otherwise the market is treated as ranging and the result is `NO TRADE`.
4. A gap of at least `3% ATR` is required between adjacent lines, so entangled
   lines never count as a trend.
5. Conflict between EMA 200 and the Alligator produces `NO TRADE`.
6. Entry requires the **last closed candle** to be a body-confirmed candle in
   the direction, with no opposite engulfing rejection. Price must remain on the
   correct side of the lips.
7. Every result lists cancellation/invalidation conditions.

No future candle is read: the frame passed to the evaluator contains closed
candles only, and the last index is the signal candle.

## Output

`BUY`, `SELL` or `NO TRADE` plus: MA 200 type/direction, Alligator state
(`AWAKE` / `SLEEPING`) and direction, trend strength, ADX, last price and time,
reasons and invalidation conditions. Rendered in the bot result card, analysis
details and the Mini App result card.

## Duplicate suppression

`AlligatorSignalGate` keys a signal by `asset + timeframe + signal candle time +
decision`. Repeated refreshes of the same closed candle cannot emit the same
signal twice. `TICK_SECONDS = 5` records the intended refresh cadence; the
evaluation itself runs on every analysis/refresh call. Because confirmation uses
closed candles, the actionable signal cannot change between two ticks of the
same candle.

## Historical test (real data)

Source: Yahoo Finance public 1-minute FX candles, 2026-11-09 → 2026-11-13,
evaluated every 5 bars after a 200-candle warm-up, outcome measured on the close
5 and 15 bars later. This is a mechanism test, not a profitability claim.

| Symbol | Bars | Signals | BUY | SELL | WIN 5 bar | LOSS 5 bar | DRAW 5 bar | WIN 15 bar | LOSS 15 bar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EUR/USD | 6,913 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GBP/USD | 6,914 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| USD/JPY | 6,913 | 196 | 129 | 67 | 89 | 104 | 3 | 90 | 106 |

EUR/USD and GBP/USD were ranging or conflicted for the whole window, so the
strategy correctly stayed out. USD/JPY produced 196 confirmed entries; the
short-horizon hit rate was about 45%, which is **not** evidence of an edge.
Spread, payout and commission are not modelled, and five days is far too short
for a conclusion.

## Live data check

On 2026-11-13 the strategy was run against live Yahoo 1-minute EUR/USD candles
(400 bars, last candle 51.6 s old at evaluation). It returned `NO TRADE` because
`EMA 200 = DOWN` while the Alligator was `SLEEPING`, and printed the real last
price/time. No fabricated quote was used.

## Verification

```
python -m pytest tests/test_alligator_ma.py -q   # 8 passed
python -m pytest -q                              # 221 passed, 3 skipped
```
