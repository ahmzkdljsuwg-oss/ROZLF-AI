# Next-Candle Walk-Forward Backtest

Generated: `2026-11-16T06:22:04.609437+00:00`

Real ExpertOption OHLC from the read-only bridge. Every prediction uses bars `0..i`;
the target is bar `i+1`. Calibration is expanding and applied out of sample.

| Market / TF | Samples | Baseline UP | Combo walk-forward | Coverage |
|---|---:|---:|---:|---:|
| ai:1min | 1279 | 48.23% | 51.02% (201/394) | 30.8% |
| cricket:1min | 1279 | 49.72% | 52.60% (152/289) | 22.6% |
| football:1min | 1279 | 51.38% | 47.49% (142/299) | 23.4% |
| forex:1min | 2830 | 49.84% | 47.39% (399/842) | 29.8% |
| gold:1min | 1279 | 47.34% | 52.33% (180/344) | 26.9% |
| luxury:1min | 1279 | 49.37% | 50.19% (135/269) | 21.0% |
| otc:1min | 3837 | 51.51% | 48.84% (483/989) | 25.8% |
| smarty:1min | 1279 | 50.43% | 37.59% (53/141) | 11.0% |

## Strategy comparison (same samples)

| Market / TF | Trend | Momentum | Price action | Location | Combo raw |
|---|---:|---:|---:|---:|---:|
| ai:1min | 50.5%/977 | 48.2%/767 | 48.5%/884 | 48.0%/684 | 48.9%/883 |
| cricket:1min | 48.0%/860 | 50.4%/756 | 51.7%/830 | 47.5%/684 | 49.0%/841 |
| football:1min | 47.7%/875 | 47.2%/798 | 45.1%/847 | 47.1%/730 | 46.1%/856 |
| forex:1min | 48.7%/2019 | 49.8%/1779 | 48.6%/1883 | 48.9%/1588 | 49.2%/1909 |
| gold:1min | 50.3%/873 | 50.1%/816 | 51.7%/842 | 52.1%/747 | 51.6%/884 |
| luxury:1min | 48.0%/859 | 51.0%/813 | 50.6%/840 | 52.0%/723 | 49.9%/857 |
| otc:1min | 48.1%/2658 | 47.5%/2355 | 48.4%/2554 | 47.2%/2099 | 47.8%/2596 |
| smarty:1min | 45.9%/811 | 45.1%/750 | 45.9%/855 | 44.7%/664 | 45.1%/815 |

Hit rate is wins / verified signals (draws are not wins). Coverage is signals / samples.
