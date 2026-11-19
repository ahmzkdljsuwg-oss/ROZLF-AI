# Next-Candle Walk-Forward Backtest

Generated: `2026-11-19T20:45:40.376755+00:00`

Real OHLC from the read-only bridge. Features use closed bars through index `i`;
entry is at the target candle open and expiry is at that candle close. Walk-forward
calibration is fitted only on earlier timestamps, never peers at the same time.

| Market / TF / lead | Samples | Legacy hit | Legacy EV | Corrected hit | 95% lower | Corrected EV | Signals |
|---|---:|---:|---:|---:|---:|---:|---:|
| ai:15min:1 | 1279 | 52.16% | -0.051 | — (no trades) | 0.00% | — | 0 |
| ai:15min:2 | 1278 | 50.00% | -0.092 | — (no trades) | 0.00% | — | 0 |
| ai:5min:1 | 1279 | 50.40% | -0.082 | — (no trades) | 0.00% | — | 0 |
| ai:5min:2 | 1278 | 50.97% | -0.078 | — (no trades) | 0.00% | — | 0 |
| football:15min:1 | 1279 | 46.84% | -0.144 | — (no trades) | 0.00% | — | 0 |
| football:15min:2 | 1278 | 51.00% | -0.077 | — (no trades) | 0.00% | — | 0 |
| football:1min:1 | 1279 | 50.72% | -0.062 | — (no trades) | 0.00% | — | 0 |
| football:1min:2 | 1278 | 51.16% | -0.049 | — (no trades) | 0.00% | — | 0 |
| football:5min:1 | 1279 | 49.37% | -0.095 | — (no trades) | 0.00% | — | 0 |
| football:5min:2 | 1278 | 50.17% | -0.087 | — (no trades) | 0.00% | — | 0 |
| forex:15min:1 | 1279 | 49.85% | -0.094 | — (no trades) | 0.00% | — | 0 |
| forex:15min:2 | 1278 | 49.54% | -0.108 | — (no trades) | 0.00% | — | 0 |
| forex:1min:1 | 1279 | 54.02% | +0.001 | — (no trades) | 0.00% | — | 0 |
| forex:1min:2 | 1278 | 43.68% | -0.166 | — (no trades) | 0.00% | — | 0 |
| forex:5min:1 | 1279 | 47.24% | -0.139 | — (no trades) | 0.00% | — | 0 |
| forex:5min:2 | 1278 | 46.93% | -0.138 | — (no trades) | 0.00% | — | 0 |
| luxury:15min:1 | 1279 | 54.43% | -0.020 | — (no trades) | 0.00% | — | 0 |
| luxury:15min:2 | 1278 | 47.28% | -0.141 | — (no trades) | 0.00% | — | 0 |
| luxury:1min:1 | 1279 | 51.77% | -0.059 | — (no trades) | 0.00% | — | 0 |
| luxury:1min:2 | 1278 | 50.22% | -0.087 | — (no trades) | 0.00% | — | 0 |
| luxury:5min:1 | 1279 | 51.56% | -0.072 | — (no trades) | 0.00% | — | 0 |
| luxury:5min:2 | 1278 | 51.52% | -0.073 | — (no trades) | 0.00% | — | 0 |
| smarty:15min:1 | 1279 | 48.18% | -0.129 | — (no trades) | 0.00% | — | 0 |
| smarty:15min:2 | 1278 | 47.51% | -0.145 | — (no trades) | 0.00% | — | 0 |
| smarty:5min:1 | 1279 | 50.61% | -0.077 | — (no trades) | 0.00% | — | 0 |
| smarty:5min:2 | 1278 | 46.93% | -0.155 | — (no trades) | 0.00% | — | 0 |

## Full-sample strategy comparison (descriptive only)

| Market / TF | Trend | Momentum | Price action | Location | Combo raw |
|---|---:|---:|---:|---:|---:|
| ai:15min:1 | 51.5%/913 | 51.9%/783 | 50.7%/840 | 51.7%/789 | 52.3%/878 |
| ai:15min:2 | 51.2%/912 | 50.3%/782 | 49.7%/839 | 50.1%/788 | 51.5%/877 |
| ai:5min:1 | 51.2%/895 | 51.8%/778 | 49.9%/859 | 51.2%/789 | 51.4%/846 |
| ai:5min:2 | 51.3%/894 | 53.0%/777 | 53.3%/858 | 50.7%/789 | 52.0%/846 |
| football:15min:1 | 49.4%/941 | 49.9%/777 | 50.7%/809 | 48.9%/822 | 48.9%/865 |
| football:15min:2 | 49.4%/940 | 49.0%/776 | 48.4%/808 | 48.0%/821 | 48.7%/864 |
| football:1min:1 | 52.1%/905 | 49.4%/803 | 50.8%/871 | 50.9%/750 | 50.4%/863 |
| football:1min:2 | 51.2%/904 | 50.8%/803 | 48.6%/870 | 51.4%/749 | 51.2%/862 |
| football:5min:1 | 48.2%/821 | 49.5%/784 | 49.7%/825 | 49.2%/778 | 48.0%/834 |
| football:5min:2 | 47.8%/820 | 48.9%/783 | 50.0%/824 | 47.9%/777 | 48.4%/833 |
| forex:15min:1 | 50.6%/915 | 46.5%/759 | 48.6%/829 | 48.1%/696 | 49.4%/855 |
| forex:15min:2 | 51.1%/914 | 48.1%/759 | 49.3%/828 | 49.6%/696 | 50.5%/855 |
| forex:1min:1 | 48.7%/885 | 50.9%/814 | 49.2%/880 | 49.5%/719 | 48.8%/860 |
| forex:1min:2 | 48.9%/884 | 50.6%/814 | 49.5%/880 | 49.6%/719 | 49.4%/859 |
| forex:5min:1 | 47.8%/913 | 48.5%/765 | 48.6%/872 | 48.0%/682 | 48.1%/835 |
| forex:5min:2 | 47.4%/912 | 47.8%/765 | 50.3%/871 | 46.2%/682 | 49.2%/835 |
| luxury:15min:1 | 52.8%/862 | 52.3%/771 | 49.9%/869 | 52.9%/936 | 51.9%/863 |
| luxury:15min:2 | 53.2%/861 | 52.1%/771 | 49.6%/869 | 54.0%/935 | 52.5%/862 |
| luxury:1min:1 | 51.0%/844 | 49.3%/742 | 48.9%/861 | 50.0%/712 | 49.7%/849 |
| luxury:1min:2 | 50.9%/843 | 48.6%/742 | 47.1%/860 | 49.2%/712 | 49.2%/848 |
| luxury:5min:1 | 53.8%/1071 | 52.0%/754 | 52.3%/872 | 51.6%/852 | 53.0%/934 |
| luxury:5min:2 | 53.8%/1070 | 50.9%/754 | 49.5%/872 | 53.5%/852 | 51.9%/933 |
| smarty:15min:1 | 48.4%/866 | 48.5%/758 | 51.5%/835 | 48.6%/695 | 50.2%/848 |
| smarty:15min:2 | 48.3%/865 | 47.6%/757 | 47.2%/834 | 47.6%/695 | 47.2%/847 |
| smarty:5min:1 | 48.4%/865 | 48.5%/758 | 47.9%/800 | 47.4%/680 | 48.3%/842 |
| smarty:5min:2 | 48.9%/865 | 47.8%/758 | 49.3%/799 | 48.1%/680 | 49.1%/841 |

Net EV assumes the configured payout and costs; draws return zero. Enablement requires at least 100 out-of-sample signals and a 95% Wilson lower bound above break-even. Coverage is signals / samples.
