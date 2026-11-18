# NEXUS PRO strategy lab

Twelve fixed research rules now use OHLC from the last closed native candle. They are grouped into trend, momentum, reversal, price structure and price action. The Telegram PRO result shows the five families, while the Mini App includes an expandable member-by-member breakdown. The actual production forecast, calibration file, minimum lead time and scanner are independent of the extra readings. No external model or new credential is needed for this feature.

PRO no longer joins old and fresh candles across a gap to get the 200-bar forecasting minimum. Missing and non-finite OHLC are not valid prices. Higher-frame trend evidence uses only complete 3× and 6× buckets and never treats unfinished or missing buckets as complete. Grouping correlated rules is for interpretation, not a claim that the families are statistically independent.

## Historical SMARTY check

`scripts/audit_candle_strategies.py` replays native ExpertOption Bridge snapshots for asset 240. The target is bar `i+2` and the strategy can only use prices through completed bar `i`. The first 40% supplies the initial comparison history and the rest is split into three chronological test windows. Before each test window, the majority comparator only sees target candles that were already closed. Both baselines are scored on the exact subset selected by each rule. A family that disagrees internally abstains. The detailed report records each immutable snapshot's hash and each tested window.

The four available intervals accounted for 3,590 eligible target candles, with overlap across intervals. The 30-second momentum rule matched 292/566 (51.59%), versus 279/566 for the past-majority baseline and 271/566 for last-candle direction. It was the only rule that beat both comparators in all three windows with 30 or more calls per window. That exploratory difference is not adequate for promotion, so no new rule drives an alert or a confidence percentage. Five seconds is chart-only for manual signals. The bridge returned HTTP 503 for the two- and three-minute replay requests, so those intervals were not tested. There are no replay results here for other assets.

Reproduce with saved native `/verify/history` exports named `5sec.json`, `30sec.json`, `1min.json`, `2min.json`, `3min.json` and `5min.json` as available:

```sh
python -m scripts.audit_candle_strategies /path/to/snapshots --output docs/SMARTY-STRATEGY-REPLAY.json
```
