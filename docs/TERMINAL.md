# NEXUS terminal

The Telegram Mini App now opens to the terminal. A pending state means the
server is fetching its data, not that individual indicators have finished. The
eight cards show observed trend, EMA 50/200, momentum, RSI, ATR/volatility,
support, resistance, and the final closed candle. Their count is the number
of actual values returned, not a signal score or a probability. The readings
use contiguous closed candles from the same frame as the result. A gap does
not get filled in, and a card with insufficient history shows unavailable.
The sparkline is rendered from actual closed prices.

Existing calibration, research-only SMARTY, the five-second chart policy,
and forecast deadlines are preserved. Results can still be NO TRADE. This UI
does not connect to a broker for order execution.

Provider status is deliberately separate from analysis. Cloudflare Workers AI
gets one read-only model-catalog check per normal process start using its
existing Railway variables, without sending candles or calling a model.
The status does not prove model inference. No OpenRouter adapter is enabled;
Gemini is the existing adapter and no extra live test is run against it.
No token, account ID, or upstream error body is exposed by the check.
