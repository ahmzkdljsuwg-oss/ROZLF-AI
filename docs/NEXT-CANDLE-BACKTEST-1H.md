# Next-Candle Walk-Forward Backtest

Generated: `2026-11-16T06:28:38.157916+00:00`

Real ExpertOption OHLC from the read-only bridge. Every prediction uses bars `0..i`;
the target is bar `i+1`. Calibration is expanding and applied out of sample.

| Market / TF | Samples | Baseline UP | Combo walk-forward | Coverage |
|---|---:|---:|---:|---:|
| ai:1h | 1279 | 47.80% | 56.56% (181/320) | 25.0% |
| cricket:1h | 1279 | 51.84% | 56.25% (171/304) | 23.8% |
| football:1h | 1279 | 49.84% | 47.43% (120/253) | 19.8% |
| forex:1h | 3837 | 49.99% | 56.78% (670/1180) | 30.8% |
| gold:1h | 1279 | 45.23% | 59.11% (227/384) | 30.0% |
| luxury:1h | 1279 | 47.45% | 53.87% (202/375) | 29.3% |
| otc:1h | 3837 | 49.52% | 56.57% (650/1149) | 29.9% |
| smarty:1h | 1279 | 52.43% | 50.64% (199/393) | 30.7% |

## Strategy comparison (same samples)

| Market / TF | Trend | Momentum | Price action | Location | Combo raw |
|---|---:|---:|---:|---:|---:|
| ai:1h | 55.6%/906 | 53.1%/794 | 50.5%/862 | 54.6%/909 | 54.4%/879 |
| cricket:1h | 53.3%/1043 | 57.0%/903 | 55.6%/860 | 55.5%/854 | 56.0%/915 |
| football:1h | 53.6%/960 | 49.9%/795 | 51.4%/850 | 51.9%/799 | 51.8%/895 |
| forex:1h | 55.9%/2958 | 55.8%/2587 | 54.3%/2615 | 57.6%/2543 | 55.4%/2708 |
| gold:1h | 57.4%/1025 | 62.7%/952 | 61.2%/952 | 61.0%/923 | 60.6%/930 |
| luxury:1h | 56.0%/1019 | 55.6%/775 | 54.3%/871 | 55.5%/1002 | 56.2%/898 |
| otc:1h | 55.1%/2861 | 56.4%/2566 | 55.1%/2619 | 56.4%/2378 | 56.3%/2682 |
| smarty:1h | 51.7%/905 | 48.7%/746 | 49.4%/816 | 49.9%/685 | 51.3%/844 |

Hit rate is wins / verified signals (draws are not wins). Coverage is signals / samples.
