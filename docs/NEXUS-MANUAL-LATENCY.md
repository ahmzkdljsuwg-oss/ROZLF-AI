# NEXUS manual Telegram analysis audit

The manual market flow now requests candles without waiting for a separate quote. SMARTY LO returns the first current, verified-source candle reading instead of serially trying alternative frames for an ineligible signal. The alternatives remain available when an earlier frame times out or is stale. LO/FAST history work has a 12-second budget, while deeper manual modes have 15 seconds. These budgets apply to collecting frame work, not to inventory or Telegram network time. Completed work is kept when another frame runs out of time. Fetches shared with another request are not cancelled when one user stops waiting. There is no change to the scanner or Mini App state.

Candle snapshots expire by the next expected close even when a source omits the currently forming candle. FAST and the manual live path use contiguous closed bars. The exact target for an analysis done during candle `i+1` is `i+2`, where candle `i` is the latest confirmed close. An old `i+1` calibration is not applied to `i+2` in manual strong modes. PRO also counts normalized strategy families, so correlated indicators in one family do not count as three separate confirmations. Different instruments cannot veto each other's analysis.

## Measured timing

Local replay of 300 rolling 300-bar windows from recorded ExpertOption SMARTY history, 50 windows per frame and mode. Direction, target time, support, resistance, directional evidence scores and PRO strategy readings matched on the compared runs. This is wall time for local analysis, not a promise of response time in Telegram.

| Frame/mode | Before median | After median |
| --- | ---: | ---: |
| 30 s / LO | 35.53 ms | 26.05 ms |
| 30 s / PRO | 58.22 ms | 39.41 ms |
| 1 min / LO | 35.03 ms | 29.40 ms |
| 1 min / PRO | 51.09 ms | 40.16 ms |
| 5 min / LO | 36.44 ms | 29.03 ms |
| 5 min / PRO | 52.06 ms | 37.90 ms |

A controlled scheduling test with 50 ms per source request, no actionable direction, and seven button taps per version used three history requests before and one after (median 151.29 ms vs 50.51 ms). An actual network bottleneck was visible on the previous deployment's health endpoint: the EO Bridge 128-sample rolling history latency was 428 ms median and 3,854 ms at p95. Only the request counts and local test results are attributed to this change.

## Fresh evidence check

`python -m scripts.audit_candle_strategies` was rerun using 19 November 2026 native SMARTY history from the read-only ExpertOption Bridge endpoint for asset 240. Across 5 s, 30 s, 1 min and 5 min, 3,592 target slots were eligible (including overlapping periods across intervals). None of the 12 rules or five family groupings beat both matching baselines in all three windows with sufficient samples. No strategy or confidence was promoted. The separate 2 min and 3 min frames were not part of this replay.
