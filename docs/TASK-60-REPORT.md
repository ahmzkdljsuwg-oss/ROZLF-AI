# ROZLF AI — TASK 60 REPORT (Panel Redesign & System Repair)

## 1. What was actually wrong (root cause)

The web service that holds `TELEGRAM_BOT_TOKEN` was running in **health-only mode**.
`config.py` derived its role from `RAILWAY_SERVICE_NAME`, and the service name is
`web`, so `web_only` became `True` and `main.py` skipped `dp.start_polling(...)`.
The bot process therefore started, served `/health`, and never consumed Telegram
updates. `/start` had no polling worker to answer it, which is why menu changes
were deployed repeatedly but never appeared in Telegram. This is the real Task O
cause, not a button label problem.

Fix: the default role is now `bot` (polls Telegram **and** serves health on
`PORT`). Health-only mode must be requested explicitly with
`ROZLF_ROLE=health` (or `web-only`). The EO Bridge is a separate Railway service
built from `eo_bridge/` and does not run the root `main.py`, so there is still
exactly one polling instance.

## 2. Panel redesign

- Main menu: every market is a first-class button — 🧠 SMARTY MARKET, ⚽ FOOTBALL
  INDEX, 💎 LUXURY INDEX, 🤖 AI INDEX, 🏏 CRICKET INDEX, 💱 FOREX MARKET — plus
  📡 LIVE SIGNALS, 📜 SIGNAL HISTORY, 📊 PERFORMANCE STATISTICS, ⚙️ SETTINGS,
  🖥️ SYSTEM STATUS. OTC and GOLD ANALYSIS are gone.
- Market page: market name, EO asset ID, live data state, and the explicit
  distinction between the candle frame used for analysis and the trade expiry.
- Two duration modes: 🤖 SMART DURATION (engine chooses from the market's real
  supported expiries) and ✋ MANUAL DURATION (only durations the source supports).
- Signal card is a single canonical function, so the template cannot drift:

```
📊 MARKET: SMARTY
💹 ASSET: SMRTY

🟢 SIGNAL: BUY 🟢      (or 🔴 SELL 🛑 / ⚪ NO TRADE)

⏱️ TRADE TIME: 30 SEC

🎯 TRADE CONFIDENCE: 73%
```

  NO TRADE always renders `—` for time and confidence. Confidence is computed
  from evidence quality only and is never a guaranteed win rate. The card carries
  no extra fields; analysis evidence is behind "🔍 WHY THIS SIGNAL".
- Removed the old fixed 80% style output; a test asserts two different evidence
  scores produce two different cards.
- History, statistics, settings, live signals and system status were rewritten
  with the same visual hierarchy and honest labels (ACTIVE/UNVERIFIED excluded
  from win rate, per-market W/L/D/WR, profit factor from price moves).

## 3. Files changed

- `config.py` — role default `bot`; `web_only` only for explicit health role.
- `bot/formatting.py` — header/menus, signal card, history, stats, status,
  market page, analysis details, unrestricted-copy removal.
- `bot/keyboards/menus.py` — market/navigation keyboards, result menu with
  WHY / RE-ANALYSE / MAIN.
- `bot/handlers/menus.py` — market page wiring, one presentation path for all
  markets, cached analysis details, removed GOLD branch and duplicate NO TRADE
  screens.
- `database/repository.py` — per-market statistics and price-based profit factor.
- `tests/test_config.py`, `tests/test_bot_ui.py`, `tests/test_evidence_engine.py`,
  `tests/test_handlers.py`, `tests/test_unified_flow.py` — updated expectations.
- `tests/test_panel_v2.py` — new panel/template/navigation tests.

## 4. Verification performed

- `pytest -q`: **148 passed, 3 skipped** (the 3 skips require live external
  credentials and are unchanged).
- `scripts/verify_build.py`: `ROZLF BUILD CHECK OK`.
- `python -m compileall`: clean.
- Templates asserted exactly for BUY, SELL and NO TRADE.
- Empty menu, unavailable market, missing cache, six-market welcome and
  per-market stats asserted.
- **Not verified here:** live Telegram delivery and physical button presses.
  The workspace has no `TELEGRAM_BOT_TOKEN`, so a real Bot API send could not be
  performed from this session. No claim is made that the user's Telegram UI was
  observed.

## 5. Railway

Deployed from `main` after commit. Expected services:

- **web** (this repo, root `main.py`): polling + `/health`; `/health` must now
  report `"role": "bot"` and `"polling": true` while the process runs.
- **worker** (EO Bridge, root `eo_bridge`): unchanged, must stay green and
  connected; no Telegram polling there.

If `polling` is false after deploy, the service still has an old
`RAILWAY_SERVICE_NAME`-based build or a second instance holds the token; the
startup log will show the Telegram conflict message.

## Post-deploy verification (build 2cd78ae)

- The web service returned HTTP 502 because `main.py` exited at startup (missing Telegram token) after the role fix made it a polling process.
- `main.py` now starts the health server before Telegram/DB initialisation, keeps it alive in `degraded`/`no-telegram-token` state, and never takes the process down for a missing token or a transient API error.
- Deployed `/health` is `status: ok`, `build: 2cd78ae`, `menu_version: M3`, and lists exactly 11 buttons: six markets, LIVE SIGNALS, SIGNAL HISTORY, PERFORMANCE STATISTICS, SETTINGS, SYSTEM STATUS. No OTC and no GOLD.
- The same deploy also updated the EO Bridge service: `/health` reports `ROZLF-EO-BRIDGE`, `connected: true`, `assets: 150`, `build: 2cd78ae`.
- **Blocking fact:** the deployed web service reports `telegram_configured: false`, `ai: false`, `bridge_configured: false`, `database_driver: sqlite`, so its Railway service has none of the project variables. Telegram polling therefore cannot start from this service. The variables must be present on the service that runs polling (`web` here); no secret value is needed in chat.
- No real Telegram message was sent from this environment (no token available here), so delivery of the new menu in the user's Telegram client is not claimed as tested.
