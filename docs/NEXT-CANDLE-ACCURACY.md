# NEXUS AI — Next-Candle Accuracy by Market

Calibration generated: 2026-11-16T06:28:38.157916+00:00
Source: ExpertOption bridge /verify/history (real OHLC, read-only)
Method: expanding walk-forward; features use bars <= i, label is bar i+1 only

Gate: tradable only when walk-forward hit rate >= 53% and >= 100 signals. Everything else returns NO TRADE.

| Market | Frame | Samples | Baseline UP | Walk-forward | Signals | Coverage | Tradable |
|---|---|---:|---:|---:|---:|---:|---|
| ai | 15min | 1279 | 48.74% | 41.74% | 230 | 18.0% | NO |
| ai | 1h | 1279 | 47.80% | 56.56% | 320 | 25.0% | YES |
| ai | 1min | 1279 | 48.23% | 51.02% | 394 | 30.8% | NO |
| ai | 30min | 1279 | 46.19% | 53.23% | 573 | 44.8% | YES |
| ai | 5min | 1279 | 49.16% | 48.89% | 270 | 21.1% | NO |
| cricket | 15min | 1279 | 49.02% | 49.01% | 253 | 19.8% | NO |
| cricket | 1h | 1279 | 51.84% | 56.25% | 304 | 23.8% | YES |
| cricket | 1min | 1279 | 49.72% | 52.60% | 289 | 22.6% | NO |
| cricket | 30min | 1279 | 50.27% | 55.75% | 287 | 22.4% | YES |
| cricket | 5min | 1279 | 49.45% | 49.63% | 409 | 32.0% | NO |
| football | 15min | 1279 | 50.08% | 51.29% | 349 | 27.3% | NO |
| football | 1h | 1279 | 49.84% | 47.43% | 253 | 19.8% | NO |
| football | 1min | 1279 | 51.38% | 47.49% | 299 | 23.4% | NO |
| football | 30min | 1279 | 50.20% | 52.00% | 300 | 23.5% | NO |
| football | 5min | 1279 | 51.03% | 52.43% | 103 | 8.1% | NO |
| forex | 15min | 3837 | 50.85% | 55.10% | 942 | 24.6% | YES |
| forex | 1h | 3837 | 49.99% | 56.78% | 1180 | 30.8% | YES |
| forex | 1min | 2830 | 49.84% | 47.39% | 842 | 29.8% | NO |
| forex | 30min | 3837 | 51.21% | 56.62% | 1254 | 32.7% | YES |
| forex | 5min | 3837 | 48.48% | 50.83% | 1019 | 26.6% | NO |
| gold | 15min | 1279 | 47.15% | 57.27% | 447 | 35.0% | YES |
| gold | 1h | 1279 | 45.23% | 59.11% | 384 | 30.0% | YES |
| gold | 1min | 1279 | 47.34% | 52.33% | 344 | 26.9% | NO |
| gold | 30min | 1279 | 46.32% | 56.15% | 390 | 30.5% | YES |
| gold | 5min | 1279 | 47.34% | 50.19% | 540 | 42.2% | NO |
| luxury | 15min | 1279 | 50.16% | 48.59% | 249 | 19.5% | NO |
| luxury | 1h | 1279 | 47.45% | 53.87% | 375 | 29.3% | YES |
| luxury | 1min | 1279 | 49.37% | 50.19% | 269 | 21.0% | NO |
| luxury | 30min | 1279 | 51.13% | 52.21% | 272 | 21.3% | NO |
| luxury | 5min | 1279 | 52.04% | 54.73% | 455 | 35.6% | YES |
| otc | 15min | 3837 | 49.61% | 54.60% | 848 | 22.1% | YES |
| otc | 1h | 3837 | 49.52% | 56.57% | 1149 | 29.9% | YES |
| otc | 1min | 3837 | 51.51% | 48.84% | 989 | 25.8% | NO |
| otc | 30min | 3837 | 49.19% | 52.35% | 659 | 17.2% | NO |
| otc | 5min | 3837 | 48.87% | 50.00% | 1332 | 34.7% | NO |
| smarty | 15min | 1279 | 51.73% | 51.59% | 347 | 27.1% | NO |
| smarty | 1h | 1279 | 52.43% | 50.64% | 393 | 30.7% | NO |
| smarty | 1min | 1279 | 50.43% | 37.59% | 141 | 11.0% | NO |
| smarty | 30min | 1279 | 51.68% | 52.17% | 253 | 19.8% | NO |
| smarty | 5min | 1279 | 52.00% | 49.38% | 320 | 25.0% | NO |

## Markets without a proven edge

- **ai**: NO TRADE on 15min, 1min, 5min
- **cricket**: NO TRADE on 15min, 1min, 5min
- **football**: NO TRADE on 15min, 1h, 1min, 30min, 5min
- **forex**: NO TRADE on 1min, 5min
- **gold**: NO TRADE on 1min, 5min
- **luxury**: NO TRADE on 15min, 1min, 30min
- **otc**: NO TRADE on 1min, 30min, 5min
- **smarty**: NO TRADE on 15min, 1h, 1min, 30min, 5min

## Honest limits

- 30sec, 15sec and 5sec frames have no walk-forward calibration, so the engine returns NO TRADE.
- 1min is below the gate for every market.
- Football and Smarty have no proven frame at all.
- OTC walk-forward numbers use bridge `/verify/history` candles tagged `market: forex` and `active: false`; the production provider rejects that mismatch, so OTC returns DATA UNAVAILABLE until the bridge returns active, correctly tagged OTC candles.
- Rates are walk-forward with no future data: features use bars <= i and the label is bar i+1.
