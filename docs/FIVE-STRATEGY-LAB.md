# Five-strategy candle research lab

This module and CLI are offline only. They do not modify Telegram, its
confidence display, active calibration, subscriptions, or deployment settings.

## Fixed hypotheses

| Rule | Closed-candle criteria |
|---|---|
| EMA 9/21/200 | New 9/21 cross with the closing price on the matching side of EMA 200. |
| Bollinger + RSI | Previous close outside the 20-bar, two-standard-deviation band with RSI 14 at 30/70 or beyond. The next bar must close back inside in the predicted direction. |
| Alligator + MA 200 | Causally shifted 13/8/5 smoothed median-price lines in order, expanding spread of at least 0.10 ATR, and close on the matching side of SMA 200. |
| Breakout + Retest | Close clears the prior 20-bar high/low by 0.10 ATR. Freeze the level and require a confirming retest within five later candles and within 0.15 ATR on the approach. |
| ATR regime | Use relative ATR and a shock filter to abstain in abnormal volatility. With ATR at 0.65–1.60 of its previous 60-bar median, use the EMA rule in an efficient trend or the Bollinger rule in a range, and abstain between regimes. |

ATR is the 14-bar mean of true range. The ATR regime is a selector for two
existing rules, not another independent vote. No parameters are fitted in the
report; the rule definitions are fixed. Gaps and invalid bars reset warmup.

The simulator observes closed candles through \(i\), then evaluates the
direction of candle \(i+2\). It excludes unclosed targets and gaps, uses 220
closed bars as common warmup, and reports three consecutive evaluation folds.
Each rule's baselines use exactly that rule's selected targets. The previous
closed candle, past majority, always-UP and always-DOWN are included. Majority
uses only outcomes strictly prior to the decision time.

## Run the replay

Save unmodified, read-only bridge history envelopes as `ASSET_ID-FRAME.json`.
Market, instrument ID and symbol, native timeframe, active state and bridge
connection must all match. The JSON report includes snapshot hashes, exact
cutoffs, unavailable combinations and matched baseline counts.

```sh
python -m scripts.replay_five_strategies /path/to/snapshots \
  --as-of 2026-11-20T04:40:00Z --evaluate-from 2026-11-19T20:50:08Z \
  --frames 30sec,1min,5min \
  --market smarty --market football --market luxury --market ai \
  --market cricket --market forex --market otc \
  --output /tmp/nexus-strategy-lab/replay.json
```

Use `--market smarty --frames 5sec` for the separate 5s measurement. Use
`--payout` and `--cost` to change the **hypothetical** return scenario. A draw
returns zero before cost and is not a directional hit. There are no real
entry/settlement prices, observed payouts, or measured Telegram delivery times.

## 20 November 2026 study

Captured up to 1,500 native candles per combination. At 30s, 1m and 5m the
report includes 25 usable instrument/timeframe combinations across six markets:
SMARTY, Football, Luxury, AI, Forex and OTC. Eight combinations provided no
eligible source envelope, including every Cricket request and every EUR/USD
request. Forex coverage comes from GBP/USD and USD/JPY, not an OTC substitution.
A separate read-only 5s SMARTY snapshot was also evaluated.

The following are descriptive aggregates of the later slice defined by the
command above. Instrument and timeframe observations overlap and are not
independent. Aggregate rates are not a head-to-head comparison because the
rules select different targets; comparisons with baselines use identical rows.

| Strategy | Selected targets | Correct direction |
|---|---:|---:|
| EMA 9/21/200 | 271 | 45.76% |
| Bollinger + RSI | 184 | 45.11% |
| Alligator + MA 200 | 4,271 | 49.52% |
| Breakout + Retest | 290 | 48.62% |
| ATR regime | 29 | 48.28% |

Alligator + MA 200 on USDCAD OTC 1m gave 92/165 correct, versus 84/165 for
the best matched aggregate baseline, and equaled or exceeded the strongest
baseline in each of three folds (two ties). NZDUSD OTC 1m gave 69/124, versus
67/124 for the best matched aggregate baseline, but lost one fold. At assumed
80% payout and no cost their scenario returns were +0.015758 and +0.009677 per
forecast. An illustrative cost of 0.02 per unit turns both negative.
SMARTY 5s yielded no robust evidence. Its largest rule sample was 293
(Alligator, 149 correct) and high percentages from some other rules were based
on only 14–15 selected candles. The 5s frame is too short for the existing
manual publication window.

These are historical, descriptive results from a short later window, not a
prospective holdout or proof of profitability. None was activated.
