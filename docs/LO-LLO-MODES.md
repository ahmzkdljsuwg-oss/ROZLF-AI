# NEXUS AI — LO / LLO modes

## Commands

- `/lo` — **LO MODE: ON**. Enables continuous technical recommendations for the
  current Telegram user only. Direction (`UP` / `DOWN`) is chosen when the
  independent technical components agree. The analyser bypasses the
  walk-forward calibration bucket, so confidence is shown as **UNVERIFIED**
  instead of a calibrated percentage.
- `/llo` — **STRONG ANALYSIS: ON**. Returns that user to the calibrated
  walk-forward engine. `UP` / `DOWN` is emitted only when the market and frame
  have a proven calibration table; otherwise the original `NO TRADE` gate applies.

The selected mode is stored in the `user_modes` table keyed by Telegram user ID.
It survives bot restarts and one user's choice never affects another user's.

## Analysis path

1. Telegram command or inline market button.
2. `_nexus_analyse` reads the stored mode from PostgreSQL/SQLite.
3. `MarketAnalysisService(mode=...)` passes `analysis_mode` to
   `analyze_market_data`.
4. **STRONG** requires a calibrated walk-forward bucket. **LO** uses the same
   real closed candles, trend, momentum, volatility and support/resistance
   evidence, but does not require calibration (`require_calibration=False`).
5. In LO mode the service evaluates the first three timeframe frames of the
   market profile instead of only calibrated frames.
6. Conflicting evidence or invalid data returns `NO TRADE` / `DATA UNAVAILABLE`.
   No synthetic or future candle is ever created.
7. Cards show `🧪 LO MODE · UNCALIBRATED` and `🎯 الثقة: UNVERIFIED` in LO mode.

## OTC / SMARTY asset selection

Pressing OTC or SMARTY now opens the live instrument list from the ExpertOption
bridge. Only rows with `active=true` and the matching `market` are offered.
The selected asset key is passed to the service, so no other instrument is
analysed and the chosen ID is the one used for candles. If discovery fails or no
active instrument exists, the bot replies `DATA UNAVAILABLE` and emits no signal.
The final card includes `💱 الأصل` with the real instrument name.

## Tests executed (this build)

```
.venv/bin/python -m pytest -q
383 passed, 3 skipped in 14.79s
```

Targeted LO/LLO tests: `tests/test_lo_mode.py` (6 passed):

1. `/lo` then SMARTY path with 5-second expiration card.
2. `/llo` then FOREX path, calibrated mode.
3. Per-user mode isolation and repository restart persistence.
4. LO engine returns UP/DOWN with `confidence_verified=False`.
5. STRONG engine returns `NO TRADE` without calibration.
6. Card displays `UNVERIFIED`, never an uncalibrated success percentage.

Additional OTC tests in `tests/test_nexus_telegram.py`: inactive and wrong-market
rows are excluded, and only the selected asset is analysed.

## Limits of this verification

- No Telegram network session was started because no bot token is present in
  this workspace. The command and callback handlers were exercised directly
  through aiogram-compatible message/callback objects up to the analysis service.
- No live ExpertOption bridge session was authenticated here, so live OTC/SMARTY
  candle availability is not claimed. When the bridge is authenticated, the same
  code path performs discovery and candle validation.
- Market data used in tests is synthetic test fixture data only. It is never
  returned to a Telegram user as a market recommendation.
