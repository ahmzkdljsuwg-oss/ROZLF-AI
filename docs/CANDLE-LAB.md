# NEXUS candle lab and delivery timing audit

This changes the original ROZLF-AI bot and Mini App, not the automated execution project. It does not place orders or request unreleased data.

## SMARTY incident on November 18

Production recorded a five-second LO DOWN at 15:28:49.783 Kuwait, targeting 15:28:50–15:28:55. The broker screenshot showed a DOWN position open from 15:28:52 to 15:28:58, at 262.4630 and 262.4710 respectively. Thus the logged signal had 217 ms of lead, and the screenshot position was a different time window. No judgment about the exact original candle's direction is made from that screenshot.

## Changes

- Accept a candidate only with eight seconds before target open to publish and at least five seconds left when the Telegram update is acknowledged. The Mini App also rechecks the deadline on receipt and clears expired directions. Exact start and end are rendered in Kuwait time for accepted forecasts. The five-second frame is visible as a chart, not a manual target.
- A candle that could have been forming when the source request began is never promoted to a completed candle by a slow response. This cutoff also applies to registry freshness, cache lifetime and settlement.
- The chart inspector shows the actual closed OHLC, open/close times, body ratio, simple candle shape, and data gaps. These describe a completed candle and do not assert what follows it.
- SMARTY without independently validated timing-specific evidence is research only, including legacy and scanner paths. Other markets retain their existing modes. Account gates are unchanged.
- The replay compares fixed FAST, LO and agreement rules against a historical majority baseline on actual native SMARTY candles. It predicts the first unopened candle, i+2, without reading the intervening candle's OHLC. The last 600 targets per frame from the saved November 16 snapshot are chronological holdouts for these fixed comparisons, not new prospective trials or broker trade results. No tested method passes the conservative screen.

Reproduce from saved read-only source snapshots using their original metadata.

```bash
python -m scripts.audit_smarty_candles --data /path/to/market-replay --output /tmp/smarty-audit.json
```
