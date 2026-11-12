# ROZLF AI — Task E verification report

Scope: strengthen Forex/SMARTY analysis, add AI / Football / Luxury index markets,
add 45s and 105s expirations. Commit: `3628638`.

## What was proven against the live service

Bridge build `3628638`, `https://worker-production-03c94.up.railway.app`

| Asset | id | candles | freshness | last close | analysis |
|---|---|---|---|---|---|
| AI Index | 285 | 120 real 5s OHLC | 3.1s | 130.9766 | UP 77% |
| Football Index | 278 | 120 real 5s OHLC | 28.3s | 82.9149 | DOWN 77% |
| Luxury Index | 286 | 120 real 5s OHLC | 13.6s | 715.6992 | UP 84% |
| SMARTY | 240 | 200 real 5s OHLC | 14s | 258.272 | feed fresh, 503 earlier was a transient timeout |

`/health`: `connected=true`, `last_message_age_seconds` < 1s, `last_error=null`, 149 assets.

## Expiration support (from live raw asset payload)

Live instruments expose `expiration_step=5`, `expiration_max_seconds=86400`.
45 and 105 are multiples of the 5s step and inside the maximum, so they are
offered for ExpertOption markets. Older durations (5, 15, 30, 60, 120, 180,
300, 900, 1800, 3600) remain unchanged. Expiry duration is stored separately
from the candle timeframe used for analysis.

## Expiry timing

`SignalTracker.verify_due(now)` uses the server clock (`utc_now`) and stored
`expires_at`. New test `test_short_expiry_uses_server_clock` proves a 45s
signal is not resolved at +44s and resolves at +46s. WIN/LOSS/DRAW uses the
closing quote, its spread tolerance and its timestamp; unverifiable signals
remain UNVERIFIED and are excluded from accuracy.

## Analysis scoring

Evidence is now grouped into independent families (trend, momentum, MACD,
structure, location, confirmation). Each family contributes only its strongest
member, so correlated readouts cannot outvote each other. Confidence comes from
family separation + breadth across independent families, capped at 92%, with
NO TRADE when evidence conflicts or confidence is below threshold. It is an
indicator-concordance score, not a historical win-rate claim.

## Data integrity

* Only the most recently subscribed ExpertOption instrument keeps ticking; the
  bridge now backfills a frozen candle bucket from `assetHistoryCandles` instead
  of serving it as live data. This was observed live: AI/Football candles were
  4-5 minutes old while SMARTY was fresh.
* Index markets never borrow SMARTY or Forex data; unavailable data returns a
  reason and no signal.

## Tests

* Root suite: 89 passed, 3 skipped.
* Bridge suite: 21 passed.
* Mock tests are not presented as proof of live data; the table above is live.

## Not verified here

* Railway bot service deployment cannot be confirmed without a Railway token.
  The bridge redeployed automatically and reports build `3628638`.
* Forex live quotes depend on `TWELVE_DATA_API_KEY`; no new key was supplied.
