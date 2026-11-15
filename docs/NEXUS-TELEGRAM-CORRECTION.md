# NEXUS AI — Telegram-only correction report

Date: 2026-11-15
Branch: `lemon/rozlf-telegram-v2`
Scope: the existing ROZLF AI Telegram bot in this repository. No new project was created.

## 1. What was deleted

- The complete Telegram Mini App package: `mini_app/` (`api.py`, `app_api.py`,
  `app_payload.py`, `app_service.py`, `auth.py`, `engine_client.py`, `service.py`
  and `static/`).
- Its tests: `tests/test_mini_app.py`, `tests/test_app_api.py`.
- Its documentation: `docs/MINI-APP.md`, `docs/ENGINE-API.md`.
- Its verification script: `scripts/verify_engine_link.py`.
- The `miniapp` Telegram command, all Web App buttons and the persistent
  `MenuButtonWebApp` item. Startup now resets the chat menu button to normal
  commands (`MenuButtonCommands`).
- Mini App configuration from `config.py` (`MINI_APP_URL`, `ENGINE_API_URL`,
  `ROZLF_ROLE`, `role`, `web_only`, `mini_app_url`, `engine_api_url`).
- Mini App variables and sections from `.env.example` and `README.md`.

No ROZLF market, analysis engine, bridge, database table or working tool was
deleted. There is no web UI and no iPhone app in this repository.

## 2. What was re-implemented inside the bot

- `/start` and `/menu` open: `WELCOME BACK 👋`, `NEXUS AI 🤖`, subtitle and one
  button `حلل 🤖`.
- `حلل 🤖` opens seven separate vertical market buttons in this exact order:
  OTC, SMARTY, FOOTBALL, LUXURY, AI INDEX, CRICKET, FOREX.
- Each market is analysed only through its own verified provider. OTC / SMARTY /
  index markets use the ExpertOption bridge only; FOREX uses its own providers;
  no market borrows another market's prices.
- Automatic analysis reads closed candles and the current candle, computes
  indicators, compares strategies, chooses entry time and duration from the
  computed evidence, and never forces a duration for `NO TRADE`.
- Recommendation card:
  `NEXUS AI 🤖 / 📊 السوق / ⏱️ الوقت (مدة + وقت الدخول) / 📈 الصفقة / 🎯 الثقة`
  followed by `خذ صفقة أخرى 🔄`, `📊 كل الأسواق`, `🏠 الرئيسية`.
- `خذ صفقة أخرى` recomputes the market and suppresses an identical result for
  10 minutes.
- No verified feed → `DATA UNAVAILABLE`, `NO TRADE`, confidence `—`, and no
  stored signal.
- Gemini and Mistral now run inside the automatic analysis path, not only in the
  extra tools. Both receive the same computed evidence. If any configured model
  disagrees with the technical direction (or answers `NO TRADE`), the signal is
  blocked as a conflict. A model that is unavailable is recorded as unavailable
  and cannot invent a verdict.
- Existing advanced tools remain reachable through `🛠 أدوات إضافية`; nothing
  working was removed to make room for NEXUS.

## 3. Files changed

- `bot/handlers/menus.py`, `bot/keyboards/menus.py`, `bot/formatting.py`
- `bot/context.py`, `services/market_analysis.py`, `config.py`, `main.py`
- `ai/gemini.py` (new), `ai/review.py` (new), `ai/mistral.py`
- `tests/test_nexus_telegram.py`, `tests/test_ai_review.py` (new),
  `tests/test_config.py`
- `.env.example`, `README.md`

## 4. Verification actually run

| Check | Result |
|---|---|
| Python compilation (`compileall`) | passed |
| Full test suite | **369 passed, 3 skipped in 15.94s** |
| Handler flow (`nx:market`, `nx:again`, card, duplicate suppression) | passed in tests |
| AI review agreement and disagreement | passed in tests |
| AI review inside `MarketAnalysisService` | passed in tests |
| DATA UNAVAILABLE without a market source | passed in tests |
| `import main` | passed |
| Health server start without a Telegram token | HTTP 200 on `/health`, `polling:false` |
| Mini App / WebApp references in application code | none |

Not tested here: a live Telegram conversation, because this workspace has no
`TELEGRAM_BOT_TOKEN` and no `.env`. Therefore no real bot screenshot or video
was produced. The button callbacks were exercised through the bot's own handler
functions with fake Telegram callbacks, which is the strongest test possible
without a token.

## 5. Remaining truth about data sources

- FOREX / GOLD have real providers when `TWELVE_DATA_API_KEY` or the configured
  Swissquote feed is available.
- OTC, SMARTY, FOOTBALL, LUXURY, AI INDEX and CRICKET require a working
  ExpertOption bridge (`EO_BRIDGE_URL` + `EO_BRIDGE_KEY`). Without it the bot
  shows `DATA UNAVAILABLE`; it does not substitute FOREX prices.
- Gemini needs `GEMINI_API_KEY`; Mistral needs `MISTRAL_API_KEY`. Both are
  optional and their absence never breaks the technical engine.

## 6. Railway

Start command remains `sh -c "python scripts/verify_build.py && exec python main.py"`,
Polling only, one replica. Extra variables for this change: `GEMINI_API_KEY`,
`GEMINI_MODEL`. Nothing was deployed.
