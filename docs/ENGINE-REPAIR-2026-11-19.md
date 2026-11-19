# NEXUS AI signal engine audit — 2026-11-19

## Findings

- Live analysis built indicators from closed candles but built its calibrated forecast from the unfiltered provider frame. A still-forming candle could therefore change the prediction before it closed.
- The backtester passed a candle's opening timestamp as decision time even though its full OHLC was already present. This let the forecast path see information that a live decision at that timestamp could not know.
- The live target could be one or two bars beyond the last closed feature candle, while the saved calibration described only the next candle. Calibration also lacked expiry metadata, although the selected trade expiry could differ from the candle horizon.
- Walk-forward calibration added target results before their target candles had closed. Its confidence bins were then fit on all samples, including samples used for the displayed out-of-sample score.
- The history script trusted a response without checking asset, market, timeframe, connection, or active status. This can mislabel a feed or calibrate a market that the bot cannot trade.
- The prior gate accepted a 53% hit rate with 100 signals. At an 80% binary-option payout, break-even before extra costs is 55.56%; a hit rate above break-even alone still does not establish an edge.

## Changes

- Forecast features now use closed candles only. The target lead is computed from the next executable candle, and calibrated forecasts must match both lead and expiry.
- Signal generation resolves an omitted expiry before analysis, using the supported expiry closest to the selected candle timeframe. Explicit, unmatched expiries fail closed.
- The backtester makes a historical bar available at its close, enters at a later candle open, settles at the last close no later than expiry, and reports net return using a configurable payout ratio and per-trade cost.
- Walk-forward training now waits until each target has closed, groups simultaneous asset timestamps, and builds runtime confidence bins only from out-of-sample predictions.
- Calibration is enabled only with at least 100 out-of-sample signals and a 95% Wilson lower bound above payout-adjusted break-even. The checked-in version 1 calibration lacked lead, expiry, and payout evidence; it has been replaced by version 2 tables from the currently verifiable data. No measured table passed the gate, so strong mode correctly emits no calibrated trades for those combinations.
- The history fetch now rejects inactive, disconnected, wrong-market, wrong-symbol, wrong-timeframe, invalid, or stale data.

## Measured results

The read-only ExpertOption history run fetched 1,500 candles per accepted asset/frame on 2026-11-19. It produced 26 market/frame/lead combinations from five currently active market groups: AI, Football, Forex (EUR/USD only), Luxury, and SMARTY. OTC, Cricket, Gold, and inactive Forex pairs were excluded by the feed metadata. The run covered 1, 5, and 15 minute candles and one- and two-bar leads; it does not represent unavailable markets, inactive assets, other expiry lengths, or 30 minute/1 hour frames.

The legacy expanding rule produced directional calls in the tested combinations. At an assumed 80% payout, 25 of 26 combinations had negative net EV before extra costs. Forex 1 minute with a one-bar lead was barely positive at +0.0011 per unit stake, but its 95% Wilson lower hit-rate bound was only 48.77%, well below 55.56% break-even. Under the corrected payout-aware, per-score-bucket 95% Wilson gate, no combination produced an accepted trade. A hit rate or EV for zero accepted trades is undefined, so the corrected report marks those fields as unavailable rather than calling them 0%. No calibration table is enabled.

The detailed before/after replay uses the same fetched candles for both methods. “Before” reproduces the prior walk-forward update rule without target-maturity purging or payout-aware bucket gating; “corrected” waits for target closes, prevents same-timestamp peer leakage, and requires the selected score bucket's lower confidence bound to clear break-even. These are candle-direction results, not a promise of executable broker fills. Legacy EV assumes 80% payout, zero additional fees, and zero-return draws, so it is optimistic when real execution has added costs.

See [full Walk-Forward results](NEXUS-AI-WALK-FORWARD-2026-11-19.md) and the machine-readable [run output](NEXUS-AI-WALK-FORWARD-2026-11-19.json).

## Verification

- Before changes: 381 passed, 3 skipped.
- After changes: 390 passed, 3 skipped.
- `python -m compileall -q engines scripts tests` completed successfully.
- No Railway deployment was performed.

## Operational note

Since no measured combination clears the payout-adjusted confidence gate, the correct current result is no calibrated trade. New data can be collected with `python -m scripts.backtest_next_candle --frames 1min,5min,15min --horizon-bars 1 2`. Re-enable a combination only after its fresh out-of-sample lower bound exceeds the configured payout break-even rate.
