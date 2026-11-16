# SMARTY next-candle replay

We tested a fixed trend/range/volatility candidate using MA200, Alligator,
ATR, candle body and liquidity sweeps. It was **not promoted to a live
direction rule**. Market-state diagnostics and target-time corrections do
not depend on approval of the candidate.

Source: ExpertOption bridge history for SMARTY (240), ending November 16,
2026 at about 15:27 UTC. 1,500 closed bars per timeframe. The final 900
target candles per timeframe were used for this comparison. Results are
per signal, including flat outcomes in the denominator. No market payout
or account execution is modeled.

| Timeframe | Candidate correct / signals | Candidate hit rate | Existing LO rule hit rate |
|---|---:|---:|---:|
| 5 seconds | 37 / 72 | 51.39% | 47.77% |
| 15 seconds | 30 / 73 | 41.10% | 46.65% |
| 30 seconds | 28 / 64 | 43.75% | 49.07% |
| 1 minute | 28 / 79 | 35.44% | 46.36% |

The 5-second candidate tied the constant-direction comparison on the same
72 timestamps and was too sparse to establish an improvement. The other
three frames did not improve on the existing LO rule overall. Neither the
old nor the new rule was demonstrated to be profitable here. The frames
overlap in time and are not independent samples.

Both rules were scored after candle i closed, during formation of i+1, for
the next still-future candle i+2. Historical replay checks direction
against i+2 open-to-close. It does not reproduce live provider latency or
quotes. This timing differs from the original calibration's i+1 replay,
so the old historical calibration should not be presented as evidence of
the experimental rule's accuracy or reused to certify a new SMARTY frame.

To reproduce with exported history responses for 5sec, 15sec, 30sec and
1min, run `python -m scripts.replay_smarty_regime INPUT --output report.json`.
The candidate is evaluated only on contiguous candle sequences.
