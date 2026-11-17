# NEXUS AI refresh

Scope is the original ROZLF-AI Telegram service and its same-origin Mini App. The separate trading project and the Railway ExpertOption worker and owner bot are not deployment targets. Nothing in this change places trades.

## Data and timing

Candle reads share in-flight work and a refresh-aware cache. The forecast path does not look up a price quote, FAST can complete before other assets do, and the scanner issues eligible readings as each source finishes. History requests are bounded, provider errors are isolated, and Twelve Data quota responses pause further upstream calls. The fallback checks the exact normal FOREX symbol and native frame and does not substitute OTC.

Fast readings are uncalibrated. PRO requires a table for the exact target timing, a strong reading supported by distinct families, and the configured confidence floor. The historical tables predate the next unopened target definition. LLO remains the legacy analysis mode. The replay script writes candidate calibration separately and excludes open, missing or incorrectly labeled native candles, including outcomes that had not settled at the time of the prediction. Re-run with supported read-only history and review results before enabling a new table.

The scanner is opt-in per user and its owner-only controls configure the shared instrument universe. Telegram alerts and stats only count acknowledgements before the target opens and verify the same source and candle after it closes. No alerts are manufactured to fill a quiet period.

## Interface and access

The same-origin Telegram Mini App uses the server-verified signed identity, preserves subscription checks, and reads markets, native OHLC, delivery history, directional performance, and user preferences from the backend. Market freshness is separate from process connectivity. The UI defaults to Arabic RTL, offers English, and respects reduced motion. Existing bots and activation flows are preserved.

## How to verify

- `python -m pytest -q`
- `node --check mini_app/static/app.js`
- `python scripts/verify_build.py`
- `python -m scripts.backtest_next_candle --market smarty --frames 5sec,30sec,1min` runs a real read-only replay and writes a candidate only if enough data is returned.
- `/health` exposes request-latency samples and process CPU/RSS. Separate provider latency from end-to-end analysis and compare on the same mix of assets and frames.
- In Telegram, use `/fast`, `/pro`, `/lo` or `/llo`, and toggle notifications from the scanner panel or Mini App settings. No Telegram token should be supplied to the browser.
