# Next-Candle Walk-Forward Backtest

Generated: `2026-11-16T06:24:54.895447+00:00`

Real ExpertOption OHLC from the read-only bridge. Every prediction uses bars `0..i`;
the target is bar `i+1`. Calibration is expanding and applied out of sample.

| Market / TF | Samples | Baseline UP | Combo walk-forward | Coverage |
|---|---:|---:|---:|---:|
| ai:15min | 1279 | 48.74% | 41.74% (96/230) | 18.0% |
| cricket:15min | 1279 | 49.02% | 49.01% (124/253) | 19.8% |
| football:15min | 1279 | 50.08% | 51.29% (179/349) | 27.3% |
| forex:15min | 3837 | 50.85% | 55.10% (519/942) | 24.6% |
| gold:15min | 1279 | 47.15% | 57.27% (256/447) | 35.0% |
| luxury:15min | 1279 | 50.16% | 48.59% (121/249) | 19.5% |
| otc:15min | 3837 | 49.61% | 54.60% (463/848) | 22.1% |
| smarty:15min | 1279 | 51.73% | 51.59% (179/347) | 27.1% |

## Strategy comparison (same samples)

| Market / TF | Trend | Momentum | Price action | Location | Combo raw |
|---|---:|---:|---:|---:|---:|
| ai:15min | 50.9%/943 | 50.5%/754 | 50.8%/819 | 51.5%/818 | 51.2%/881 |
| cricket:15min | 51.7%/923 | 53.3%/856 | 52.8%/803 | 50.9%/852 | 51.7%/865 |
| football:15min | 49.9%/901 | 50.3%/762 | 52.0%/795 | 50.5%/744 | 49.6%/852 |
| forex:15min | 57.0%/2988 | 55.2%/2467 | 53.7%/2654 | 57.2%/2467 | 56.5%/2699 |
| gold:15min | 55.8%/1026 | 60.5%/889 | 59.2%/951 | 60.4%/916 | 58.6%/913 |
| luxury:15min | 51.4%/872 | 51.7%/729 | 49.5%/861 | 51.8%/907 | 51.1%/830 |
| otc:15min | 56.0%/2971 | 56.5%/2534 | 56.1%/2633 | 57.3%/2444 | 57.2%/2698 |
| smarty:15min | 49.3%/848 | 48.0%/760 | 50.4%/833 | 47.9%/710 | 49.7%/847 |

Hit rate is wins / verified signals (draws are not wins). Coverage is signals / samples.
