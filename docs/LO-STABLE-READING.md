# LO technical reading

The previous path could count candle body and close pressure from the same
candle as separate confirmations, and could skip a neutral preferred timeframe
to display a directional fallback. Some manual LO results were then stored as
signals despite being uncalibrated.

LO now uses the latest 200 valid contiguous completed candles. It requires a
consistent EMA 21/50 trend, movement over several closed candles, and agreement
in recent candle bodies; it stays neutral in ranges, abnormal volatility,
conflicts, gaps, or stale data. The preferred valid frame stays selected even
when neutral, and multiple asset responses are resolved in configured order.
LO reports a technical bias or the last completed candle without an entry
time, a confidence percentage, or a new signal record. Other modes and
existing signal records are unchanged.

## Historical behavior check

On 180 contiguous historical decision points per group, sampled from the
read-only 20 November bridge snapshots used by the strategy lab, the change
was more selective. Replay used identical 200-bar windows and compared
direction with the first unopened candle's eventual direction.

| Group | Old directional reads | New directional reads |
|---|---:|---:|
| SMARTY 30s | 90 | 20 |
| Football 1m | 104 | 14 |
| USDCAD OTC 1m | 105 | 32 |
| GBP/USD 1m | 93 | 24 |
| Total | 392 | 90 |

These are different subsets of a short historical sample. The new directional
reads matched 44 of 90 candle directions, versus 202 of 392 for the old path.
This is not evidence of better prediction accuracy or of any trading edge.
The change makes the reading stricter and separates observations from signals.
