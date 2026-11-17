# NEXUS AI Mini App

The private Telegram home keyboard preserves its existing analysis action and adds a
single “Mini App ⚡” Web App button when public HTTPS is configured. The existing
Telegram message templates, /lo, /llo, scanner, and subscription settings are unchanged.

## Deployment

1. Deploy this branch, or merge its changes, to the service already running the
   Telegram bot. Do not start a second polling process using the same token.
2. The existing HTTP listener requires `PORT`. The app uses the service's
   `RAILWAY_PUBLIC_DOMAIN` by default. Set `MINI_APP_URL=https://your-public-host`
   if using a custom host for the same service. It must serve both
   `/mini-app/` and `/api/nexus-mini/v1/` on the same HTTPS origin.
3. Open the bot's private chat and send `/start`. After tapping the button, Telegram
   must supply a current signed session. Opening the web address in a normal browser
   cannot query analysis endpoints. No token, API key, or query-string auth is sent to
   the page. No new account, billing, or execution permissions are introduced.

## Analysis

- “تحليل سريع” runs the bot's existing technical LO engine, on closed candles.
  The engine tries eligible 5s, 15s, 30s, then 1m frames, and shows the actual
  frame used. Looser technical signals have no calibrated win probability.
- “تحليل دقيقة” uses the calibrated engine on 60-second candles. Some markets,
  including those with no active 1m calibration in the checked-in data, report
  **NO TRADE** rather than borrowing another frame or assigning false confidence.
- The latest closed candles must be recent and consecutive. The target is the
  next unopened slot following the candle in progress. A near or expired target
  is withheld by both server and browser. Times in the UI are Kuwait time.
- The catalogue includes the bot's markets when their feed is configured and an
  asset is available. Unavailable data returns a separate state, never a made-up
  candle or direction. Forex and OTC do not substitute for one another.
- The Mini App reads prices and forecasts. It does not send orders, publish
  notifications, or alter Telegram users' analysis modes.

## Tests

`python -m pytest -q tests/test_nexus_mini.py` exercises signed sessions, access
gates, separate mode routing, fallback, stale bars and closed-only results.
These tests validate the plumbing and timing, not the model's live hit rate.
