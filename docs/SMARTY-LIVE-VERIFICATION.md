# SMARTY — Live ExpertOption verification

Verified against the deployed bridge `https://worker-production-03c94.up.railway.app`
with the account token already stored in Railway (`EO_TOKEN`). No mock data used.

## Root causes found in this round

1. **Binary frames were dropped.** The gateway answers in WebSocket BINARY frames
   (plain UTF-8 or zlib JSON), not TEXT. Every reply was ignored, so the socket
   stayed "connected" while no assets or candles ever arrived.
2. **Candle blocks carry their own timeframe.** `assetHistoryCandles` / `candles`
   arrive as `{"assetId": 240, "candles": [{"tf": 5, "periods": ...}]}`. The parser
   required a top-level `tf` and discarded every block.
3. **Partial asset pushes overwrote the catalog.** A later `assets` message with
   one symbol replaced the 149-instrument catalog; the catalog is now merged by id.
4. **Invalid attribute in the probe** (`instrument.expirations`) caused HTTP 500
   once candles parsed; expiries now come from the raw asset payload.

## Live evidence (2026-11-10)

```json
{
  "asset_id": 240, "symbol": "SMRTY", "name": "Smarty", "market": "smarty",
  "active": true,
  "expirations": {"step_seconds": 5, "count": 7, "max_seconds": 86400, "purchase_time": 5},
  "timeframes_tested": {
    "5":   {"candles": 60, "last_close": 257.969},
    "10":  {"candles": 60},
    "15":  {"candles": 60},
    "30":  {"candles": 60},
    "60":  {"candles": 60},
    "180": {"error": "EO_ERROR", "detail": "ERROR_INCORRECT_DATA"},
    "300": {"candles": 60},
    "900": {"candles": 60}
  },
  "candles": 120, "stale_seconds": 13.0, "duplicate_timestamps": 0,
  "future_candles": 0, "invalid_ohlc": 0
}
```

Supported SMARTY durations exposed in Telegram: **5s, 15s, 30s, 1m, 3m(180) is
rejected by ExpertOption, 5m**. 180s returns `ERROR_INCORRECT_DATA`, so it is not
shown and cannot be chosen.

## Real analysis over 120 live 5s candles

```
direction: UP   confidence: 92   price: 258.018
trend UP · momentum BULLISH · volatility NORMAL
RSI 64.97 · MACD hist +0.0009 · EMA9 258.0134 · EMA21 257.9992 · EMA50 257.9817
SMC: last event BOS bullish (index 114), 4 unfilled bullish FVGs, 2 demand order blocks,
liquidity sweeps recorded, zone PREMIUM
reasons: Bullish EMA stack / Bullish BOS / RSI momentum above 58 / Price above EMA 200 /
         MACD histogram positive / Unfilled bullish FVG nearby
candle validation: ok (120 bars, 13s old, no duplicates, no future bars, no invalid OHLC)
```

Analysis only runs on validated, fresh candles; stale or invalid input yields
`NO TRADE` / `SMARTY_UNAVAILABLE`, never a fabricated signal.

## Deployment

`main` auto-deploys the bridge service (`ROZLF-EO-BRIDGE`). Health includes the
deployed commit in `build`, plus redacted diagnostics (`assets_debug`,
`seen_actions`, `msg_shapes`) so future protocol drift is visible without secrets.
