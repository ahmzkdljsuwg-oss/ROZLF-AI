# Next-Candle Walk-Forward Backtest

Generated: `2026-11-16T06:27:37.573671+00:00`

Real ExpertOption OHLC from the read-only bridge. Every prediction uses bars `0..i`;
the target is bar `i+1`. Calibration is expanding and applied out of sample.

| Market / TF | Samples | Baseline UP | Combo walk-forward | Coverage |
|---|---:|---:|---:|---:|
| ai:30min | 1279 | 46.19% | 53.23% (305/573) | 44.8% |
| cricket:30min | 1279 | 50.27% | 55.75% (160/287) | 22.4% |
| football:30min | 1279 | 50.20% | 52.00% (156/300) | 23.5% |
| forex:30min | 3837 | 51.21% | 56.62% (710/1254) | 32.7% |
| gold:30min | 1279 | 46.32% | 56.15% (219/390) | 30.5% |
| luxury:30min | 1279 | 51.13% | 52.21% (142/272) | 21.3% |
| otc:30min | 3837 | 49.19% | 52.35% (345/659) | 17.2% |
| smarty:30min | 1279 | 51.68% | 52.17% (132/253) | 19.8% |

## Strategy comparison (same samples)

| Market / TF | Trend | Momentum | Price action | Location | Combo raw |
|---|---:|---:|---:|---:|---:|
| ai:30min | 55.0%/944 | 54.2%/784 | 53.3%/863 | 55.5%/872 | 54.8%/889 |
| cricket:30min | 52.9%/1037 | 53.9%/841 | 55.9%/863 | 54.2%/886 | 54.4%/882 |
| football:30min | 53.3%/1003 | 52.5%/843 | 50.1%/833 | 52.4%/820 | 53.5%/896 |
| forex:30min | 55.8%/3020 | 55.1%/2522 | 53.5%/2572 | 56.7%/2559 | 56.0%/2711 |
| gold:30min | 55.6%/1024 | 56.8%/866 | 56.1%/920 | 56.8%/930 | 56.3%/918 |
| luxury:30min | 56.1%/910 | 54.6%/801 | 52.2%/891 | 56.6%/949 | 55.4%/877 |
| otc:30min | 55.1%/2798 | 55.0%/2505 | 54.5%/2601 | 55.5%/2393 | 55.0%/2651 |
| smarty:30min | 51.1%/893 | 49.8%/765 | 49.6%/832 | 49.1%/725 | 49.0%/851 |

Hit rate is wins / verified signals (draws are not wins). Coverage is signals / samples.
