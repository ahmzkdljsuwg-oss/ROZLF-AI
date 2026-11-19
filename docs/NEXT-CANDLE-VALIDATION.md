# Next-candle research validation

The Telegram branch targets the first unopened candle, i+2, after using the
completed candles through i. Its old production calibration predates that
target. This change updates the **research replay only**. It does not promote
a calibration, change Telegram controls or trade.

## Reproduce the replay

```sh
python -m scripts.backtest_next_candle --market smarty --frames 5sec,30sec,1min \
  --output /tmp/nexus-replay/report.json --calibration /tmp/nexus-replay/candidate.json
```

For a fixed input, save the bridge's unmodified /verify/history JSON files as
`ASSET_ID-FRAME.json` (for example `240-1min.json`) and add
`--snapshot-dir PATH --as-of TIMESTAMP`, using the report's timezone-aware
`as_of` timestamp. The report includes SHA-256 hashes of snapshots, so
repeat runs can check that the input did not change.

## What the numbers mean

- Native candles must match the requested market, instrument ID and timeframe.
  Only closed, valid contiguous candles are used. The latest 299 usable feature
  candles approximate the live 300-row history request with a forming bar.
- Opposite directions no longer share a score bucket. Assets and timeframes
  never share samples. Outcome labels enter training only after their candles
  close and strictly before the forecast time.
- The actual replay outcome is the target candle's close versus its open.
  Always-UP, always-DOWN, past majority and previous candle are evaluated on
  the very same targets selected by the forecasts. Draws are misses for all
  directional methods. The Brier score measures probability error on all rows
  that had enough prior information for a probability, including abstentions.
- A 52% screen is retained for research comparability. It is not a
  profitability threshold, significance test, or basis for making a forecast
  actionable. The shorter frames do not gain eligibility to publish signals.
- This is an exploratory candle replay, not prospective validation of the full
  Telegram decision flow. It has no measured delivery latency, entry or
  settlement prices, payout history, or proof of a tradable edge. The research
  candidate format cannot enable live markets.

## SMARTY replay on 19 November 2026

Read-only source snapshots for instrument 240 returned 1,500 native candles
per frame and 1,279 usable targets per frame after warmup. Cutoff
`2026-11-19T18:55:11.951019+00:00`.

| Frame | Selected targets | Replay hit rate | Best matched baseline |
|---|---:|---:|---:|
| 5 seconds | 228 | 48.25% | 48.68% (previous candle) |
| 30 seconds | 200 | 47.50% | 51.50% (previous candle) |
| 1 minute | 266 | 49.25% | 49.62% (always UP / past majority) |

This run did not outperform the strongest matching baseline on any frame.
The snapshots are time-adjacent and the frame runs are not independent
replications. No frame was enabled or promoted as a result.
