# Next-Candle Walk-Forward Backtest

Generated: `2026-11-16T06:26:02.636437+00:00`

Real ExpertOption OHLC from the read-only bridge. Every prediction uses bars `0..i`;
the target is bar `i+1`. Calibration is expanding and applied out of sample.

| Market / TF | Samples | Baseline UP | Combo walk-forward | Coverage |
|---|---:|---:|---:|---:|
| ai:5min | 1279 | 49.16% | 48.89% (132/270) | 21.1% |
| cricket:5min | 1279 | 49.45% | 49.63% (203/409) | 32.0% |
| football:5min | 1279 | 51.03% | 52.43% (54/103) | 8.1% |
| forex:5min | 3837 | 48.48% | 50.83% (518/1019) | 26.6% |
| gold:5min | 1279 | 47.34% | 50.19% (271/540) | 42.2% |
| luxury:5min | 1279 | 52.04% | 54.73% (249/455) | 35.6% |
| otc:5min | 3837 | 48.87% | 50.00% (666/1332) | 34.7% |
| smarty:5min | 1279 | 52.00% | 49.38% (158/320) | 25.0% |

## Strategy comparison (same samples)

| Market / TF | Trend | Momentum | Price action | Location | Combo raw |
|---|---:|---:|---:|---:|---:|
| ai:5min | 49.8%/895 | 47.4%/740 | 46.6%/843 | 46.7%/717 | 48.0%/831 |
| cricket:5min | 52.4%/873 | 49.0%/798 | 48.7%/833 | 49.9%/763 | 49.8%/867 |
| football:5min | 51.7%/888 | 51.8%/807 | 51.1%/823 | 51.6%/792 | 51.8%/844 |
| forex:5min | 51.3%/2644 | 50.0%/2376 | 49.7%/2588 | 51.2%/2193 | 50.7%/2616 |
| gold:5min | 52.4%/912 | 51.0%/796 | 52.2%/878 | 54.9%/824 | 52.5%/873 |
| luxury:5min | 51.4%/832 | 51.4%/771 | 51.5%/845 | 51.7%/807 | 51.5%/847 |
| otc:5min | 50.4%/2685 | 48.9%/2311 | 48.4%/2486 | 48.5%/2180 | 49.3%/2566 |
| smarty:5min | 51.3%/952 | 48.4%/760 | 49.0%/818 | 48.7%/710 | 50.0%/864 |

Hit rate is wins / verified signals (draws are not wins). Coverage is signals / samples.
